#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plot_ablation.py -- figure for the SPP ablation (v1 GPS-only -> v4 FDE).

    (a) East-North scatter of the static solution, v3 and v4
    (b) 95 % horizontal radius per version, both datasets
    (c) vertical scatter (sigma U) per version, both datasets

Run with the python.org interpreter that has matplotlib.
"""

from __future__ import annotations

import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIR = os.path.join(ROOT, "work/spp_ablation")
OUT = os.path.join(DIR, "ablation.png")

plt.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Helvetica", "Arial"],
    "font.size": 8, "axes.titlesize": 9, "axes.labelsize": 8.5,
    "legend.fontsize": 7, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
    "axes.linewidth": 0.7, "savefig.dpi": 300, "figure.dpi": 110,
})

LABELS = {"v1": "v1", "v2": "v2", "v3": "v3", "v4": "v4"}
COL = {"Move": "#1f77b4", "static": "#2ca02c"}


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


def enu(pts):
    mlat, mlon = np.mean(pts[:, 0]), np.mean(pts[:, 1])
    de = (pts[:, 1] - mlon) * 111320.0 * math.cos(math.radians(mlat))
    dn = (pts[:, 0] - mlat) * 111320.0
    return de, dn


def stats(pts):
    de, dn = enu(pts)
    r = np.hypot(de, dn)
    return de, dn, np.sort(r)[int(0.95 * len(r)) - 1], np.std(pts[:, 2])


def main():
    fig = plt.figure(figsize=(15.2 / 2.54, 4.9 / 2.54))
    gs = fig.add_gridspec(1, 3, width_ratios=[1.05, 1.0, 1.0], wspace=0.42)

    # ---------------- (a) static EN scatter, v3 vs v4 --------------------
    ax = fig.add_subplot(gs[0, 0])
    for v, col, lab in (("v3", "#9aa5b1", "v3 (no FDE)"), ("v4", "#1f77b4", "v4 (FDE)")):
        pts = read_pos(os.path.join(DIR, f"static_{v}.pos"))
        de, dn, r95, _ = stats(pts)
        ax.scatter(de, dn, s=5, color=col, alpha=0.55, linewidths=0, label=lab)
        ax.add_patch(Circle((0, 0), r95, fc="none", ec=col, lw=1.0, ls="--"))
    ax.plot([0], [0], marker="+", ms=9, color="#c00000", mew=1.3)
    lim = 9.5
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal", adjustable="box")
    ax.axhline(0, color="#bbbbbb", lw=0.6)
    ax.axvline(0, color="#bbbbbb", lw=0.6)
    ax.grid(alpha=0.3)
    ax.set_axisbelow(True)
    ax.set_xlabel("East [m]")
    ax.set_ylabel("North [m]")
    ax.set_title("(a) static, scatter about the mean", fontsize=8.5)
    ax.legend(loc="upper right", framealpha=0.9, handletextpad=0.4,
              markerscale=2.2, borderpad=0.4)

    # ---------------- (b)/(c) bars ---------------------------------------
    versions = ["v1", "v2", "v3", "v4"]
    for k, (axpos, metric, title, ylab) in enumerate((
            (gs[0, 1], 2, "(b) 95 % horizontal radius", "95 % radius [m]"),
            (gs[0, 2], 3, "(c) vertical scatter", r"$\sigma_U$ [m]"))):
        ax = fig.add_subplot(axpos)
        x = np.arange(len(versions))
        w = 0.38
        for j, ds in enumerate(("Move", "static")):
            vals = []
            for v in versions:
                p = os.path.join(DIR, f"{ds}_{v}.pos")
                vals.append(stats(read_pos(p))[metric] if os.path.exists(p) else 0.0)
            ax.bar(x + (j - 0.5) * w, vals, w, color=COL[ds], alpha=0.85,
                   label="kinematic" if ds == "Move" else "static")
            for xi, v in zip(x + (j - 0.5) * w, vals):
                ax.text(xi, v + 0.6, f"{v:.1f}", ha="center", va="bottom",
                        fontsize=5.8, color="#333333")
        ax.set_xticks(x)
        ax.set_xticklabels([LABELS[v] for v in versions], fontsize=7.5)
        ax.set_ylabel(ylab)
        ax.set_title(title, fontsize=8.5)
        ax.grid(True, axis="y", alpha=0.3)
        ax.set_axisbelow(True)
        ax.set_ylim(0, ax.get_ylim()[1] * 1.28)
        if k == 0:
            ax.legend(loc="upper right", frameon=False, fontsize=6.8)

    fig.savefig(OUT, bbox_inches="tight", pad_inches=0.03)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
