#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
csv_spp_check.py -- end-to-end validation of the rinex2csv output.

Reads the five quantity CSVs produced by rinex2csv.py, runs a plain weighted
least-squares single-point positioning (SPP) per epoch and reports the solution.
The result is compared with the RTKLIB/RTKPOST single solution (.pos) so that the
CSV chain can be checked against an independent implementation.

  P_corr = P_meas + sv_clock_correction_tgd_m - iono_slant_m - tropo_slant_m
  P_corr = |R(omega_e*tau) * (r_sat - r_rx)| + c * dt_rx

Usage
    python3 csv_spp_check.py --csv csv/Move --out work/check/Move_csv_spp.pos
    python3 csv_spp_check.py --csv csv/Move --ref work/spp/Move_spp.pos
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


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def ecef2pos(r):
    x, y, z = r
    a = RE_WGS84
    f = 1.0 / 298.257223563
    e2 = f * (2.0 - f)
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1.0 - e2))
    h = 0.0
    for _ in range(10):
        sl = math.sin(lat)
        N = a / math.sqrt(1.0 - e2 * sl * sl)
        h = p / math.cos(lat) - N
        lat_new = math.atan2(z, p * (1.0 - e2 * N / (N + h)))
        if abs(lat_new - lat) < 1e-14:
            lat = lat_new
            break
        lat = lat_new
    sl = math.sin(lat)
    N = a / math.sqrt(1.0 - e2 * sl * sl)
    h = p / math.cos(lat) - N
    return lat, lon, h


def pos2ecef(lat, lon, h):
    a = RE_WGS84
    f = 1.0 / 298.257223563
    e2 = f * (2.0 - f)
    N = a / math.sqrt(1.0 - e2 * math.sin(lat) ** 2)
    return ((N + h) * math.cos(lat) * math.cos(lon),
            (N + h) * math.cos(lat) * math.sin(lon),
            (N * (1.0 - e2) + h) * math.sin(lat))


def solve(rows, x0, sys_list=("G",), max_iter=8):
    """rows: list of dicts with pr, x/y/z, el, sys.

    Unknowns: x, y, z and one receiver clock bias per constellation (in metres).
    """
    x = list(x0) + [0.0] * len(sys_list)
    ncol = 3 + len(sys_list)
    sidx = {s: 3 + i for i, s in enumerate(sys_list)}
    for _ in range(max_iter):
        H, v, w = [], [], []
        for r in rows:
            rs = (r["x"], r["y"], r["z"])
            dx, dy, dz = rs[0] - x[0], rs[1] - x[1], rs[2] - x[2]
            rho = math.sqrt(dx * dx + dy * dy + dz * dz)
            if rho < 1e3:
                continue
            # RTKLIB geodist(): first order earth rotation (Sagnac) correction
            rho = rho + OMGE * (rs[0] * x[1] - rs[1] * x[0]) / CLIGHT
            hi = [-dx / math.sqrt(dx * dx + dy * dy + dz * dz),
                  -dy / math.sqrt(dx * dx + dy * dy + dz * dz),
                  -dz / math.sqrt(dx * dx + dy * dy + dz * dz)] + [0.0] * len(sys_list)
            hi[sidx[r["sys"]]] = 1.0
            H.append(hi)
            v.append(r["pr"] - (rho + x[sidx[r["sys"]]]))
            s = max(0.1, math.sin(r["el"] * DEG))
            w.append(s * s)
        if len(H) < ncol:
            return None, 0
        # normal equations
        A = [[sum(w[k] * H[k][i] * H[k][j] for k in range(len(H)))
              for j in range(ncol)] for i in range(ncol)]
        b = [sum(w[k] * H[k][i] * v[k] for k in range(len(H))) for i in range(ncol)]
        M = [row[:] + [b[i]] for i, row in enumerate(A)]
        ok = True
        for c in range(ncol):
            piv = max(range(c, ncol), key=lambda rr: abs(M[rr][c]))
            if abs(M[piv][c]) < 1e-12:
                ok = False
                break
            M[c], M[piv] = M[piv], M[c]
            for rr in range(c + 1, ncol):
                fac = M[rr][c] / M[c][c]
                for cc in range(c, ncol + 1):
                    M[rr][cc] -= fac * M[c][cc]
        if not ok:
            return None, 0
        d = [0.0] * ncol
        for rr in range(ncol - 1, -1, -1):
            s = M[rr][ncol] - sum(M[rr][cc] * d[cc] for cc in range(rr + 1, ncol))
            d[rr] = s / M[rr][rr]
        for i in range(ncol):
            x[i] += d[i]
        if max(abs(d[0]), abs(d[1]), abs(d[2])) < 1e-4:
            break
    return x, len(H)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="directory with the five CSV files")
    ap.add_argument("--out", help="write a .pos file (llh, RTKLIB style)")
    ap.add_argument("--ref", help="RTKLIB .pos file to compare with")
    ap.add_argument("--init", help="initial ECEF 'x/y/z' (default: first epoch, "
                                   "bootstrapped from the pseudoranges)")
    args = ap.parse_args()

    files = {}
    for name in ("pseudoranges_meas", "satellite_positions", "satellite_clock_bias",
                 "ionospheric_delay", "tropospheric_delay"):
        files[name] = read_csv(os.path.join(args.csv, name + ".csv"))
    n = len(files["pseudoranges_meas"])
    for k, v in files.items():
        if len(v) != n:
            sys.exit(f"row mismatch in {k}.csv: {len(v)} vs {n}")

    # epoch metadata (GPS week/TOW) and linearisation point from epochs.csv
    rows_epoch = read_csv(os.path.join(args.csv, "epochs.csv"))
    ep_meta = {int(r["epoch_id"]): (int(r["gps_week"]), float(r["gps_tow_s"]))
               for r in rows_epoch}

    # group by epoch (identical row order in all files)
    epochs = {}
    for i in range(n):
        pr = files["pseudoranges_meas"][i]
        sp = files["satellite_positions"][i]
        cb = files["satellite_clock_bias"][i]
        io = files["ionospheric_delay"][i]
        tr = files["tropospheric_delay"][i]
        e = int(pr["epoch_id"])
        prec = (float(pr["pseudorange_m"]) + float(cb["sv_clock_correction_tgd_m"])
                - float(io["iono_slant_m"] or 0.0)
                - float(tr["tropo_slant_m"] or 0.0))
        rec = {
            "pr": prec,
            "el": float(pr["elevation_deg"]),
            "x": float(sp["x_ecef_m"]), "y": float(sp["y_ecef_m"]),
            "z": float(sp["z_ecef_m"]),
            "clk": float(cb["sv_clock_correction_tgd_m"]),
            "iono": float(io["iono_slant_m"] or 0.0),
            "tropo": float(tr["tropo_slant_m"] or 0.0),
            "t": float(pr["gps_tow_s"]),
            "sys": pr["sys"],
        }
        epochs.setdefault(e, {"tow": rec["t"], "rows": []})["rows"].append(rec)

    # initial receiver position: mean of satellite positions is a poor start;
    # use a robust bootstrap: start from the earth centre offset by the
    # difference of measured/computed ranges (single iteration from (0,0,0)+R).
    # linearisation point from epochs.csv (RINEX APPROX POSITION XYZ)
    ep = rows_epoch
    x = [float(ep[0]["rx_x_ecef_m"]), float(ep[0]["rx_y_ecef_m"]),
         float(ep[0]["rx_z_ecef_m"]), 0.0]
    if args.init:
        x = [float(v) for v in args.init.split("/")] + [0.0]

    sys_list = sorted({r["sys"] for e in epochs for r in epochs[e]["rows"]})
    print(f"constellations: {','.join(sys_list)}")
    x0 = x[:3]
    out = []
    for e in sorted(epochs):
        rows = epochs[e]["rows"]
        sol, ns = solve(rows, x0, sys_list)
        if sol is None:
            continue
        x0 = sol[:3]
        lat, lon, h = ecef2pos(sol[:3])
        wk, tow = ep_meta[e]
        out.append((wk, tow, lat / DEG, lon / DEG, h, ns))

    if not out:
        sys.exit("no solution")

    lats = [o[2] for o in out]
    lons = [o[3] for o in out]
    hs = [o[4] for o in out]
    print(f"epochs solved : {len(out)}")
    print(f"lat  mean/std : {sum(lats)/len(lats):.9f} deg  "
          f"{_std(lats):.3e} deg")
    print(f"lon  mean/std : {sum(lons)/len(lons):.9f} deg  "
          f"{_std(lons):.3e} deg")
    print(f"hgt  mean/std : {sum(hs)/len(hs):.3f} m  {_std(hs):.3f} m")
    print(f"mean #sats    : {sum(o[5] for o in out)/len(out):.2f}")

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write("% csv_spp_check.py -- WLS SPP from rinex2csv CSV files\n")
            fh.write("%  GPST                  latitude(deg) longitude(deg)  "
                     "height(m)   Q  ns\n")
            for wk, tow, lat, lon, h, ns in out:
                dt = GPS_EPOCH + timedelta(seconds=wk * 604800.0 + tow)
                fh.write(f"{dt.strftime('%Y/%m/%d %H:%M:%S')}.{int(round((dt.microsecond)/1000)):03d}"
                         f"  {lat:14.9f} {lon:14.9f} {h:12.4f}   5 {ns:3d}\n")
        print(f"wrote {args.out}")

    if args.ref:
        ref = _read_pos(args.ref)
        _compare(out, ref)


GPS_EPOCH = datetime(1980, 1, 6, tzinfo=timezone.utc)


def _read_pos(path):
    """RTKLIB .pos -> {gps_seconds: (lat, lon, h)}"""
    rows = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("%") or not line.strip():
                continue
            tok = line.split()
            if len(tok) < 5:
                continue
            try:
                dt = datetime.strptime(tok[0] + " " + tok[1], "%Y/%m/%d %H:%M:%S.%f")
                lat, lon, h = float(tok[2]), float(tok[3]), float(tok[4])
            except ValueError:
                continue
            t = (dt.replace(tzinfo=timezone.utc) - GPS_EPOCH).total_seconds()
            rows[t] = (lat, lon, h)
    return rows


def _compare(out, ref):
    d = []
    for wk, tow, lat1, lon1, h1, _ in out:
        t = wk * 604800.0 + tow
        key = min(ref, key=lambda k: abs(k - t)) if ref else None
        if key is None or abs(key - t) > 0.5:
            continue
        lat2, lon2, h2 = ref[key]
        dn = (lat1 - lat2) * DEG * 6371000.0
        de = (lon1 - lon2) * DEG * 6371000.0 * math.cos(lat1 * DEG)
        du = h1 - h2
        d.append((de, dn, du))
    n = len(d)
    if n == 0:
        print("no common epochs to compare")
        return
    nrm = math.sqrt(sum(v[0] ** 2 + v[1] ** 2 + v[2] ** 2 for v in d) / len(d))
    en = [math.hypot(v[0], v[1]) for v in d]
    en.sort()
    print(f"\ncomparison with {n} RTKLIB single-solution epochs")
    print(f"  E mean/std : {sum(v[0] for v in d)/len(d):8.3f} / {_std([v[0] for v in d]):7.3f} m")
    print(f"  N mean/std : {sum(v[1] for v in d)/len(d):8.3f} / {_std([v[1] for v in d]):7.3f} m")
    print(f"  U mean/std : {sum(v[2] for v in d)/len(d):8.3f} / {_std([v[2] for v in d]):7.3f} m")
    print(f"  3D RMS     : {nrm:8.3f} m")
    print(f"  2D 95%     : {en[int(0.95*(len(en)-1))]:8.3f} m")


def _std(v):
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / max(1, len(v) - 1))


if __name__ == "__main__":
    main()
