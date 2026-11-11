#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rinex2csv.py -- convert RINEX observation + broadcast navigation files into the
CSV tables used by the SPP exercise.

This is a Python equivalent of the MATLAB function

    rinex2csv(obs_file, nav_file, out_dir)          % Lab1 of the course repository

which "reads the RINEX files with MatRTKLIB, computes satellite positions and
clock offsets from the broadcast ephemeris, evaluates the ionospheric and
tropospheric models, and writes one CSV file per quantity to out_dir:
pseudoranges_meas.csv, satellite_clock_bias.csv, satellite_positions.csv,
ionospheric_delay.csv and tropospheric_delay.csv, together with epochs.csv and
a conversion summary" (Lab tutorial, Section 7.1).

The numerical models are the RTKLIB ones, so that the CSV files are consistent
with RTKPOST/RTKLIB:

  * broadcast ephemeris -> satellite position/clock : RTKLIB eph2pos()/geph2pos()
  * ionosphere         -> Klobuchar (GPS broadcast coefficients)
  * troposphere        -> Saastamoinen (standard atmosphere, RTKLIB tropmodel())
  * signal timing      -> transmission time from pseudorange and satellite clock,
                          two-step iteration as in RTKLIB satposs()

Output files (all CSV, UTF-8, comma separated, header line, long format keyed by
epoch_id + sat_id):

  epochs.csv                 one row per epoch
  pseudoranges_meas.csv      one row per (epoch, satellite) after the masks
  satellite_positions.csv    idem
  satellite_clock_bias.csv   idem
  ionospheric_delay.csv      idem
  tropospheric_delay.csv     idem
  satellite_visibility.csv   all (epoch, satellite) before the masks + flags
  conversion_summary.txt     human readable summary
  conversion_summary.json    machine readable summary

Model for the pseudorange correction used downstream:

    P_corr = P_meas + sv_clock_correction_tgd_m - iono_slant_m - tropo_slant_m

with  sv_clock_correction_tgd_m = c*(sv_clock_bias_s + sv_relativity_s) - tgd_m

Usage
-----
    python3 rinex2csv.py --obs rinex/Move.obs --nav rinex/Move.nav \
                         --out csv/Move                       # GPS L1, 15 deg, 15 dB-Hz
    python3 rinex2csv.py --obs rinex/Move.obs --nav rinex/Move.nav \
                         --out csv/Move_multi --systems GREC  # multi-GNSS variant
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------- #
# constants (RTKLIB: src/rtklib.h, src/ephemeris.c, src/rtkcmn.c)
# --------------------------------------------------------------------------- #
CLIGHT = 299792458.0            # speed of light [m/s]
OMGE = 7.2921151467e-5          # earth angular velocity (IS-GPS) [rad/s]
RE_WGS84 = 6378137.0            # WGS84 semi-major axis [m]
HION = 350000.0                 # ionosphere height [m]
DEG = math.pi / 180.0
PI = math.pi

MU = {"G": 3.9860050e14, "J": 3.9860050e14,
      "E": 3.986004418e14, "C": 3.986004418e14, "I": 3.986004418e14}
OMGE_SYS = {"G": OMGE, "J": OMGE, "E": 7.2921151467e-5,
            "C": 7.292115e-5, "I": 7.292115e-5}

MU_GLO = 3.9860044e14
OMGE_GLO = 7.292115e-5
RE_GLO = 6378136.0
J2_GLO = 1.0826257e-3
TSTEP_GLO = 60.0

SIN_5 = -0.0871557427476582
COS_5 = 0.9961946980917456

MAXDTOE = {"G": 7200.0, "J": 7200.0, "E": 14400.0, "C": 21600.0,
           "I": 7200.0, "R": 1800.0}
MAX_ITER_KEPLER = 30
RTOL_KEPLER = 1e-13

GPS_EPOCH = datetime(1980, 1, 6, tzinfo=timezone.utc)

# leap seconds (UTC -> GPST), used only for display / GLONASS nav epochs
LEAP_TABLE = [
    (datetime(1981, 7, 1, tzinfo=timezone.utc), 1),
    (datetime(1982, 7, 1, tzinfo=timezone.utc), 2),
    (datetime(1983, 7, 1, tzinfo=timezone.utc), 3),
    (datetime(1985, 7, 1, tzinfo=timezone.utc), 4),
    (datetime(1988, 1, 1, tzinfo=timezone.utc), 5),
    (datetime(1990, 1, 1, tzinfo=timezone.utc), 6),
    (datetime(1991, 1, 1, tzinfo=timezone.utc), 7),
    (datetime(1992, 7, 1, tzinfo=timezone.utc), 8),
    (datetime(1993, 7, 1, tzinfo=timezone.utc), 9),
    (datetime(1994, 7, 1, tzinfo=timezone.utc), 10),
    (datetime(1996, 1, 1, tzinfo=timezone.utc), 11),
    (datetime(1997, 7, 1, tzinfo=timezone.utc), 12),
    (datetime(1999, 1, 1, tzinfo=timezone.utc), 13),
    (datetime(2006, 1, 1, tzinfo=timezone.utc), 14),
    (datetime(2009, 1, 1, tzinfo=timezone.utc), 15),
    (datetime(2012, 7, 1, tzinfo=timezone.utc), 16),
    (datetime(2015, 7, 1, tzinfo=timezone.utc), 17),
    (datetime(2017, 1, 1, tzinfo=timezone.utc), 18),
]

SYS_NAME = {"G": "GPS", "R": "GLONASS", "E": "Galileo", "C": "BDS",
            "J": "QZSS", "I": "IRNSS", "S": "SBAS"}

# BDT-GPST offset and week offset (BDT week 0 = 2006-01-01 = GPS week 1356)
BDT_GPST = 14.0
BDWEEK_GPST = 1356


# --------------------------------------------------------------------------- #
# time helpers: everything internal is "GPS seconds" = week*604800 + tow
# --------------------------------------------------------------------------- #
def leaps_at(dt_utc: datetime) -> int:
    """UTC -> GPST leap seconds valid at a UTC date."""
    n = 0
    for t, v in LEAP_TABLE:
        if dt_utc >= t:
            n = v
    return n


def dt_to_gps(dt: datetime) -> float:
    """calendar GPST -> GPS seconds (week*604800 + tow)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - GPS_EPOCH).total_seconds()


def gps_to_dt(t: float) -> datetime:
    """GPS seconds -> calendar GPST."""
    return GPS_EPOCH + timedelta(seconds=t)


def gps_week_tow(t: float):
    week = int(math.floor(t / 604800.0))
    return week, t - week * 604800.0


def gps_iso_utc(t: float, leaps: int = 18) -> str:
    """GPST seconds -> ISO-8601 UTC string."""
    return (GPS_EPOCH + timedelta(seconds=t - leaps)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def gps_from_week_tow(week: int, tow: float) -> float:
    return week * 604800.0 + tow


# --------------------------------------------------------------------------- #
# small linear algebra helpers
# --------------------------------------------------------------------------- #
def norm3(v):
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def sub3(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def llh2ecef(lat, lon, h):
    """geodetic (rad, rad, m) -> ECEF, WGS84."""
    a = RE_WGS84
    f = 1.0 / 298.257223563
    e2 = f * (2.0 - f)
    N = a / math.sqrt(1.0 - e2 * math.sin(lat) ** 2)
    return ((N + h) * math.cos(lat) * math.cos(lon),
            (N + h) * math.cos(lat) * math.sin(lon),
            (N * (1.0 - e2) + h) * math.sin(lat))


def pos_file_apriori(path):
    """first valid position of a RTKLIB .pos file -> ECEF [m]."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("%") or not line.strip():
                continue
            t = line.split()
            if len(t) < 5:
                continue
            try:
                lat, lon, h = float(t[2]), float(t[3]), float(t[4])
            except ValueError:
                continue
            if abs(lat) < 1e-6 and abs(lon) < 1e-6:
                continue
            return list(llh2ecef(lat * DEG, lon * DEG, h))
    return None


def ecef2pos(r):
    """ECEF -> geodetic (lat, lon [rad], height [m]), WGS84, iterative."""
    x, y, z = r
    a = RE_WGS84
    f = 1.0 / 298.257223563
    e2 = f * (2.0 - f)
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    if p < 1e-9:
        lat = math.copysign(PI / 2.0, z) if abs(z) > 1e-9 else 0.0
        return lat, lon, abs(z) - a * (1.0 - f)
    lat = math.atan2(z, p * (1.0 - e2))
    for _ in range(10):
        sinlat = math.sin(lat)
        N = a / math.sqrt(1.0 - e2 * sinlat * sinlat)
        h = p / math.cos(lat) - N
        lat_new = math.atan2(z, p * (1.0 - e2 * N / (N + h)))
        if abs(lat_new - lat) < 1e-14:
            lat = lat_new
            break
        lat = lat_new
    sinlat = math.sin(lat)
    N = a / math.sqrt(1.0 - e2 * sinlat * sinlat)
    h = p / math.cos(lat) - N
    return lat, lon, h


def azel_from_pos(rr, rs, llh=None):
    """azimuth/elevation [rad] of satellite rs seen from receiver rr."""
    if llh is None:
        llh = ecef2pos(rr)
    lat, lon, _ = llh[0], llh[1], llh[2]
    dx, dy, dz = sub3(rs, rr)
    sinlat, coslat = math.sin(lat), math.cos(lat)
    sinlon, coslon = math.sin(lon), math.cos(lon)
    e = -sinlon * dx + coslon * dy
    n = -sinlat * coslon * dx - sinlat * sinlon * dy + coslat * dz
    u = coslat * coslon * dx + coslat * sinlon * dy + sinlat * dz
    rng = math.sqrt(dx * dx + dy * dy + dz * dz)
    if rng < 1e-6:
        return 0.0, 0.0
    el = math.asin(max(-1.0, min(1.0, u / rng)))
    az = math.atan2(e, n)
    if az < 0:
        az += 2.0 * PI
    return az, el


def geodist_sagnac(rs, rr):
    """Geometric range and earth-rotation (Sagnac) correction.

    RTKLIB geodist(): rho = r + omega_e*(x_s*y_r - y_s*x_r)/c.
    Returns (plain range [m], corrected range [m], travel time [s]).
    """
    dx, dy, dz = sub3(rs, rr)
    rng = math.sqrt(dx * dx + dy * dy + dz * dz)
    corr = OMGE * (rs[0] * rr[1] - rs[1] * rr[0]) / CLIGHT
    tau = (rng + corr) / CLIGHT
    return rng, rng + corr, tau


# --------------------------------------------------------------------------- #
# RINEX observation reader (RINEX 3.x)
# --------------------------------------------------------------------------- #
class ObsFile:
    def __init__(self):
        self.version = 0.0
        self.obs_types = {}          # sys -> [codes]
        self.approx_pos = None       # [x,y,z]
        self.first_time = None
        self.time_system = "GPS"
        self.leaps = 18
        self.epochs = []             # list of (t_gps, sys, prn, {code: value})


def _parse_float(s):
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def read_obs(path: str, verbose=True) -> ObsFile:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()

    obs = ObsFile()
    cur_sys = None
    i = 0
    n = len(lines)
    # ---- header ----
    while i < n:
        line = lines[i]
        label = line[60:80].strip() if len(line) > 60 else ""
        if i == 0:
            try:
                obs.version = float(line[0:9])
            except ValueError:
                pass
        if label == "END OF HEADER":
            i += 1
            break
        if label == "SYS / # / OBS TYPES":
            if len(line) > 0 and line[0].isalpha():
                cur_sys = line[0]
                obs.obs_types[cur_sys] = []
            try:
                ncode = int(line[3:6])
            except ValueError:
                ncode = 0
            codes = line[7:60].split()
            if cur_sys is not None:
                obs.obs_types.setdefault(cur_sys, []).extend(codes[:ncode])
        elif label == "APPROX POSITION XYZ":
            obs.approx_pos = [
                float(line[0:14]), float(line[14:28]), float(line[28:42])]
        elif label == "TIME OF FIRST OBS":
            obs.time_system = line[48:51].strip() or "GPS"
        elif label == "LEAP SECONDS":
            v = _parse_float(line[0:6])
            if v:
                obs.leaps = int(v)
        i += 1

    if obs.version < 3.0:
        raise ValueError(
            f"{path}: RINEX {obs.version:.2f} is not supported by this reader; "
            "convert with '-v 3.04' (as done here) or extend read_obs().")

    # ---- epochs ----
    while i < n:
        line = lines[i]
        if not line.startswith(">"):
            i += 1
            continue
        tok = line[1:].split()
        if len(tok) < 8:
            i += 1
            continue
        y, mo, d, hh, mm = (int(tok[0]), int(tok[1]), int(tok[2]),
                            int(tok[3]), int(tok[4]))
        sec = float(tok[5])
        flag = int(tok[6])
        nsat = int(tok[7])
        century = 2000 if y < 80 else 1900
        dt = datetime(century + y if y < 100 else y, mo, d,
                      tzinfo=timezone.utc) + timedelta(
            hours=hh, minutes=mm, seconds=sec)
        t = dt_to_gps(dt)

        if flag >= 2:                 # special event: skip nsat header records
            i += 1 + nsat
            continue

        i += 1
        for _ in range(nsat):
            if i >= n:
                break
            sline = lines[i]
            if len(sline) < 3:
                i += 1
                continue
            sysc = sline[0]
            try:
                prn = int(sline[1:3])
            except ValueError:
                i += 1
                continue
            nobs = len(obs.obs_types.get(sysc, []))
            vals = {}
            if nobs:
                codes = obs.obs_types[sysc]
                got = []
                payload = sline[3:]
                k = 0
                while len(got) < nobs:
                    if k + 16 <= len(payload):
                        got.append(payload[k:k + 16])
                        k += 16
                        continue
                    # continue on the next physical line (3 leading blanks)
                    i += 1
                    if i >= n:
                        break
                    payload = lines[i][3:]
                    k = 0
                for code, chunk in zip(codes, got):
                    v = _parse_float(chunk[0:14])
                    lli = chunk[14:15]
                    ssi = chunk[15:16]
                    if v is not None:
                        vals[code] = v
                        if ssi.strip():
                            vals["_ssi_" + code] = ssi.strip()
                        if lli.strip():
                            vals["_lli_" + code] = lli.strip()
            obs.epochs.append((t, sysc, prn, vals))
            i += 1

    if verbose:
        print(f"  read {path}: RINEX {obs.version:.2f}, "
              f"{len(obs.epochs)} satellite records, "
              f"systems {''.join(sorted(obs.obs_types))}")
    return obs


# --------------------------------------------------------------------------- #
# RINEX navigation reader (RINEX 3.x, mixed)
# --------------------------------------------------------------------------- #
class NavFile:
    def __init__(self):
        self.version = 0.0
        self.iono = {}          # 'GPSA'/'GPSB' -> [4]
        self.leaps = 18
        self.eph = {}           # (sys, prn) -> list of dict, sorted by toe
        self.geph = {}


def _dfloat(s):
    s = s.strip()
    if not s:
        return None
    try:
        return float(s.replace("D", "E").replace("d", "e"))
    except ValueError:
        return None


def read_nav(path: str, verbose=True) -> NavFile:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()

    nav = NavFile()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        label = line[60:80].strip() if len(line) > 60 else ""
        if i == 0:
            try:
                nav.version = float(line[0:9])
            except ValueError:
                pass
        if label == "END OF HEADER":
            i += 1
            break
        if label == "IONOSPHERIC CORR":
            key = line[0:4].strip()
            vals = [_dfloat(line[j:j + 12]) for j in (5, 17, 29, 41)]
            nav.iono[key] = [v if v is not None else 0.0 for v in vals]
        elif label == "LEAP SECONDS":
            v = _parse_float(line[0:6])
            if v:
                nav.leaps = int(v)
        i += 1

    if nav.version < 3.0:
        raise ValueError(f"{path}: only RINEX 3.x navigation is supported "
                         f"(found {nav.version:.2f}).")

    while i < n:
        line = lines[i]
        if len(line) < 23 or not line[0].isalpha():
            i += 1
            continue
        sysc = line[0]
        try:
            prn = int(line[1:3])
        except ValueError:
            i += 1
            continue

        ncont = 3 if sysc == "R" else (7 if sysc in "GECJI" else None)
        if ncont is None:
            i += 1
            continue
        if i + ncont >= n:
            break

        head = line.split()
        # head: <sys><prn>, y, m, d, h, min, sec, v1, v2, v3   (10 tokens)
        if len(head) < 10:
            i += 1
            continue
        y, mo, d, hh, mm = (int(head[1]), int(head[2]), int(head[3]),
                            int(head[4]), int(head[5]))
        sec = float(head[6])
        century = 2000 if y < 80 else 1900
        toc_cal = datetime(century + y if y < 100 else y, mo, d,
                           tzinfo=timezone.utc) + timedelta(
            hours=hh, minutes=mm, seconds=sec)
        toc = dt_to_gps(toc_cal)

        vals = [_dfloat(t) for t in head[7:10]]
        for k in range(1, ncont + 1):
            vals.extend([_dfloat(t) for t in lines[i + k].split()])
        need = 15 if sysc == "R" else 29
        if len(vals) < need:
            vals.extend([0.0] * (need - len(vals)))
        elif len(vals) > need:
            vals = vals[:need]

        if sysc == "R":
            # TauN GammaN tk X Y Z Vx Vy Vz ax ay az health freq age
            # RINEX 3.04 GLONASS records are column-major:
            #   X Vx ax health | Y Vy ay freq | Z Vz az age
            g = {
                "prn": prn, "toc": toc, "toe": toc + leaps_at(toc_cal),
                "taun": -vals[0], "gamn": vals[1],
                "pos": [vals[3] * 1e3, vals[7] * 1e3, vals[11] * 1e3],
                "vel": [vals[4] * 1e3, vals[8] * 1e3, vals[12] * 1e3],
                "acc": [vals[5] * 1e3, vals[9] * 1e3, vals[13] * 1e3],
                "svh": int(vals[6]) & 1, "frq": int(vals[10]), "age": int(vals[14]),
            }
            nav.geph.setdefault(("R", prn), []).append(g)
        else:
            # af0 af1 af2 | IODE Crs dn M0 | Cuc e Cus sqrtA | toe Cic OMG0 Cis
            #             | i0 Crc omg OMGd | IDOT code week L2P | sva svh tgd iodc
            #             | ttr fit
            week = int(vals[21])
            toes = vals[11]
            toc_s = toc
            if sysc == "C":
                # RINEX 3 nav gives the BDT week: BDT week 0 = 2006-01-01,
                # which is GPS week 1356; BDT is ahead of... behind GPST by 14 s
                week += BDWEEK_GPST
                toc_s = toc + BDT_GPST
            toe = gps_from_week_tow(week, toes) + (BDT_GPST if sysc == "C" else 0.0)
            ttr = gps_from_week_tow(week, vals[27]) + (BDT_GPST if sysc == "C" else 0.0)
            eph = {
                "prn": prn, "week": week, "toes": toes, "toe": toe,
                "toc": toc_s, "ttr": ttr,
                "f0": vals[0], "f1": vals[1], "f2": vals[2],
                "iode": int(vals[3]), "crs": vals[4], "deln": vals[5],
                "M0": vals[6], "cuc": vals[7], "e": vals[8], "cus": vals[9],
                "A": vals[10] * vals[10], "sqrtA": vals[10],
                "cic": vals[12], "OMG0": vals[13], "cis": vals[14],
                "i0": vals[15], "crc": vals[16], "omg": vals[17],
                "OMGd": vals[18], "idot": vals[19], "code": int(vals[20]),
                "l2p": int(vals[22]), "sva": vals[23], "svh": int(vals[24]),
                "tgd": vals[25], "iodc": int(vals[26]), "fit": vals[28],
            }
            nav.eph.setdefault((sysc, prn), []).append(eph)
        i += ncont + 1

    for key in nav.eph:
        nav.eph[key].sort(key=lambda e: e["toe"])
    for key in nav.geph:
        nav.geph[key].sort(key=lambda e: e["toe"])

    if verbose:
        print(f"  read {path}: RINEX {nav.version:.2f}, "
              f"{len(nav.eph)} satellite ephemerides, {len(nav.geph)} GLONASS, "
              f"iono={sorted(nav.iono)}")
    return nav


# --------------------------------------------------------------------------- #
# ephemeris -> satellite position and clock
# --------------------------------------------------------------------------- #
def eph_pos(eph, sysc: str, t: float):
    """RTKLIB eph2pos(): position (ECEF, signal transmission frame) and clock.

    Returns (x, y, z, dts, E) with dts = clock bias incl. relativity [s].
    """
    A = eph["A"]
    if A <= 0.0:
        return None
    mu = MU.get(sysc, MU["G"])
    omge = OMGE_SYS.get(sysc, OMGE)

    tk = t - eph["toe"]
    if tk > 302400.0:
        tk -= 604800.0
    elif tk < -302400.0:
        tk += 604800.0

    n0 = math.sqrt(mu / (A * A * A))
    M = eph["M0"] + (n0 + eph["deln"]) * tk

    e = eph["e"]
    E = M
    for _ in range(MAX_ITER_KEPLER):
        Ek = E
        E = Ek - (Ek - e * math.sin(Ek) - M) / (1.0 - e * math.cos(Ek))
        if abs(E - Ek) < RTOL_KEPLER:
            break

    sinE, cosE = math.sin(E), math.cos(E)
    u = math.atan2(math.sqrt(1.0 - e * e) * sinE, cosE - e) + eph["omg"]
    r = A * (1.0 - e * cosE)
    inc = eph["i0"] + eph["idot"] * tk
    sin2u, cos2u = math.sin(2.0 * u), math.cos(2.0 * u)
    u += eph["cus"] * sin2u + eph["cuc"] * cos2u
    r += eph["crs"] * sin2u + eph["crc"] * cos2u
    inc += eph["cis"] * sin2u + eph["cic"] * cos2u

    x = r * math.cos(u)
    y = r * math.sin(u)
    cosi = math.cos(inc)

    if sysc == "C" and (eph["prn"] <= 5 or eph["prn"] >= 59):
        # BeiDou GEO: extra rotation about X by -5 deg and about Z by omge*tk
        O = eph["OMG0"] + eph["OMGd"] * tk - omge * eph["toes"]
        sinO, cosO = math.sin(O), math.cos(O)
        xg = x * cosO - y * cosi * sinO
        yg = x * sinO + y * cosi * cosO
        zg = y * math.sin(inc)
        sino, coso = math.sin(omge * tk), math.cos(omge * tk)
        rs = (xg * coso + yg * sino * COS_5 + zg * sino * SIN_5,
              -xg * sino + yg * coso * COS_5 + zg * coso * SIN_5,
              -yg * SIN_5 + zg * COS_5)
    else:
        O = eph["OMG0"] + (eph["OMGd"] - omge) * tk - omge * eph["toes"]
        sinO, cosO = math.sin(O), math.cos(O)
        rs = (x * cosO - y * cosi * sinO,
              x * sinO + y * cosi * cosO,
              y * math.sin(inc))

    tk_c = t - eph["toc"]
    if tk_c > 302400.0:
        tk_c -= 604800.0
    elif tk_c < -302400.0:
        tk_c += 604800.0
    dts = eph["f0"] + eph["f1"] * tk_c + eph["f2"] * tk_c * tk_c
    rel = -2.0 * math.sqrt(mu * A) * e * sinE / (CLIGHT * CLIGHT)
    dts += rel
    return rs[0], rs[1], rs[2], dts, E, rel


def _glo_deq(x, acc):
    r2 = x[0] ** 2 + x[1] ** 2 + x[2] ** 2
    r3 = r2 * math.sqrt(r2)
    omg2 = OMGE_GLO ** 2
    a = 1.5 * J2_GLO * MU_GLO * RE_GLO ** 2 / r2 / r3
    b = 5.0 * x[2] * x[2] / r2
    c = -MU_GLO / r3 - a * (1.0 - b)
    return [x[3], x[4], x[5],
            (c + omg2) * x[0] + 2.0 * OMGE_GLO * x[4] + acc[0],
            (c + omg2) * x[1] - 2.0 * OMGE_GLO * x[3] + acc[1],
            (c - 2.0 * a) * x[2] + acc[2]]


def _glo_step(h, x, acc):
    k1 = _glo_deq(x, acc)
    w = [x[i] + k1[i] * h / 2.0 for i in range(6)]
    k2 = _glo_deq(w, acc)
    w = [x[i] + k2[i] * h / 2.0 for i in range(6)]
    k3 = _glo_deq(w, acc)
    w = [x[i] + k3[i] * h for i in range(6)]
    k4 = _glo_deq(w, acc)
    for i in range(6):
        x[i] += (k1[i] + 2.0 * k2[i] + 2.0 * k3[i] + k4[i]) * h / 6.0


def geph_pos(geph, t: float):
    """RTKLIB geph2pos(): GLONASS position (PZ-90 ~ WGS84) and clock."""
    tdiff = t - geph["toe"]
    dts = -geph["taun"] + geph["gamn"] * tdiff
    x = [geph["pos"][0], geph["pos"][1], geph["pos"][2],
         geph["vel"][0], geph["vel"][1], geph["vel"][2]]
    tt = -TSTEP_GLO if tdiff < 0.0 else TSTEP_GLO
    while abs(tdiff) > 1e-9:
        if abs(tdiff) < TSTEP_GLO:
            tt = tdiff
        _glo_step(tt, x, geph["acc"])
        tdiff -= tt
    return x[0], x[1], x[2], dts


def select_eph(nav: NavFile, sysc: str, prn: int, t: float):
    if sysc == "R":
        lst = nav.geph.get(("R", prn))
        if not lst:
            return None
        maxdt = MAXDTOE["R"]
        best, bestdt = None, None
        for g in lst:
            dt = t - g["toe"]
            if abs(dt) <= maxdt and (bestdt is None or abs(dt) < abs(bestdt)):
                best, bestdt = g, dt
        return best
    lst = nav.eph.get((sysc, prn))
    if not lst:
        return None
    toes = [e["toe"] for e in lst]
    k = bisect.bisect_left(toes, t)
    best, bestdt = None, None
    for j in (k - 1, k, k - 2, k + 1):
        if 0 <= j < len(lst):
            dt = t - lst[j]["toe"]
            if abs(dt) <= MAXDTOE.get(sysc, 7200.0) and (
                    bestdt is None or abs(dt) < abs(bestdt)):
                best, bestdt = lst[j], dt
    return best


# --------------------------------------------------------------------------- #
# atmosphere models (RTKLIB ionmodel / tropmodel)
# --------------------------------------------------------------------------- #
def ionmodel_klobuchar(iono, lat, lon, az, el, t_gps):
    """Klobuchar slant ionospheric delay on L1 [m]; RTKLIB ionmodel()."""
    a = [iono.get("GPSA", [0, 0, 0, 0])[k] for k in range(4)]
    b = [iono.get("GPSB", [0, 0, 0, 0])[k] for k in range(4)]
    if all(v == 0.0 for v in a + b):
        return None
    el_semi = el / PI                                  # semi-circles
    az_semi = az / PI
    if el_semi <= 0.0:
        return 0.0
    psi = 0.0137 / (el_semi + 0.11) - 0.022
    phi = lat / PI + psi * math.cos(az)
    phi = max(-0.416, min(0.416, phi))
    lam = lon / PI + psi * math.sin(az) / math.cos(phi * PI)
    phi += 0.064 * math.cos((lam - 1.617) * PI)
    tt = 43200.0 * lam + (t_gps % 86400.0)
    tt -= math.floor(tt / 86400.0) * 86400.0
    f = 1.0 + 16.0 * (0.53 - el_semi) ** 3
    amp = a[0] + phi * (a[1] + phi * (a[2] + phi * a[3]))
    per = b[0] + phi * (b[1] + phi * (b[2] + phi * b[3]))
    amp = max(0.0, amp)
    per = max(72000.0, per)
    x = 2.0 * PI * (tt - 50400.0) / per
    if abs(x) < 1.57:
        delay_s = 5e-9 + amp * (1.0 + x * x * (-0.5 + x * x / 24.0))
    else:
        delay_s = 5e-9
    return CLIGHT * f * delay_s


def tropmodel(lat, hgt, el, humi=0.7):
    """Saastamoinen slant delay [m]; RTKLIB tropmodel() (dry+wet)."""
    if el <= 0.0 or hgt < -100.0 or hgt > 1e4:
        return None, None, None
    h = max(0.0, hgt)
    pres = 1013.25 * (1.0 - 2.2557e-5 * h) ** 5.2568
    temp = 15.0 - 6.5e-3 * h + 273.16
    e = 6.108 * humi * math.exp((17.15 * temp - 4684.0) / (temp - 38.45))
    z = PI / 2.0 - el
    trph = 0.0022768 * pres / (
        1.0 - 0.00266 * math.cos(2.0 * lat) - 0.00028 * h / 1e3) / math.cos(z)
    trpw = 0.002277 * (1255.0 / temp + 0.05) * e / math.cos(z)
    return trph, trpw, trph + trpw


# --------------------------------------------------------------------------- #
# observation-code selection ("L1" of each constellation) and C/N0 mapping
# --------------------------------------------------------------------------- #
PR_CODES = {
    "G": ["C1C", "C1W", "C1P", "C1L", "C1S", "C1X"],
    "R": ["C1C", "C1P"],
    "E": ["C1X", "C1C", "C1B", "C1A"],
    "C": ["C2I", "C1X", "C1P", "C1D"],
    "J": ["C1C", "C1X", "C1Z"],
    "I": ["C5A", "C1D"],
}


def pick_code(vals, sysc):
    for c in PR_CODES.get(sysc, []):
        v = vals.get(c)
        if v is not None and v > 0.0:
            return c, v
    return None, None


def cn0_of(vals, code):
    if code is None:
        return None
    s = "S" + code[1:]
    v = vals.get(s)
    if v is None:
        return None
    return v


# --------------------------------------------------------------------------- #
# conversion
# --------------------------------------------------------------------------- #
def fmt(v, nd=3):
    if v is None:
        return ""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return ""
    return f"{v:.{nd}f}"


csv.field_size_limit(1 << 20)


def convert(obs_path, nav_path, out_dir, systems="G", elev_mask=15.0,
            cn0_mask=15.0, iono_nav=None, apriori=None, verbose=True):
    obs = read_obs(obs_path, verbose)
    nav = read_nav(nav_path, verbose)
    if iono_nav:
        aux = read_nav(iono_nav, verbose=False)
        for k in ("GPSA", "GPSB", "GAL", "BDSA", "BDSB"):
            if k in aux.iono and k not in nav.iono:
                nav.iono[k] = aux.iono[k]
        print(f"  ionospheric coefficients taken from {iono_nav}: "
              f"{sorted(set(nav.iono) & {'GPSA', 'GPSB'})}")

    if obs.approx_pos is None or norm3(obs.approx_pos) < 1.0e6:
        # the header position is missing or zero (common in third-party
        # RINEX): fall back to the position given on the command line
        if apriori is None:
            raise ValueError(
                "the observation header has no usable APPROX POSITION XYZ; "
                "pass --apriori\"X,Y,Z\" or --apriori-pos <file.pos>")
        rr = tuple(apriori)
    else:
        rr = tuple(obs.approx_pos)
    llh0 = ecef2pos(rr)
    lat0, lon0, hgt0 = llh0

    sys_sel = [s for s in systems if s.upper() in "GRECJI"]
    sys_sel = [s.upper() for s in sys_sel]
    leaps = obs.leaps if obs.leaps else nav.leaps

    # --- epoch list (unique, sorted) ---
    epoch_times = sorted({e[0] for e in obs.epochs})

    # group observations by epoch
    by_epoch = {}
    for t, sysc, prn, vals in obs.epochs:
        by_epoch.setdefault(t, []).append((sysc, prn, vals))

    rows_vis = []
    rows = []
    rows_epoch = []
    counts = {"obs_records": len(obs.epochs), "masked_elev": 0,
              "masked_cn0": 0, "masked_both": 0, "no_ephemeris": 0,
              "no_pseudorange": 0, "used": 0}
    per_sys_used = {}

    for eid, t in enumerate(epoch_times):
        week, tow = gps_week_tow(t)
        iso = gps_iso_utc(t, leaps)
        n_vis = 0
        n_used = 0
        for sysc, prn, vals in by_epoch[t]:
            if sysc not in sys_sel:
                continue
            code, pr = pick_code(vals, sysc)
            if code is None:
                counts["no_pseudorange"] += 1
                continue
            cn0 = cn0_of(vals, code)

            eph = select_eph(nav, sysc, prn, t)
            if eph is None:
                counts["no_ephemeris"] += 1
                continue

            # --- transmission time / satellite position & clock -----------
            t_tx = t - pr / CLIGHT
            if sysc == "R":
                _, _, _, dt0 = geph_pos(eph, t_tx)
            else:
                p0 = eph_pos(eph, sysc, t_tx)
                if p0 is None:
                    counts["no_ephemeris"] += 1
                    continue
                dt0 = p0[3]
            t_tx -= dt0
            if sysc == "R":
                x, y, z, dts = geph_pos(eph, t_tx)
                rel = 0.0
            else:
                p = eph_pos(eph, sysc, t_tx)
                if p is None:
                    counts["no_ephemeris"] += 1
                    continue
                x, y, z, dts, _, rel = p

            rs = (x, y, z)
            az, el = azel_from_pos(rr, rs, llh0)
            rng, rng_sagnac, tau = geodist_sagnac(rs, rr)
            el_deg = el / DEG
            az_deg = az / DEG

            # --- models ----------------------------------------------------
            iono = ionmodel_klobuchar(nav.iono, lat0, lon0, az, el, t)
            trph, trpw, trop = tropmodel(lat0, hgt0, el)
            tgd_m = 0.0
            if sysc != "R":
                tgd_m = CLIGHT * (eph.get("tgd") or 0.0)

            elev_ok = el_deg >= elev_mask
            if cn0 is None:
                cn0_ok = (cn0_mask <= 0.0)
            else:
                cn0_ok = cn0 >= cn0_mask
            used = elev_ok and cn0_ok

            if not elev_ok and not cn0_ok:
                counts["masked_both"] += 1
            elif not elev_ok:
                counts["masked_elev"] += 1
            elif not cn0_ok:
                counts["masked_cn0"] += 1

            sat_id = f"{sysc}{prn:02d}"
            r = {
                "epoch_id": eid, "gps_week": week, "gps_tow_s": tow,
                "utc_time_iso": iso, "sys": sysc, "prn": prn, "sat_id": sat_id,
                "obs_code": code, "pr": pr, "cn0": cn0,
                "el": el_deg, "az": az_deg,
                "x": x, "y": y, "z": z, "range": rng, "range_sagnac": rng_sagnac,
                "tau": tau,
                "dts": dts, "rel": rel, "tgd_m": tgd_m,
                "iono": iono, "tropo_dry": trph, "tropo_wet": trpw,
                "tropo": trop,
            }
            n_vis += 1
            rows_vis.append(r)
            if used:
                n_used += 1
                rows.append(r)
                per_sys_used[sysc] = per_sys_used.get(sysc, 0) + 1
        counts["used"] += n_used
        rows_epoch.append({
            "epoch_id": eid, "gps_week": week, "gps_tow_s": tow,
            "utc_time_iso": iso, "n_sat_visible": n_vis,
            "n_sat_used": n_used,
        })

    os.makedirs(out_dir, exist_ok=True)

    # ------------------------------------------------------------------ #
    # write CSV files
    # ------------------------------------------------------------------ #
    def open_w(name, header):
        f = open(os.path.join(out_dir, name), "w", newline="", encoding="utf-8")
        w = csv.writer(f)
        w.writerow(header)
        return f, w

    # epochs.csv (the approximate receiver position is the linearisation point
    # for the SPP, taken from APPROX POSITION XYZ of the RINEX header)
    f, w = open_w("epochs.csv", ["epoch_id", "gps_week", "gps_tow_s",
                                 "utc_time_iso", "n_sat_visible", "n_sat_used",
                                 "rx_x_ecef_m", "rx_y_ecef_m", "rx_z_ecef_m"])
    for e in rows_epoch:
        w.writerow([e["epoch_id"], e["gps_week"], fmt(e["gps_tow_s"], 4),
                    e["utc_time_iso"], e["n_sat_visible"], e["n_sat_used"],
                    fmt(rr[0], 4), fmt(rr[1], 4), fmt(rr[2], 4)])
    f.close()

    key = ["epoch_id", "gps_week", "gps_tow_s", "utc_time_iso",
           "sys", "prn", "sat_id"]

    # pseudoranges_meas.csv
    f, w = open_w("pseudoranges_meas.csv", key + [
        "obs_code", "pseudorange_m", "cn0_dbhz", "elevation_deg", "azimuth_deg"])
    for r in rows:
        w.writerow([r["epoch_id"], r["gps_week"], fmt(r["gps_tow_s"], 4),
                    r["utc_time_iso"], r["sys"], r["prn"], r["sat_id"],
                    r["obs_code"], fmt(r["pr"], 3), fmt(r["cn0"], 2),
                    fmt(r["el"], 4), fmt(r["az"], 4)])
    f.close()

    # satellite_positions.csv
    f, w = open_w("satellite_positions.csv", key + [
        "x_ecef_m", "y_ecef_m", "z_ecef_m", "elevation_deg", "azimuth_deg",
        "geometric_range_m", "sagnac_correction_m", "signal_travel_time_s"])
    for r in rows:
        w.writerow([r["epoch_id"], r["gps_week"], fmt(r["gps_tow_s"], 4),
                    r["utc_time_iso"], r["sys"], r["prn"], r["sat_id"],
                    fmt(r["x"], 4), fmt(r["y"], 4), fmt(r["z"], 4),
                    fmt(r["el"], 4), fmt(r["az"], 4), fmt(r["range"], 4),
                    fmt(r["range_sagnac"] - r["range"], 4), fmt(r["tau"], 9)])
    f.close()

    # satellite_clock_bias.csv
    f, w = open_w("satellite_clock_bias.csv", key + [
        "sv_clock_bias_s", "sv_relativity_s", "sv_clock_correction_m",
        "tgd_m", "sv_clock_correction_tgd_m"])
    for r in rows:
        corr = CLIGHT * r["dts"]
        tgd = r["tgd_m"]
        w.writerow([r["epoch_id"], r["gps_week"], fmt(r["gps_tow_s"], 4),
                    r["utc_time_iso"], r["sys"], r["prn"], r["sat_id"],
                    fmt(r["dts"] - r["rel"], 12), fmt(r["rel"], 12),
                    fmt(corr, 4), fmt(tgd, 4), fmt(corr - tgd, 4)])
    f.close()

    # ionospheric_delay.csv
    f, w = open_w("ionospheric_delay.csv", key + [
        "iono_slant_m", "iono_vertical_m", "iono_mapping_factor"])
    for r in rows:
        el_semi = r["el"] / 180.0            # elevation in semi-circles
        mf = 1.0 + 16.0 * (0.53 - el_semi) ** 3 if r["el"] > 0 else None
        w.writerow([r["epoch_id"], r["gps_week"], fmt(r["gps_tow_s"], 4),
                    r["utc_time_iso"], r["sys"], r["prn"], r["sat_id"],
                    fmt(r["iono"], 4),
                    fmt(r["iono"] / mf if (mf and r["iono"] is not None) else None, 4),
                    fmt(mf, 6)])
    f.close()

    # tropospheric_delay.csv
    f, w = open_w("tropospheric_delay.csv", key + [
        "tropo_dry_m", "tropo_wet_m", "tropo_slant_m"])
    for r in rows:
        w.writerow([r["epoch_id"], r["gps_week"], fmt(r["gps_tow_s"], 4),
                    r["utc_time_iso"], r["sys"], r["prn"], r["sat_id"],
                    fmt(r["tropo_dry"], 4), fmt(r["tropo_wet"], 4),
                    fmt(r["tropo"], 4)])
    f.close()

    # satellite_visibility.csv (pre-mask diagnostics)
    f, w = open_w("satellite_visibility.csv", [
        "epoch_id", "gps_week", "gps_tow_s", "utc_time_iso",
        "sys", "prn", "sat_id", "obs_code", "pseudorange_m", "cn0_dbhz",
        "elevation_deg", "azimuth_deg",
        "elev_mask_pass", "cn0_mask_pass", "used"])
    for r in rows_vis:
        elev_ok = r["el"] >= elev_mask
        cn0_ok = (cn0_mask <= 0.0) if r["cn0"] is None else (r["cn0"] >= cn0_mask)
        w.writerow([r["epoch_id"], r["gps_week"], fmt(r["gps_tow_s"], 4),
                    r["utc_time_iso"], r["sys"], r["prn"], r["sat_id"],
                    r["obs_code"], fmt(r["pr"], 3), fmt(r["cn0"], 2),
                    fmt(r["el"], 4), fmt(r["az"], 4),
                    int(elev_ok), int(cn0_ok), int(elev_ok and cn0_ok)])
    f.close()

    # ------------------------------------------------------------------ #
    # summary
    # ------------------------------------------------------------------ #
    t0 = epoch_times[0] if epoch_times else 0.0
    t1 = epoch_times[-1] if epoch_times else 0.0
    w0, tow0 = gps_week_tow(t0)
    w1, tow1 = gps_week_tow(t1)
    n_epoch = len(epoch_times)
    dur = t1 - t0
    rate = (n_epoch - 1) / dur if dur > 0 and n_epoch > 1 else 0.0
    sats_all = sorted({(r["sys"], r["prn"]) for r in rows})
    sats_per_sys = {}
    for s, _ in sats_all:
        sats_per_sys[s] = sats_per_sys.get(s, 0) + 1

    summary = {
        "obs_file": os.path.basename(obs_path),
        "nav_file": os.path.basename(nav_path),
        "rinex_version": obs.version,
        "systems": "".join(sys_sel),
        "elevation_mask_deg": elev_mask,
        "cn0_mask_dbhz": cn0_mask,
        "epochs": n_epoch,
        "sample_interval_s": round(1.0 / rate, 3) if rate else None,
        "start_utc": gps_iso_utc(t0, leaps),
        "end_utc": gps_iso_utc(t1, leaps),
        "start_gpst": gps_to_dt(t0).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "end_gpst": gps_to_dt(t1).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "start_gps_week_tow": [w0, round(tow0, 4)],
        "end_gps_week_tow": [w1, round(tow1, 4)],
        "duration_s": round(dur, 3),
        "receiver_approx_ecef_m": [round(v, 4) for v in rr],
        "receiver_approx_latlonh": [lat0 / DEG, lon0 / DEG, hgt0],
        "leap_seconds": leaps,
        "obs_records": counts["obs_records"],
        "observation_rows_used": counts["used"],
        "satellites_used": sats_per_sys,
        "satellites_used_total": len(sats_all),
        "rejected_no_pseudorange": counts["no_pseudorange"],
        "rejected_no_ephemeris": counts["no_ephemeris"],
        "rejected_elevation_mask": counts["masked_elev"],
        "rejected_cn0_mask": counts["masked_cn0"],
        "rejected_both_masks": counts["masked_both"],
        "rows_per_epoch_mean": round(counts["used"] / n_epoch, 2) if n_epoch else 0,
        "iono_model": "Klobuchar (GPS broadcast alpha/beta)"
                     if nav.iono else "not applied (no IONOSPHERIC CORR)",
        "tropo_model": "Saastamoinen (standard atmosphere, RH=70%)",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    with open(os.path.join(out_dir, "conversion_summary.json"), "w",
              encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    txt = []
    txt.append("rinex2csv conversion summary")
    txt.append("=" * 60)
    txt.append(f"generated (UTC)      : {summary['generated_utc']}")
    txt.append(f"observation file     : {summary['obs_file']} (RINEX {obs.version:.2f})")
    txt.append(f"navigation file      : {summary['nav_file']} (RINEX {nav.version:.2f})")
    txt.append(f"systems              : {summary['systems']} "
               f"({', '.join(SYS_NAME.get(s, s) for s in sys_sel)})")
    txt.append(f"elevation mask       : {elev_mask:.1f} deg")
    txt.append(f"C/N0 mask            : {cn0_mask:.1f} dB-Hz")
    txt.append(f"epochs               : {n_epoch}")
    txt.append(f"sample interval      : {summary['sample_interval_s']} s")
    txt.append(f"start (GPST)         : {summary['start_gpst']}")
    txt.append(f"end   (GPST)         : {summary['end_gpst']}")
    txt.append(f"start (UTC)          : {summary['start_utc']}")
    txt.append(f"end   (UTC)          : {summary['end_utc']}")
    txt.append(f"GPS week / TOW       : {w0} / {tow0:.4f}  ->  {w1} / {tow1:.4f}")
    txt.append(f"duration             : {dur:.1f} s")
    txt.append(f"approx. position ECEF: {rr[0]:.4f} {rr[1]:.4f} {rr[2]:.4f} m")
    txt.append(f"approx. position LLH : {lat0/DEG:.9f} deg  {lon0/DEG:.9f} deg  "
               f"{hgt0:.3f} m")
    txt.append("")
    txt.append(f"observation records  : {counts['obs_records']}")
    txt.append(f"rows used (post-mask): {counts['used']}  "
               f"({summary['rows_per_epoch_mean']} per epoch)")
    txt.append(f"satellites used      : {summary['satellites_used_total']} "
               f"({', '.join(f'{SYS_NAME.get(k,k)}:{v}' for k, v in sorted(sats_per_sys.items()))})")
    txt.append("")
    txt.append("rejections")
    txt.append(f"  no L1 pseudorange  : {counts['no_pseudorange']}")
    txt.append(f"  no broadcast eph.  : {counts['no_ephemeris']}")
    txt.append(f"  elevation mask     : {counts['masked_elev']}")
    txt.append(f"  C/N0 mask          : {counts['masked_cn0']}")
    txt.append(f"  both masks         : {counts['masked_both']}")
    txt.append("")
    txt.append("models")
    txt.append(f"  ionosphere         : {summary['iono_model']}")
    txt.append(f"  troposphere        : {summary['tropo_model']}")
    txt.append(f"  satellite clock    : broadcast af0/af1/af2 + relativity")
    txt.append(f"  ephem. time base   : GPS/GAL GPST, BDS BDT+14 s, GLO UTC->GPST "
               f"(leap={leaps} s)")
    txt.append("")
    txt.append("pseudorange correction used downstream")
    txt.append("  P_corr = P_meas + sv_clock_correction_tgd_m - iono_slant_m "
               "- tropo_slant_m")
    txt.append("")
    txt.append("files")
    for name in ("epochs.csv", "pseudoranges_meas.csv", "satellite_positions.csv",
                 "satellite_clock_bias.csv", "ionospheric_delay.csv",
                 "tropospheric_delay.csv", "satellite_visibility.csv"):
        p = os.path.join(out_dir, name)
        txt.append(f"  {name:28s} {sum(1 for _ in open(p, encoding='utf-8')) - 1:8d} rows")
    with open(os.path.join(out_dir, "conversion_summary.txt"), "w",
              encoding="utf-8") as fh:
        fh.write("\n".join(txt) + "\n")

    if verbose:
        print("\n".join(txt))
        print()
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Convert RINEX 3.x obs+nav to the SPP CSV tables "
                    "(Python equivalent of rinex2csv.m).")
    ap.add_argument("--obs", required=True, help="RINEX observation file")
    ap.add_argument("--nav", required=True, help="RINEX navigation file")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--systems", default="G",
                    help="constellations to convert, e.g. G or GREC (default G = GPS, "
                         "as in rinex2csv.m)")
    ap.add_argument("--elev-mask", type=float, default=15.0,
                    help="elevation mask [deg] (default 15)")
    ap.add_argument("--cn0-mask", type=float, default=15.0,
                    help="C/N0 mask [dB-Hz] (default 15)")
    ap.add_argument("--apriori", default=None,
                    help='"X,Y,Z" ECEF apriori position (m), used when the '
                         'RINEX header has no usable APPROX POSITION')
    ap.add_argument("--apriori-pos", default=None,
                    help="RTKLIB .pos file whose first position is used as the "
                         "apriori (alternative to --apriori)")
    ap.add_argument("--iono-from", default=None,
                    help="optional second navigation file providing the "
                         "broadcast ionospheric coefficients when the main "
                         "nav file has none (e.g. a log from the same day)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    convert(args.obs, args.nav, args.out, systems=args.systems,
            elev_mask=args.elev_mask, cn0_mask=args.cn0_mask,
            iono_nav=args.iono_from,
            apriori=(pos_file_apriori(args.apriori_pos) if args.apriori_pos
                     else ([float(v) for v in args.apriori.split(",")]
                           if args.apriori else None)),
            verbose=not args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
