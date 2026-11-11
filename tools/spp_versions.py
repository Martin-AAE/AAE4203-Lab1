#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
spp_versions.py -- SPP variants used for the ablation of Lab 1.

    v1  GPS only, one receiver clock, unweighted            (the original solver)
    v2  GPS + Galileo + BeiDou, one clock per constellation (inter-system bias)
    v3  v2 + elevation weighting  w = sin^2(el)
    v4  v3 + residual-based outlier rejection (FDE loop)

Every version reads the same CSV tables produced by tools/rinex2csv.py, so the
only difference between the runs is the estimator.  Versions are kept side by
side on purpose ("keep the original version for comparison").

Model
    P_corr = P_meas + c*dt_sv - c*TGD - I - T          (columns of the CSVs)
    P_corr = |r_sat - r_rx| + c*dt_rx(system) + e
    Sagnac: rho += omega_e*(x_s*y_r - y_s*x_r)/c       (RTKLIB geodist)

Outlier rejection (v4)
    after convergence, with sigma0^2 = v'Wv/(n-u) and
        Qv_ii = 1/w_i - h_i (H'WH)^-1 h_i'
    the normalised residual  w_i = v_i / (sigma*sqrt(Qv_ii))  is tested against
    a threshold k (default 4); the worst satellite is removed and the epoch is
    solved again, until the test passes or only (u+1) satellites remain.

    Warning: if sigma is estimated from the same residuals (sigma0), a single
    gross error inflates sigma0 and masks itself.  A prior value (--sigma, the
    expected code noise in metres at zenith, divided by sin(el)) is therefore
    used by default, as in RAIM.

Usage
    python3 tools/spp_versions.py --csv csv/Move_multi  --out work/spp_ablation/Move
    python3 tools/spp_versions.py --csv csv/static_multi --out work/spp_ablation/static
    python3 tools/spp_versions.py --all          # both, plus the summary table
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from datetime import datetime, timedelta, timezone

CLIGHT = 299792458.0
OMGE = 7.2921151467e-5
RE_WGS84 = 6378137.0
DEG = math.pi / 180.0

VERSIONS = {
    "v1": dict(systems="G", weight="none", reject=False,
               label="GPS only, unweighted (original)"),
    "v2": dict(systems="GEC", weight="none", reject=False,
               label="+ Galileo, BeiDou (one clock per system)"),
    "v3": dict(systems="GEC", weight="elev", reject=False,
               label="+ elevation weighting sin2(el)"),
    "v4": dict(systems="GEC", weight="elev", reject=True,
               label="+ residual-based outlier rejection (FDE)"),
}


# --------------------------------------------------------------------------- #
# small linear algebra
# --------------------------------------------------------------------------- #
def solve_linear(A, b):
    """Gaussian elimination with partial pivoting; returns None if singular."""
    n = len(b)
    M = [list(A[i]) + [b[i]] for i in range(n)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            return None
        M[c], M[piv] = M[piv], M[c]
        for r in range(c + 1, n):
            f = M[r][c] / M[c][c]
            for k in range(c, n + 1):
                M[r][k] -= f * M[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        s = M[r][n] - sum(M[r][k] * x[k] for k in range(r + 1, n))
        x[r] = s / M[r][r]
    return x


def inverse(A):
    n = len(A)
    M = [list(A[i]) + [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            return None
        M[c], M[piv] = M[piv], M[c]
        d = M[c][c]
        M[c] = [v / d for v in M[c]]
        for r in range(n):
            if r != c:
                f = M[r][c]
                M[r] = [a - f * b for a, b in zip(M[r], M[c])]
    return [row[n:] for row in M]


def ecef2pos(r):
    x, y, z = r
    a, f = RE_WGS84, 1.0 / 298.257223563
    e2 = f * (2.0 - f)
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1.0 - e2))
    h = 0.0
    for _ in range(8):
        sl = math.sin(lat)
        N = a / math.sqrt(1.0 - e2 * sl * sl)
        h = p / math.cos(lat) - N
        lat = math.atan2(z, p * (1.0 - e2 * N / (N + h)))
    sl = math.sin(lat)
    N = a / math.sqrt(1.0 - e2 * sl * sl)
    h = p / math.cos(lat) - N
    return lat, lon, h


# --------------------------------------------------------------------------- #
# input
# --------------------------------------------------------------------------- #
def load_epochs(csv_dir):
    """Read the five quantity tables and group them per epoch."""
    with open(os.path.join(csv_dir, "pseudoranges_meas.csv"), newline="",
              encoding="utf-8") as fh:
        pr = list(csv.DictReader(fh))
    with open(os.path.join(csv_dir, "satellite_positions.csv"), newline="",
              encoding="utf-8") as fh:
        sp = list(csv.DictReader(fh))
    with open(os.path.join(csv_dir, "satellite_clock_bias.csv"), newline="",
              encoding="utf-8") as fh:
        cb = list(csv.DictReader(fh))
    with open(os.path.join(csv_dir, "ionospheric_delay.csv"), newline="",
              encoding="utf-8") as fh:
        io = list(csv.DictReader(fh))
    with open(os.path.join(csv_dir, "tropospheric_delay.csv"), newline="",
              encoding="utf-8") as fh:
        tr = list(csv.DictReader(fh))
    with open(os.path.join(csv_dir, "epochs.csv"), newline="", encoding="utf-8") as fh:
        ep = list(csv.DictReader(fh))

    epochs = {}
    for k in range(len(pr)):
        eid = int(pr[k]["epoch_id"])
        rec = {
            "pr": (float(pr[k]["pseudorange_m"])
                   + float(cb[k]["sv_clock_correction_tgd_m"])
                   - float(io[k]["iono_slant_m"] or 0.0)
                   - float(tr[k]["tropo_slant_m"] or 0.0)),
            "x": float(sp[k]["x_ecef_m"]),
            "y": float(sp[k]["y_ecef_m"]),
            "z": float(sp[k]["z_ecef_m"]),
            "el": float(pr[k]["elevation_deg"]),
            "sys": pr[k]["sys"],
            "sat": pr[k]["sat_id"],
            "cn0": float(pr[k]["cn0_dbhz"] or 0.0),
        }
        epochs.setdefault(eid, {"tow": float(pr[k]["gps_tow_s"]),
                                "wk": int(pr[k]["gps_week"]),
                                "rows": []})["rows"].append(rec)

    apriori = {int(r["epoch_id"]): (float(r["rx_x_ecef_m"]),
                                    float(r["rx_y_ecef_m"]),
                                    float(r["rx_z_ecef_m"])) for r in ep}
    return epochs, apriori


# --------------------------------------------------------------------------- #
# the estimator
# --------------------------------------------------------------------------- #
def solve_epoch(rows, x0, systems, weight="none", reject=False, k_thr=4.0,
                max_iter=8, max_reject=None, sigma_prior=0.0):
    """Weighted least-squares SPP for one epoch.

    rows   : list of dicts (pr, x, y, z, el, sys, sat)
    x0     : apriori position [m]
    systems: constellations to use, e.g. 'G' or 'GEC'
    return : dict(state, n_used, rejected, rms, sigma0, n_iter)
    """
    use = [r for r in rows if r["sys"] in systems]
    if len(use) < 4:
        return None
    ncol = 3 + len(systems)
    sidx = {s: 3 + i for i, s in enumerate(systems)}
    rejected = []
    x = list(x0) + [0.0] * len(systems)

    for _ in range(max_iter):
        H, v, w, keep = [], [], [], []
        for r in use:
            dx, dy, dz = r["x"] - x[0], r["y"] - x[1], r["z"] - x[2]
            rho = math.sqrt(dx * dx + dy * dy + dz * dz)
            if rho < 1e3:
                continue
            rho += OMGE * (r["x"] * x[1] - r["y"] * x[0]) / CLIGHT
            h = [-dx / rho, -dy / rho, -dz / rho] + [0.0] * len(systems)
            h[sidx[r["sys"]]] = 1.0
            H.append(h)
            v.append(r["pr"] - (rho + x[sidx[r["sys"]]]))
            w.append(max(0.1, math.sin(r["el"] * DEG)) ** 2
                     if weight == "elev" else 1.0)
            keep.append(r)
        if len(H) < ncol:
            return None
        A = [[sum(w[k] * H[k][i] * H[k][j] for k in range(len(H)))
              for j in range(ncol)] for i in range(ncol)]
        b = [sum(w[k] * H[k][i] * v[k] for k in range(len(H))) for i in range(ncol)]
        dx = solve_linear(A, b)
        if dx is None:
            return None
        for i in range(ncol):
            x[i] += dx[i]
        if max(abs(dx[0]), abs(dx[1]), abs(dx[2])) < 1e-4:
            break

    # ---- residual-based outlier rejection (data snooping) ----------------
    if reject:
        n_rej_max = max_reject if max_reject is not None else max(0, len(use) - ncol)
        for _ in range(n_rej_max):
            H, v, w, keep = [], [], [], []
            for r in use:
                dx, dy, dz = r["x"] - x[0], r["y"] - x[1], r["z"] - x[2]
                rho = math.sqrt(dx * dx + dy * dy + dz * dz)
                rho += OMGE * (r["x"] * x[1] - r["y"] * x[0]) / CLIGHT
                h = [-dx / rho, -dy / rho, -dz / rho] + [0.0] * len(systems)
                h[sidx[r["sys"]]] = 1.0
                H.append(h)
                v.append(r["pr"] - (rho + x[sidx[r["sys"]]]))
                w.append(max(0.1, math.sin(r["el"] * DEG)) ** 2
                         if weight == "elev" else 1.0)
                keep.append(r)
            n, u = len(H), ncol
            if n <= u + 1:               # no redundancy left for a test
                break
            A = [[sum(w[t] * H[t][i] * H[t][j] for t in range(n))
                  for j in range(u)] for i in range(u)]
            Q = inverse(A)
            if Q is None:
                break
            vwv = sum(w[t] * v[t] * v[t] for t in range(n))
            sigma0 = math.sqrt(vwv / (n - u))
            sigma = sigma_prior if sigma_prior > 0.0 else sigma0
            worst, worst_val = None, 0.0
            for t in range(n):
                hv = [sum(H[t][i] * Q[i][j] * H[t][j] for i in range(u))
                      for j in range(u)]
                qv = 1.0 / w[t] - sum(H[t][i] * Q[i][j] * H[t][j]
                                      for i in range(u) for j in range(u))
                if qv <= 1e-9 or sigma <= 1e-9:
                    continue
                wn = abs(v[t]) / (sigma * math.sqrt(qv))
                if wn > worst_val:
                    worst, worst_val = t, wn
            if worst is None or worst_val <= k_thr:
                break                    # consistent solution
            rejected.append((keep[worst]["sat"], round(worst_val, 2),
                             round(keep[worst]["el"], 1),
                             round(keep[worst]["cn0"], 1)))
            use = [r for r in use if r is not keep[worst]]
            if len(use) < u + 1:
                break
            # re-solve with the reduced set
            for _ in range(max_iter):
                H, v, w = [], [], []
                for r in use:
                    dx, dy, dz = r["x"] - x[0], r["y"] - x[1], r["z"] - x[2]
                    rho = math.sqrt(dx * dx + dy * dy + dz * dz)
                    rho += OMGE * (r["x"] * x[1] - r["y"] * x[0]) / CLIGHT
                    h = [-dx / rho, -dy / rho, -dz / rho] + [0.0] * len(systems)
                    h[sidx[r["sys"]]] = 1.0
                    H.append(h)
                    v.append(r["pr"] - (rho + x[sidx[r["sys"]]]))
                    w.append(max(0.1, math.sin(r["el"] * DEG)) ** 2
                             if weight == "elev" else 1.0)
                A = [[sum(w[t] * H[t][i] * H[t][j] for t in range(len(H)))
                      for j in range(u)] for i in range(u)]
                b = [sum(w[t] * H[t][i] * v[t] for t in range(len(H)))
                     for i in range(u)]
                d2 = solve_linear(A, b)
                if d2 is None:
                    return None
                for i in range(u):
                    x[i] += d2[i]
                if max(abs(d2[0]), abs(d2[1]), abs(d2[2])) < 1e-4:
                    break

    # ---- final residuals ---------------------------------------------------
    H, v, w = [], [], []
    for r in use:
        dx, dy, dz = r["x"] - x[0], r["y"] - x[1], r["z"] - x[2]
        rho = math.sqrt(dx * dx + dy * dy + dz * dz)
        rho += OMGE * (r["x"] * x[1] - r["y"] * x[0]) / CLIGHT
        v.append(r["pr"] - (rho + x[sidx[r["sys"]]]))
        w.append(max(0.1, math.sin(r["el"] * DEG)) ** 2 if weight == "elev" else 1.0)
    rms = math.sqrt(sum(wk * vk * vk for wk, vk in zip(w, v)) / len(v))
    return {"state": x, "n_used": len(use), "n_rejected": len(rejected),
            "rejected": rejected, "rms": rms, "systems": systems}


# --------------------------------------------------------------------------- #
# run one version on one dataset
# --------------------------------------------------------------------------- #
def run_version(csv_dir, version, out_pos=None, k_thr=4.0, sigma_prior=4.0):
    cfg = VERSIONS[version]
    epochs, apriori = load_epochs(csv_dir)
    x0 = list(apriori[min(apriori)])
    out = []
    n_rej = 0
    for eid in sorted(epochs):
        e = epochs[eid]
        res = solve_epoch(e["rows"], x0, cfg["systems"], cfg["weight"],
                          cfg["reject"], k_thr, sigma_prior=sigma_prior)
        if res is None:
            continue
        x0 = res["state"][:3]                 # warm start on the previous epoch
        lat, lon, h = ecef2pos(res["state"][:3])
        out.append({"epoch": eid, "wk": e["wk"], "tow": e["tow"],
                    "lat": lat / DEG, "lon": lon / DEG, "h": h,
                    "n": res["n_used"], "rej": res["n_rejected"],
                    "rms": res["rms"], "state": res["state"]})
        n_rej += res["n_rejected"]

    if out_pos:
        os.makedirs(os.path.dirname(os.path.abspath(out_pos)), exist_ok=True)
        with open(out_pos, "w", encoding="utf-8") as fh:
            fh.write(f"% {version}: {cfg['label']}\n")
            fh.write("%  GPST                  latitude(deg) longitude(deg)  "
                     "height(m)   Q  ns  \n")
            for o in out:
                fh.write(f"{_gpst_date(o['wk'], o['tow'])} {_hms(o['tow'])}  "
                         f"{o['lat']:14.9f} "
                         f"{o['lon']:14.9f} {o['h']:12.4f}   5 {o['n']:3d}\n")
    return {"version": version, **cfg, "solutions": out, "epochs_total": len(epochs),
            "n_rejected": n_rej}


def _gpst_date(week, tow):
    """GPS week/TOW -> calendar date string (GPST)."""
    dt = datetime(1980, 1, 6, tzinfo=timezone.utc) + \
        timedelta(seconds=week * 604800.0 + tow)
    return dt.strftime("%Y/%m/%d")


def _hms(tow):
    tow = tow % 86400.0
    # GPST calendar (week 2442, 2026-10-30)
    return (f"{int(tow // 3600):02d}:{int((tow % 3600) // 60):02d}:"
            f"{tow % 60:06.3f}")


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def read_pos(path):
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("%") or not line.strip():
                continue
            t = line.split()
            if len(t) < 5:
                continue
            try:
                out.append((float(t[2]), float(t[3]), float(t[4])))
            except ValueError:
                continue
    return out


def enu_vs(sol, ref, mode="scatter"):
    """Differences in E/N/U.

    mode='scatter' : about the mean of the solution itself (precision)
    mode='ref'     : with a reference trajectory of the same length
    """
    if mode == "scatter":
        mlat = sum(p[0] for p in sol) / len(sol)
        mlon = sum(p[1] for p in sol) / len(sol)
        mh = sum(p[2] for p in sol) / len(sol)
        de = [(p[1] - mlon) * 111320.0 * math.cos(math.radians(mlat)) for p in sol]
        dn = [(p[0] - mlat) * 111320.0 for p in sol]
        du = [p[2] - mh for p in sol]
    else:
        de, dn, du = [], [], []
        for p, q in zip(sol, ref):
            dn.append((p[0] - q[0]) * 111320.0)
            de.append((p[1] - q[1]) * 111320.0 * math.cos(math.radians(p[0])))
            du.append(p[2] - q[2])
    n = len(de)
    sd = lambda a: (sum((x - sum(a) / n) ** 2 for x in a) / max(1, n - 1)) ** 0.5
    r2 = [math.hypot(a, b) for a, b in zip(de, dn)]
    r2s = sorted(r2)
    return {
        "n": n,
        "meanE": sum(de) / n, "meanN": sum(dn) / n, "meanU": sum(du) / n,
        "sdE": sd(de), "sdN": sd(dn), "sdU": sd(du),
        "rms2": math.sqrt(sum(x * x for x in r2) / n),
        "p95": r2s[int(0.95 * n) - 1],
        "p50": r2s[int(0.50 * n) - 1],
    }


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def selftest(csv_dir="csv/static_multi", version="v4", bias=50.0,
             sigma_prior=4.0):
    """Inject a gross error into one pseudorange and check the FDE loop.

    The clean solution is the reference; the biased observation is then added and
    the version without rejection (v3) and with rejection (v4) are compared.
    """
    epochs, apriori = load_epochs(csv_dir)
    eid = sorted(epochs)[len(epochs) // 2]
    rows = [dict(r) for r in epochs[eid]["rows"]]
    cfg = VERSIONS[version]
    clean = solve_epoch(rows, apriori[eid], cfg["systems"], cfg["weight"], False)
    if clean is None:
        return 1
    # choose the satellite with the best elevation (largest influence)
    tgt = max((r for r in rows if r["sys"] in cfg["systems"]),
              key=lambda r: r["el"])
    bad_rows = [dict(r) for r in rows]
    for r in bad_rows:
        if r["sat"] == tgt["sat"]:
            r["pr"] += bias
    v3 = solve_epoch(bad_rows, apriori[eid], cfg["systems"], "elev", False)
    v4 = solve_epoch(bad_rows, apriori[eid], cfg["systems"], "elev", True,
                     sigma_prior=sigma_prior)

    def err(sol):
        return math.dist(sol["state"][:3], clean["state"][:3])

    print(f"selftest on {csv_dir}, epoch {eid}, satellite {tgt['sat']} "
          f"(el {tgt['el']:.1f} deg), injected bias +{bias:.0f} m")
    print(f"  no rejection    : position error {err(v3):7.2f} m, "
          f"residual RMS {v3['rms']:6.2f} m, rejected {v3['rejected']}")
    print(f"  with rejection  : position error {err(v4):7.2f} m, "
          f"residual RMS {v4['rms']:6.2f} m, rejected {v4['rejected']}")
    ok = (v4["n_rejected"] == 1 and tgt["sat"] in [r[0] for r in v4["rejected"]]
          and err(v4) < 0.2 * err(v3))
    print("  RESULT:", "PASS - the loop flags and removes the biased "
          "observation" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="SPP ablation: v1 original -> v4 FDE")
    ap.add_argument("--csv", help="directory of rinex2csv tables")
    ap.add_argument("--out", help="output prefix for the .pos files")
    ap.add_argument("--versions", default="v1,v2,v3,v4")
    ap.add_argument("--k", type=float, default=4.0, help="FDE threshold (sigma)")
    ap.add_argument("--ref", help="reference .pos for the trajectory comparison")
    ap.add_argument("--scatter", action="store_true",
                    help="also report scatter about the mean (static case)")
    ap.add_argument("--all", action="store_true",
                    help="run both datasets and print the summary table")
    ap.add_argument("--systems", default=None,
                    help="override the constellations, e.g. GREC (default: as "
                         "defined per version, G for v1 and GEC for v2-v4)")
    ap.add_argument("--sigma", type=float, default=4.0,
                    help="a-priori code noise at zenith (m) used by the FDE test")
    ap.add_argument("--solutions", action="store_true",
                    help="also write every epoch of every version to "
                         "work/spp_ablation/spp_solutions.csv")
    ap.add_argument("--selftest", action="store_true",
                    help="inject a bias into one pseudorange and check that the "
                         "FDE loop removes it")
    args = ap.parse_args()

    if args.selftest:
        return selftest(sigma_prior=args.sigma)

    versions = [v.strip() for v in args.versions.split(",") if v.strip()]
    if args.systems:
        for v in versions:
            if v in VERSIONS:
                VERSIONS[v]["systems"] = args.systems
    jobs = []
    if args.all:
        jobs = [("Move", "csv/Move_multi", "work/spp_ablation/Move",
                 "work/spp/Move_rtk_multi.pos"),
                ("static", "csv/static_multi", "work/spp_ablation/static",
                 "work/spp/static_rtk_multi.pos")]
    else:
        jobs = [("dataset", args.csv, args.out, args.ref)]

    rows = []
    all_sol = []
    for name, csv_dir, prefix, ref in jobs:
        ref_pos = read_pos(ref) if ref else None
        for v in versions:
            res = run_version(csv_dir, v, out_pos=f"{prefix}_{v}.pos",
                             k_thr=args.k, sigma_prior=args.sigma)
            all_sol.append((name, v, res))
            sol = [(o["lat"], o["lon"], o["h"]) for o in res["solutions"]]
            if not sol:
                print(f"{name:8s} {v}: no solution")
                continue
            st = enu_vs(sol, None, mode="scatter")
            line = {
                "dataset": name, "version": v, "label": res["label"],
                "solutions": len(sol), "epochs": res["epochs_total"],
                "availability": 100.0 * len(sol) / res["epochs_total"],
                "sats": sum(o["n"] for o in res["solutions"]) / len(sol),
                "rejected": res["n_rejected"],
                "rms": sum(o["rms"] for o in res["solutions"]) / len(sol),
                "sdE": st["sdE"], "sdN": st["sdN"], "sdU": st["sdU"],
                "r95": st["p95"],
            }
            if ref_pos:
                n = min(len(sol), len(ref_pos))
                d = enu_vs(sol[:n], ref_pos[:n], mode="ref")
                line.update({"meanE": d["meanE"], "meanU": d["meanU"],
                             "rms2": d["rms2"]})
            rows.append(line)
            print(f"{name:8s} {v}: {len(sol):4d}/{res['epochs_total']:4d} "
                  f"({line['availability']:5.1f} %) sats {line['sats']:5.2f} "
                  f"rej {line['rejected']:3d} rms {line['rms']:5.2f} m "
                  f"sigmaE/N/U {st['sdE']:.2f}/{st['sdN']:.2f}/{st['sdU']:.2f} "
                  f"95%R {st['p95']:.2f} m")

    # ---- summary table ----------------------------------------------------
    def table(sel):
        hdr = (f"{'dataset':8s} {'ver':3s} {'sol/epochs':>10s} {'avail':>6s} "
               f"{'sats':>5s} {'rej':>4s} {'res RMS':>7s} "
               f"{'sE':>5s} {'sN':>5s} {'sU':>5s} {'95%R':>5s}")
        lines = [hdr, "-" * len(hdr)]
        for r in rows:
            if r["dataset"] not in sel:
                continue
            lines.append(f"{r['dataset']:8s} {r['version']:3s} "
                         f"{r['solutions']:4d}/{r['epochs']:<5d} "
                         f"{r['availability']:6.1f} {r['sats']:5.2f} "
                         f"{r['rejected']:4d} {r['rms']:7.2f} "
                         f"{r['sdE']:5.2f} {r['sdN']:5.2f} {r['sdU']:5.2f} "
                         f"{r['r95']:5.2f}")
        return "\n".join(lines)

    print("\n" + table({r["dataset"] for r in rows}))

    base_dir = os.path.dirname(os.path.abspath(jobs[0][2])) if jobs else "."
    out_csv = os.path.join(base_dir, "summary.csv")
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nwrote {out_csv}")

    if args.solutions and all_sol:
        sol_csv = os.path.join(base_dir, "spp_solutions.csv")
        with open(sol_csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["dataset", "version", "epoch_id", "gps_week", "gps_tow_s",
                        "lat_deg", "lon_deg", "height_m", "n_sat", "n_rejected",
                        "residual_rms_m"])
            for name, v, res in all_sol:
                for o in res["solutions"]:
                    w.writerow([name, v, o["epoch"], o["wk"],
                                f"{o['tow']:.4f}", f"{o['lat']:.9f}",
                                f"{o['lon']:.9f}", f"{o['h']:.4f}",
                                o["n"], o["rej"], f"{o['rms']:.3f}"])
        print(f"wrote {sol_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
