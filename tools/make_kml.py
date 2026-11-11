#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_kml.py -- build one Google Earth KML with several solution tracks.

This is the "one file, several colours" companion of RTKPLOT's
Tools -> Convert to KML (`pos2kml`, which writes one KML per .pos file):
it reads RTKLIB .pos files (latitude/longitude/height) and writes a single KML
document with one folder per track, so that e.g. the RTKLIB solution (yellow)
and the receiver's own solution (green) can be compared in Google Earth,
as in Lab tutorial Fig. 27.

Usage
    python3 tools/make_kml.py --out kml/Move_compare.kml \
        --track work/spp/Move_spp.pos      "RTKLIB SPP (GPS)"   yellow \
        --track work/spp/Move_rtk_multi.pos "RTKLIB SPP (G/R/E/C)" orange \
        --track work/spp/Move_receiver.pos  "Receiver NAV-HPPOSECEF" green
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from xml.sax.saxutils import escape

# KML colours are aabbggrr
COLORS = {
    "yellow": "ff00ffff",
    "green": "ff008800",
    "red": "ff0000ff",
    "orange": "ff00a5ff",
    "blue": "ffff0000",
    "white": "ffffffff",
    "magenta": "ffff00ff",
    "cyan": "ffffff00",
}


def read_pos(path):
    """RTKLIB .pos, llh solution -> [(lat, lon, h)]"""
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("%") or not line.strip():
                continue
            tok = line.split()
            if len(tok) < 5:
                continue
            try:
                lat, lon, h = float(tok[2]), float(tok[3]), float(tok[4])
            except ValueError:
                continue
            if abs(lat) > 90 or abs(lon) > 180:
                continue
            out.append((lat, lon, h))
    return out


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2])


def build(tracks, name="GNSS solutions", altitude=False, max_offset=0.0):
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        "<Document>",
        f"  <name>{escape(name)}</name>",
        "  <open>1</open>",
    ]
    for i, (path, label, color) in enumerate(tracks, 1):
        pts = read_pos(path)
        if not pts:
            print(f"  warning: no position in {path}", file=sys.stderr)
            continue
        n_all = len(pts)
        if max_offset > 0.0:
            mlat, mlon = median([p[0] for p in pts]), median([p[1] for p in pts])
            kx = 111320.0
            ky = 111320.0 * math.cos(math.radians(mlat))
            pts = [p for p in pts
                   if math.hypot((p[0] - mlat) * kx, (p[1] - mlon) * ky)
                   <= max_offset]
            print(f"  filter >{max_offset:.0f} m from median: "
                  f"{n_all - len(pts)} of {n_all} epochs removed")
        col = COLORS.get(color, color)
        parts.append(f"  <Style id=\"line{i}\">")
        parts.append("    <LineStyle>")
        parts.append(f"      <color>{col}</color>")
        parts.append("      <width>3</width>")
        parts.append("    </LineStyle>")
        parts.append("    <IconStyle>")
        parts.append("      <scale>0.5</scale>")
        parts.append(f"      <color>{col}</color>")
        parts.append("    </IconStyle>")
        parts.append("  </Style>")
        parts.append("  <Folder>")
        parts.append(f"    <name>{escape(label)}</name>")
        parts.append("    <open>1</open>")
        hz = sum(p[2] for p in pts) / len(pts)
        parts.append("    <Placemark>")
        parts.append(f"      <name>{escape(label)}: track</name>")
        extra = (f", outliers > {max_offset:.0f} m from the median removed "
                 f"({n_all - len(pts)} epochs)") if max_offset > 0 else ""
        parts.append(f"      <description>{len(pts)} epochs, mean ellipsoidal "
                     f"height {hz:.2f} m{extra}</description>")
        parts.append("      <styleUrl>#line%d</styleUrl>" % i)
        parts.append("      <LineString>")
        parts.append("        <tessellate>1</tessellate>")
        parts.append("        <altitudeMode>%s</altitudeMode>"
                     % ("absolute" if altitude else "clampToGround"))
        coords = []
        for lat, lon, h in pts:
            coords.append(f"{lon:.9f},{lat:.9f},{h:.3f}" if altitude
                          else f"{lon:.9f},{lat:.9f},0.000")
        parts.append("        <coordinates>")
        # keep the file readable: 20 points per line
        for k in range(0, len(coords), 20):
            parts.append("          " + " ".join(coords[k:k + 20]))
        parts.append("        </coordinates>")
        parts.append("      </LineString>")
        parts.append("    </Placemark>")
        for tag, p in (("start", pts[0]), ("end", pts[-1])):
            parts.append("    <Placemark>")
            parts.append(f"      <name>{escape(label)}: {tag}</name>")
            parts.append("      <styleUrl>#line%d</styleUrl>" % i)
            parts.append("      <Point>")
            parts.append("        <altitudeMode>%s</altitudeMode>"
                         % ("absolute" if altitude else "clampToGround"))
            parts.append(f"        <coordinates>{p[1]:.9f},{p[0]:.9f},"
                         f"{p[2] if altitude else 0.0:.3f}</coordinates>")
            parts.append("      </Point>")
            parts.append("    </Placemark>")
        parts.append("  </Folder>")
        print(f"  {label}: {len(pts)} points, mean height {hz:.2f} m "
              f"({os.path.basename(path)})")
    parts += ["</Document>", "</kml>", ""]
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="GNSS solutions")
    ap.add_argument("--track", nargs=3, action="append", required=True,
                    metavar=("POSFILE", "LABEL", "COLOR"),
                    help="position file (RTKLIB .pos llh), label and colour")
    ap.add_argument("--altitude", action="store_true",
                    help="use absolute altitude instead of clampToGround")
    ap.add_argument("--max-offset", type=float, default=0.0,
                    help="drop epochs farther than this (m) from the track "
                         "median position; 0 keeps everything")
    args = ap.parse_args()

    tracks = [(a, b, c) for a, b, c in args.track]
    print(f"writing {args.out}")
    kml = build(tracks, args.name, args.altitude, args.max_offset)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(kml)
    print(f"  {os.path.getsize(args.out)} bytes")


if __name__ == "__main__":
    main()
