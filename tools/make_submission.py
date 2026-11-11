#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_submission.py -- write the submission CSV of the AAE4203 accuracy challenge.

The submission file is NOT one of the observation tables: according to the
tutorial (Section 9.1, Table 14) it has exactly five columns

    gps_week,gps_tow_s,x_ecef_m,y_ecef_m,z_ecef_m

one row per epoch in time order, positions in ECEF metres with three decimals,
named GXX_benchmark.csv (benchmark dataset) or GXX_owndata.csv (own data),
where XX is the two-digit group number.

Input can be either
  * a trajectory in RTKLIB .pos format (latitude/longitude/height), e.g. the
    output of RTKPOST or of an SPP run, or
  * the long-format solution table written by tools/spp_versions.py
    (work/spp_ablation/spp_solutions.csv, columns dataset/version/...).

Examples
    # own data, best estimator (v4, multi-GNSS + FDE), group 05
    python3 tools/make_submission.py --solutions work/spp_ablation/spp_solutions.csv \
            --dataset Move --version v4 --group 05 --kind owndata

    # a .pos produced by RTKPOST on the benchmark dataset
    python3 tools/make_submission.py --pos out/benchmark.pos --group 05 --kind benchmark

    # validate a file before uploading
    python3 tools/make_submission.py --check submission/G05_owndata.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from datetime import datetime, timedelta, timezone

RE_WGS84 = 6378137.0
F_WGS84 = 1.0 / 298.257223563
GPS_EPOCH = datetime(1980, 1, 6, tzinfo=timezone.utc)
HEADER = ["gps_week", "gps_tow_s", "x_ecef_m", "y_ecef_m", "z_ecef_m"]


def llh_to_ecef(lat_deg, lon_deg, h):
    a, f = RE_WGS84, F_WGS84
    e2 = f * (2.0 - f)
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    N = a / math.sqrt(1.0 - e2 * math.sin(lat) ** 2)
    return ((N + h) * math.cos(lat) * math.cos(lon),
            (N + h) * math.cos(lat) * math.sin(lon),
            (N * (1.0 - e2) + h) * math.sin(lat))


# --------------------------------------------------------------------------- #
# readers
# --------------------------------------------------------------------------- #
def read_pos(path):
    """RTKLIB .pos, llh -> [(week, tow, lat, lon, h)]"""
    out = []
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
            sec = (dt.replace(tzinfo=timezone.utc) - GPS_EPOCH).total_seconds()
            week = int(math.floor(sec / 604800.0))
            out.append((week, sec - week * 604800.0, lat, lon, h))
    return out


def read_solutions(path, dataset, version):
    """long-format solution table -> [(week, tow, lat, lon, h)]"""
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if dataset and r["dataset"] != dataset:
                continue
            if version and r["version"] != version:
                continue
            out.append((int(r["gps_week"]), float(r["gps_tow_s"]),
                        float(r["lat_deg"]), float(r["lon_deg"]),
                        float(r["height_m"])))
    out.sort(key=lambda t: (t[0], t[1]))
    return out


# --------------------------------------------------------------------------- #
# writer / checker
# --------------------------------------------------------------------------- #
def to_ecef(rows):
    out = []
    for week, tow, lat, lon, h in rows:
        x, y, z = llh_to_ecef(lat, lon, h)
        out.append((week, tow, x, y, z))
    return out


def screen_speed(rows, max_speed):
    """Drop epochs whose implied speed from the last accepted epoch exceeds
    max_speed (m/s).  Physically impossible jumps are gross errors of the
    single-point solution, not motion of the platform."""
    kept, dropped = [], []
    anchor = None
    for r in rows:
        if anchor is None:
            kept.append(r)
            anchor = r
            continue
        dt = (r[0] - anchor[0]) * 604800.0 + (r[1] - anchor[1])
        d = math.dist(r[2:], anchor[2:])
        if dt > 0 and d / dt > max_speed:
            dropped.append((r, d / dt))
        else:
            kept.append(r)
            anchor = r
    return kept, dropped


def write_submission(rows_ecef, out_path):
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(HEADER)
        for week, tow, x, y, z in rows_ecef:
            w.writerow([week, f"{tow:.3f}", f"{x:.3f}", f"{y:.3f}", f"{z:.3f}"])
    return len(rows_ecef)


def check_file(path, verbose=True):
    """Format checks that mirror tools/check_submission.py of the course repo."""
    errs, warns = [], []
    with open(path, newline="", encoding="utf-8") as fh:
        rd = csv.reader(fh)
        try:
            header = next(rd)
        except StopIteration:
            return ["file is empty"], []
        if [h.strip() for h in header] != HEADER:
            errs.append(f"header is {header}, expected {HEADER}")
        n = 0
        prev = None
        for k, row in enumerate(rd, start=2):
            if not row or all(not c.strip() for c in row):
                continue
            if len(row) != 5:
                errs.append(f"line {k}: {len(row)} columns")
                continue
            try:
                week = int(row[0])
                tow = float(row[1])
                x, y, z = (float(row[2]), float(row[3]), float(row[4]))
            except ValueError:
                errs.append(f"line {k}: non-numeric field")
                continue
            if not (1000 <= week <= 3000):
                errs.append(f"line {k}: implausible GPS week {week}")
            if not (0.0 <= tow < 604800.0):
                errs.append(f"line {k}: tow {tow} outside [0, 604800)")
            r = math.sqrt(x * x + y * y + z * z)
            if not (6.2e6 < r < 6.6e6):
                errs.append(f"line {k}: |r| = {r / 1e3:.1f} km is not on the Earth")
            if prev is not None and (week, tow) <= prev:
                errs.append(f"line {k}: epoch not strictly increasing")
            prev = (week, tow)
            if len(str(row[2]).split(".")[-1]) > 3:
                warns.append(f"line {k}: more than 3 decimals in x")
            n += 1
    if n == 0:
        errs.append("no data rows")
    if verbose:
        print(f"checked {path}: {n} epochs")
        for e in errs[:10]:
            print("  ERROR  ", e)
        for w in warns[:5]:
            print("  warning", w)
        if len(errs) > 10:
            print(f"  ... {len(errs) - 10} more errors")
        print("  result:", "OK" if not errs else f"{len(errs)} error(s)")
    return errs, warns


def main():
    ap = argparse.ArgumentParser(description="Write/validate the submission CSV "
                                             "(gps_week,gps_tow_s,x,y,z)")
    ap.add_argument("--pos", help="RTKLIB .pos file (llh)")
    ap.add_argument("--solutions", help="long-format solution table "
                                        "(work/spp_ablation/spp_solutions.csv)")
    ap.add_argument("--dataset", help="dataset column to select in --solutions")
    ap.add_argument("--version", help="version column to select in --solutions")
    ap.add_argument("--group", default="05", help="two-digit group number (default 05)")
    ap.add_argument("--kind", default="owndata", choices=["owndata", "benchmark"],
                    help="file name suffix (default owndata)")
    ap.add_argument("--out", help="explicit output path")
    ap.add_argument("--max-speed", type=float, default=0.0,
                    help="drop epochs whose implied speed from the last "
                         "accepted epoch exceeds this value (m/s); 0 = keep all")
    ap.add_argument("--check", help="only validate this file")
    args = ap.parse_args()

    if args.check:
        errs, _ = check_file(args.check)
        return 0 if not errs else 1

    if args.pos:
        rows = read_pos(args.pos)
    elif args.solutions:
        rows = read_solutions(args.solutions, args.dataset, args.version)
    else:
        print("need --pos or --solutions", file=sys.stderr)
        return 2

    if not rows:
        print("no epoch selected", file=sys.stderr)
        return 2

    g = args.group.strip().lstrip("Gg")
    g = g.zfill(2)
    out = args.out or os.path.join("submission", f"G{g}_{args.kind}.csv")
    ecef = to_ecef(rows)
    if args.max_speed > 0.0:
        ecef, dropped = screen_speed(ecef, args.max_speed)
        if dropped:
            v = sorted(d for _, d in dropped)
            print(f"speed screening at {args.max_speed:.0f} m/s: removed "
                  f"{len(dropped)} epochs "
                  f"({v[0]:.0f}..{v[-1]:.0f} m/s)")
    n = write_submission(ecef, out)
    print(f"wrote {out}: {n} epochs "
          f"({ecef[0][0]} {ecef[0][1]:.1f} .. {ecef[-1][0]} {ecef[-1][1]:.1f})")
    errs, _ = check_file(out)
    return 0 if not errs else 1


if __name__ == "__main__":
    sys.exit(main())
