#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_figures.py -- figures of the AAE4203 Lab 1 report.

Figure 1  site map (OpenStreetMap tiles + own trajectory)
Figure 2  C/N0 versus time, all constellations
Figure 3  sky plot of the kinematic session
Figure 4  East-North scatter of the static solution (GPS only / multi-GNSS)

Run with the python.org interpreter that has matplotlib:
    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 \
        report/make_figures.py
"""

from __future__ import annotations

import csv
import math
import os
import ssl
import urllib.request

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle, Rectangle

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIG = os.path.join(HERE, "figs")
CACHE = os.path.join(FIG, ".tiles")
os.makedirs(CACHE, exist_ok=True)

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 8,
    "axes.titlesize": 9,
    "axes.labelsize": 8.5,
    "legend.fontsize": 7.2,
    "xtick.labelsize": 7.5,
    "ytick.labelsize": 7.5,
    "axes.linewidth": 0.7,
    "grid.linewidth": 0.4,
    "savefig.dpi": 300,
    "figure.dpi": 110,
})

SYS_COLOR = {"G": "#1f77b4", "R": "#d62728", "E": "#2ca02c", "C": "#9467bd"}
SYS_NAME = {"G": "GPS", "R": "GLONASS", "E": "Galileo", "C": "BeiDou"}


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


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
    return np.array(out)


def median_filter_track(pts, max_off=50.0):
    if len(pts) == 0:
        return pts
    mlat, mlon = np.median(pts[:, 0]), np.median(pts[:, 1])
    dn = (pts[:, 0] - mlat) * 111320.0
    de = (pts[:, 1] - mlon) * 111320.0 * math.cos(math.radians(mlat))
    return pts[np.hypot(de, dn) <= max_off]


# --------------------------------------------------------------------------- #
# Figure 1 -- site map
# --------------------------------------------------------------------------- #
def lonlat_to_px(lon, lat, z):
    n = 256.0 * 2 ** z
    x = (np.asarray(lon) + 180.0) / 360.0 * n
    rad = np.radians(np.asarray(lat))
    y = (1.0 - np.log(np.tan(rad) + 1.0 / np.cos(rad)) / math.pi) / 2.0 * n
    return x, y


def fetch_tile(z, x, y):
    path = os.path.join(CACHE, f"{z}_{x}_{y}.png")
    if not os.path.exists(path):
        url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        req = urllib.request.Request(
            url, headers={"User-Agent": "AAE4203-lab-report/1.0 (coursework; "
                                        "contact: student)"})
        ctx = (ssl.create_default_context(cafile="/etc/ssl/cert.pem")
               if os.path.exists("/etc/ssl/cert.pem") else ssl.create_default_context())
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r, \
                open(path, "wb") as fh:
            fh.write(r.read())
    return plt.imread(path)


def figure_site_map():
    from PIL import Image

    spp = median_filter_track(read_pos(os.path.join(
        ROOT, "work/check/Move_multi_csvspp.pos")))
    rec = read_pos(os.path.join(ROOT, "work/spp/Move_receiver.pos"))
    static = read_pos(os.path.join(ROOT, "work/check/static_multi_csvspp.pos"))
    slat, slon = float(np.mean(static[:, 0])), float(np.mean(static[:, 1]))

    lats = np.concatenate([spp[:, 0], rec[:, 0], [slat]])
    lons = np.concatenate([spp[:, 1], rec[:, 1], [slon]])
    pad = 0.00055                                  # ~60 m margin
    lat0, lat1 = lats.min() - pad, lats.max() + pad
    lon0, lon1 = lons.min() - pad * 1.3, lons.max() + pad * 1.3

    z = 18
    x0, y0 = lonlat_to_px(lon0, lat1, z)           # top-left
    x1, y1 = lonlat_to_px(lon1, lat0, z)           # bottom-right
    tx0, tx1 = int(x0 // 256), int(x1 // 256)
    ty0, ty1 = int(y0 // 256), int(y1 // 256)

    W, H = (tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256
    canvas = Image.new("RGB", (W, H))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            path = os.path.join(CACHE, f"{z}_{tx}_{ty}.png")
            if not os.path.exists(path):
                fetch_tile(z, tx, ty)
            canvas.paste(Image.open(path).convert("RGB"),
                         ((tx - tx0) * 256, (ty - ty0) * 256))

    cx0, cy0 = int(x0 - tx0 * 256), int(y0 - ty0 * 256)
    cx1, cy1 = int(x1 - tx0 * 256), int(y1 - ty0 * 256)
    canvas = canvas.crop((cx0, cy0, cx1, cy1))
    W, H = canvas.size

    m_per_px = 156543.03392 * math.cos(math.radians((lat0 + lat1) / 2)) / 2 ** z

    fig_w_in = 13.0 / 2.54
    fig_h_in = fig_w_in * H / W
    fig, ax = plt.subplots(figsize=(fig_w_in, fig_h_in))
    ax.imshow(np.asarray(canvas), extent=[0, W, H, 0], interpolation="bilinear")
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.set_axis_off()

    def to_px(lat, lon):
        px, py = lonlat_to_px(lon, lat, z)
        return px - (tx0 * 256 + cx0), py - (ty0 * 256 + cy0)

    sx, sy = to_px(slat, slon)
    px, py = to_px(spp[:, 0], spp[:, 1])
    ax.plot(px, py, color="#ff9f1c", lw=0.8, alpha=0.35, zorder=3,
            label="own SPP solution (scattered)")
    rx, ry = to_px(rec[:, 0], rec[:, 1])
    ax.plot(rx, ry, color="#b3001b", lw=2.2, alpha=0.95, zorder=4,
            solid_capstyle="round", label="walking track (receiver solution)")

    ax.plot([sx], [sy], marker="^", ms=12, color="#1b4965", mec="white", mew=1.2,
            zorder=6, label="static antenna")
    ax.add_patch(Circle((sx, sy), 13, fc="none", ec="#1b4965", lw=1.0, alpha=0.8,
                        zorder=5))

    for idx, lab, dx, dy in ((0, "start", -46, 26), (-1, "end", 20, -30)):
        ax.plot([rx[idx]], [ry[idx]], marker="o", ms=5.5, color="#b3001b",
                mec="white", mew=1.0, zorder=7)
        ax.annotate(lab, (rx[idx], ry[idx]), textcoords="offset points",
                    xytext=(dx, dy), fontsize=7, color="#7a0012", zorder=7,
                    bbox=dict(fc="white", ec="none", alpha=0.75, pad=1.2))
    ax.annotate("static antenna", (sx, sy), textcoords="offset points",
                xytext=(34, 30), fontsize=7, color="#1b4965",
                arrowprops=dict(arrowstyle="-", lw=0.8, color="#1b4965"),
                zorder=7, bbox=dict(fc="white", ec="none", alpha=0.75, pad=1.2))

    bar = 100.0 / m_per_px
    bx, by = 26, H - 26
    ax.add_patch(Rectangle((bx, by), bar, 5, fc="#222222", ec="white", lw=0.8,
                           zorder=8))
    ax.text(bx + bar / 2, by - 7, "100 m", ha="center", va="bottom", fontsize=6.8,
            color="#111111", zorder=8,
            bbox=dict(fc="white", ec="none", alpha=0.7, pad=1.0))
    ax.annotate("N", xy=(W - 30, 22), xytext=(W - 30, 58),
                ha="center", va="center", fontsize=8, fontweight="bold",
                arrowprops=dict(arrowstyle="-|>", lw=1.1, color="#111111"),
                zorder=8)

    ax.text(W - 5, H - 5, "Map data © OpenStreetMap contributors",
            ha="right", va="bottom", fontsize=5.2, color="#222222",
            bbox=dict(fc="white", ec="none", alpha=0.7, pad=1.2), zorder=8)
    leg = ax.legend(loc="upper left", framealpha=0.88, borderpad=0.35,
                    handlelength=1.4, fontsize=6.4)
    leg.set_zorder(9)

    out = os.path.join(FIG, "fig1_site_map.png")
    fig.savefig(out, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    print("wrote", out, f"({W}x{H} px map, {m_per_px:.2f} m/px)")


# --------------------------------------------------------------------------- #
# Figure 2 -- C/N0 versus time
# --------------------------------------------------------------------------- #
def figure_cn0():
    rows = [r for r in read_csv(os.path.join(
        ROOT, "csv/Move_multi/satellite_visibility.csv")) if r["cn0_dbhz"]]
    t = np.array([float(r["gps_tow_s"]) for r in rows])
    t = t - t.min()
    cn0 = np.array([float(r["cn0_dbhz"]) for r in rows])
    sysc = np.array([r["sys"] for r in rows])

    bins = np.arange(0, t.max() + 10, 10.0)
    idx = np.digitize(t, bins) - 1
    centres, p10, p50, p90 = [], [], [], []
    sys_med = {s: [] for s in SYS_COLOR}
    for k in range(len(bins) - 1):
        m = idx == k
        if m.sum() < 5:
            continue
        centres.append(0.5 * (bins[k] + bins[k + 1]))
        p10.append(np.percentile(cn0[m], 10))
        p50.append(np.percentile(cn0[m], 50))
        p90.append(np.percentile(cn0[m], 90))
        for s in sys_med:
            mm = m & (sysc == s)
            sys_med[s].append(np.median(cn0[mm]) if mm.sum() >= 3 else np.nan)
    centres = np.array(centres)

    fig, ax = plt.subplots(figsize=(15.0 / 2.54, 5.4 / 2.54))
    ax.fill_between(centres, p10, p90, color="#9aa5b1", alpha=0.35, lw=0,
                    label="10–90 % of all tracked signals")
    ax.plot(centres, p50, color="#222222", lw=1.1, label="median, all signals")
    for s in ("G", "R", "E", "C"):
        ax.plot(centres, sys_med[s], color=SYS_COLOR[s], lw=1.0,
                label=f"median, {SYS_NAME[s]}")

    for y in (30, 40):
        ax.axhline(y, color="#c00000", lw=0.8, ls=(0, (4, 2)), alpha=0.85)
        ax.text(centres[-1] * 0.995, y + 0.6, f"{y} dB-Hz", ha="right",
                va="bottom", fontsize=6.2, color="#a00000",
                bbox=dict(fc="white", ec="none", alpha=0.8, pad=1.0))

    ax.set_xlim(0, centres[-1])
    ax.set_ylim(18, 55)
    ax.set_xlabel("Time from start of the kinematic session [s]")
    ax.set_ylabel("C/N$_0$ [dB-Hz]")
    ax.grid(True, axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.42), ncol=3,
              frameon=False, fontsize=6.4, handlelength=1.8, columnspacing=1.4)
    fig.tight_layout(pad=0.3)
    out = os.path.join(FIG, "fig2_cn0.png")
    fig.savefig(out, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    print("wrote", out)


# --------------------------------------------------------------------------- #
# Figure 3 -- sky plot
# --------------------------------------------------------------------------- #
def figure_sky():
    rows = read_csv(os.path.join(ROOT, "csv/Move_multi/satellite_visibility.csv"))
    az = np.array([float(r["azimuth_deg"]) for r in rows])
    el = np.array([float(r["elevation_deg"]) for r in rows])
    cn0 = np.array([float(r["cn0_dbhz"]) for r in rows])

    fig = plt.figure(figsize=(8.4 / 2.54, 8.4 / 2.54))
    ax = fig.add_subplot(111, projection="polar")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_rlim(0, 90)
    ax.set_rticks([0, 30, 60, 90])
    ax.set_yticklabels(["90°", "60°", "30°", "0°"], fontsize=5.6, color="#555555")
    ax.set_xticks(np.radians([0, 45, 90, 135, 180, 225, 270, 315]))
    ax.set_xticklabels(["N", "NE", "E", "SE", "S", "SW", "W", "NW"], fontsize=6.5)
    ax.tick_params(pad=1.0)
    ax.grid(color="#cccccc", lw=0.5)
    ax.set_facecolor("#fbfbfb")

    ax.plot(np.linspace(0, 2 * np.pi, 361), np.full(361, 75.0),
            color="#c00000", lw=0.8, ls=(0, (4, 2)), zorder=3)
    ax.text(np.radians(232), 78.0, "15° mask", fontsize=5.8, color="#a00000",
            ha="center", va="bottom", rotation=-35)

    sc = ax.scatter(np.radians(az), 90.0 - el, c=cn0, cmap="viridis",
                    s=3.2, alpha=0.65, vmin=15, vmax=50, linewidths=0)
    cb = fig.colorbar(sc, ax=ax, pad=0.09, fraction=0.046)
    cb.set_label("C/N$_0$ [dB-Hz]", fontsize=6.5)
    cb.ax.tick_params(labelsize=5.8, length=2)
    cb.outline.set_linewidth(0.5)

    out = os.path.join(FIG, "fig3_sky.png")
    fig.savefig(out, bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)
    print("wrote", out)


# --------------------------------------------------------------------------- #
# Figure 4 -- East-North scatter of the static solution
# --------------------------------------------------------------------------- #
def enu_about_mean(pts):
    mlat, mlon = np.mean(pts[:, 0]), np.mean(pts[:, 1])
    de = (pts[:, 1] - mlon) * 111320.0 * math.cos(math.radians(mlat))
    dn = (pts[:, 0] - mlat) * 111320.0
    return de, dn


def figure_static_scatter():
    cases = [("static_csvspp.pos", "(a) GPS only", "#1f77b4"),
             ("static_multi_csvspp.pos", "(b) GPS + GLO + GAL + BDS", "#2ca02c")]

    fig, axes = plt.subplots(1, 2, figsize=(15.0 / 2.54, 7.2 / 2.54),
                             sharey=False)
    for ax, (fname, title, color) in zip(axes, cases):
        pts = read_pos(os.path.join(ROOT, "work/check", fname))
        de, dn = enu_about_mean(pts)
        r = np.hypot(de, dn)
        r95 = np.sort(r)[int(0.95 * len(r)) - 1]

        ax.scatter(de, dn, s=5, color=color, alpha=0.55, linewidths=0)
        ax.add_patch(Circle((0, 0), r95, fc="none", ec="#d62728", lw=0.9,
                            ls="--", zorder=3))
        ax.plot([0], [0], marker="+", ms=9, color="#d62728", mew=1.3, zorder=4,
                label=f"mean / 95 % radius ({r95:.2f} m)")

        lim = max(6.0, 1.15 * np.percentile(np.abs(np.r_[de, dn]), 99))
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-lim, lim)
        ax.set_aspect("equal", adjustable="box")
        ax.axhline(0, color="#999999", lw=0.6)
        ax.axvline(0, color="#999999", lw=0.6)
        ax.grid(True, alpha=0.3)
        ax.set_axisbelow(True)
        ax.set_title(title, fontsize=8.5)
        ax.set_xlabel("East [m]")
        if ax is axes[0]:
            ax.set_ylabel("North [m]")
        ax.text(0.03, 0.97,
                f"n = {len(de)}\nσE = {np.std(de):.2f} m\nσN = {np.std(dn):.2f} m\n"
                f"95 % R = {r95:.2f} m",
                transform=ax.transAxes, va="top", ha="left", fontsize=6.4,
                bbox=dict(fc="white", ec="#cccccc", lw=0.5, alpha=0.9, pad=2.5))
        ax.legend(loc="lower right", fontsize=6.2, framealpha=0.9,
                  handlelength=1.2)

    fig.tight_layout(pad=0.5, w_pad=1.5)
    out = os.path.join(FIG, "fig4_static_scatter.png")
    fig.savefig(out, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    print("wrote", out)


if __name__ == "__main__":
    figure_site_map()
    figure_cn0()
    figure_sky()
    figure_static_scatter()
