#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ubx_hpposecef.py -- extract UBX-NAV-HPPOSECEF (receiver's own solution) to CSV.

This is the small, dependency-free counterpart of the course script
pyubx2_csv_converter_gui.py (Lab tutorial, Section 7.2): it keeps only the
NAV-HPPOSECEF message and writes

    csv/<dataset>_receiver/NAV-HPPOSECEF.csv

with the epoch in GPS week / seconds-of-week (the message only carries iTOW,
milliseconds of week, so the week is taken from the matching RINEX file or from
--week), the ECEF coordinates in metres and the geodetic coordinates.

The coordinates are centimetres with a 0.1 mm high-precision part:
    x = ecefX * 0.01 + ecefXHp * 0.0001      (same for y, z)

Optionally writes a RTKLIB .pos file (llh) so that the solution can be converted
to KML with pos2kml, next to the RTKLIB/RTKPOST solution (Lab tutorial Fig. 27).

Usage
    python3 tools/ubx_hpposecef.py --ubx input/Move.ubx --obs rinex/Move.obs \
            --out csv/Move_receiver --pos work/spp/Move_receiver.pos
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rinex2csv import ecef2pos, gps_iso_utc, read_obs, gps_week_tow, DEG  # noqa: E402

CLS_NAV, ID_HPPOSECEF = 0x01, 0x13


def iter_ubx(path):
    data = open(path, "rb").read()
    i, n = 0, len(data)
    while i < n - 8:
        if data[i] != 0xB5 or data[i + 1] != 0x62:
            i += 1
            continue
        cls, mid = data[i + 2], data[i + 3]
        ln = struct.unpack_from("<H", data, i + 4)[0]
        end = i + 6 + ln
        if end + 2 > n:
            break
        yield cls, mid, data[i + 6:end]
        i = end + 2


def parse_hpposecef(p, itow_off=4):
    if len(p) < 28:
        return None
    itow = struct.unpack_from("<I", p, itow_off)[0]
    ver = p[0] if itow_off == 4 else p[4]
    x, y, z = struct.unpack_from("<iii", p, 8)
    xh, yh, zh = struct.unpack_from("<bbb", p, 20)
    flags = p[23]
    pacc = struct.unpack_from("<I", p, 24)[0]
    return {
        "itow_ms": itow, "version": ver,
        "x": x * 0.01 + xh * 0.0001,
        "y": y * 0.01 + yh * 0.0001,
        "z": z * 0.01 + zh * 0.0001,
        "invalid": bool(flags & 0x01),
        "pacc": pacc * 0.0001,         # 0.1 mm -> m
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ubx", required=True)
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--obs", help="RINEX obs file, used to get the GPS week")
    ap.add_argument("--week", type=int, help="GPS week (if --obs is not given)")
    ap.add_argument("--pos", help="also write a RTKLIB .pos (llh) file")
    args = ap.parse_args()

    week = args.week
    leaps = 18
    if args.obs:
        obs = read_obs(args.obs, verbose=False)
        t0 = min(e[0] for e in obs.epochs)
        week, _ = gps_week_tow(t0)
        leaps = obs.leaps
    if week is None:
        sys.exit("need --obs or --week to resolve the GPS week")

    # ------------------------------------------------------------------ #
    # The u-blox interface description puts iTOW first, but the logs used
    # here carry [version, reserved[3], iTOW] instead.  Detect the layout
    # from the data: the true iTOW is a valid time of week that increases
    # monotonically, while the other candidate is constant (0).
    # ------------------------------------------------------------------ #
    payloads = [p for c, m, p in iter_ubx(args.ubx)
                if (c, m) == (CLS_NAV, ID_HPPOSECEF) and len(p) >= 28]
    if not payloads:
        sys.exit("no UBX-NAV-HPPOSECEF message found")

    def score(off):
        v = [struct.unpack_from("<I", p, off)[0] for p in payloads]
        if any(x >= 604800000 for x in v):
            return -1
        inc = sum(1 for a, b in zip(v, v[1:]) if 0 < b - a < 5000)
        return inc

    itow_off = 0 if score(0) > score(4) else 4
    print(f"iTOW at payload offset {itow_off} "
          f"(detected: {score(0)} / {score(4)} plausible steps)")

    rows = []
    for pay in payloads:
        r = parse_hpposecef(pay, itow_off)
        if r is None or r["invalid"]:
            continue
        tow = (r["itow_ms"] % 604800000) / 1000.0
        t = week * 604800.0 + tow
        lat, lon, h = ecef2pos((r["x"], r["y"], r["z"]))
        rows.append((t, tow, r, lat, lon, h))

    rows.sort(key=lambda x: x[0])
    if not rows:
        sys.exit("no valid UBX-NAV-HPPOSECEF message found")

    os.makedirs(args.out, exist_ok=True)
    csv_path = os.path.join(args.out, "NAV-HPPOSECEF.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["gps_week", "gps_tow_s", "utc_time_iso", "itow_ms",
                    "x_ecef_m", "y_ecef_m", "z_ecef_m",
                    "lat_deg", "lon_deg", "height_m",
                    "position_accuracy_m", "version"])
        for t, tow, r, lat, lon, h in rows:
            w.writerow([week, f"{tow:.3f}", gps_iso_utc(t, leaps), r["itow_ms"],
                        f"{r['x']:.4f}", f"{r['y']:.4f}", f"{r['z']:.4f}",
                        f"{lat / DEG:.9f}", f"{lon / DEG:.9f}", f"{h:.4f}",
                        f"{r['pacc']:.4f}", r["version"]])

    if args.pos:
        os.makedirs(os.path.dirname(os.path.abspath(args.pos)), exist_ok=True)
        with open(args.pos, "w", encoding="utf-8") as fh:
            fh.write("% UBX-NAV-HPPOSECEF -- receiver's own solution\n")
            fh.write("%  GPST                  latitude(deg) longitude(deg)  "
                     "height(m)   Q  ns\n")
            for t, tow, r, lat, lon, h in rows:
                dt = _gpst_calendar(t, leaps)
                fh.write(f"{dt}  {lat/DEG:14.9f} {lon/DEG:14.9f} {h:12.4f}"
                         f"   1   1\n")

    lat = [x[3] / DEG for x in rows]
    lon = [x[4] / DEG for x in rows]
    h = [x[5] for x in rows]
    print(f"NAV-HPPOSECEF: {len(rows)} epochs")
    print(f"  start/end  : {gps_iso_utc(rows[0][0], leaps)} .. "
          f"{gps_iso_utc(rows[-1][0], leaps)}")
    print(f"  lat  mean  : {sum(lat)/len(lat):.9f} deg  (span "
          f"{(max(lat)-min(lat))*111e3:.2f} m)")
    print(f"  lon  mean  : {sum(lon)/len(lon):.9f} deg  (span "
          f"{(max(lon)-min(lon))*111e3*math.cos(sum(lat)/len(lat)*DEG):.2f} m)")
    print(f"  hgt  mean  : {sum(h)/len(h):.3f} m")
    print(f"  wrote {csv_path}")
    if args.pos:
        print(f"  wrote {args.pos}")


def _gpst_calendar(t, leaps):
    from datetime import datetime, timedelta, timezone
    dt = datetime(1980, 1, 6, tzinfo=timezone.utc) + timedelta(seconds=t)
    return dt.strftime("%Y/%m/%d %H:%M:%S.") + f"{dt.microsecond//1000:03d}"


if __name__ == "__main__":
    main()
