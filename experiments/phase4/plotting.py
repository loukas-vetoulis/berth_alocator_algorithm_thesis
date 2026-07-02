"""Shared matplotlib helpers for the phase-4 figures."""
from __future__ import annotations
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from src.realistic.demand import SEASON_DAYS, day_to_date

DPI = 150

MONTH_STARTS = [t for t in range(SEASON_DAYS) if day_to_date(t).day == 1]
MONTH_LABELS = [day_to_date(t).strftime("%b") for t in MONTH_STARTS]

POLICY_COLORS = {
    "online[first_fit]": "#9e9e9e",
    "online[best_fit]": "#1976d2",
    "online[revenue_max]": "#e64a19",
    "batch[plain]": "#8e24aa",
    "batch[tuned]": "#2e7d32",
    "oracle": "#212121",
}


def _finish(fig, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    print(f"  saved {os.path.relpath(path)}")


def month_axis(ax) -> None:
    ax.set_xticks(MONTH_STARTS)
    ax.set_xticklabels(MONTH_LABELS)
    ax.set_xlim(0, SEASON_DAYS - 1)


def bar_with_error(labels, means, stds, ylabel, title, path,
                   colors=None, fmt="{:.0f}") -> None:
    fig, ax = plt.subplots(figsize=(9, 4.6))
    xs = np.arange(len(labels))
    bars = ax.bar(xs, means, yerr=stds, capsize=4,
                  color=colors or "#1976d2", edgecolor="black", linewidth=0.4)
    for b, v in zip(bars, means):
        ax.annotate(fmt.format(v), (b.get_x() + b.get_width() / 2, b.get_height()),
                    ha="center", va="bottom", fontsize=8)
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.3)
    _finish(fig, path)


def grouped_bars(group_labels, series, ylabel, title, path, fmt=None) -> None:
    """series = {name: list of values, one per group}."""
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    n = len(series)
    width = 0.8 / n
    xs = np.arange(len(group_labels))
    for k, (name, vals) in enumerate(series.items()):
        ax.bar(xs + (k - (n - 1) / 2) * width, vals, width,
               label=name, color=POLICY_COLORS.get(name),
               edgecolor="black", linewidth=0.3)
    ax.set_xticks(xs)
    ax.set_xticklabels(group_labels)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    _finish(fig, path)


def season_lines(series, ylabel, title, path, capacity_line=None) -> None:
    """series = {name: array over season days}."""
    fig, ax = plt.subplots(figsize=(10, 4.2))
    for name, ys in series.items():
        ax.plot(np.arange(len(ys)), ys, label=name, linewidth=1.4,
                color=POLICY_COLORS.get(name))
    if capacity_line is not None:
        ax.axhline(capacity_line, color="black", linestyle="--", linewidth=1,
                   label="capacity")
    month_axis(ax)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    _finish(fig, path)


def sweep_lines(xvals, per_scenario, xlabel, ylabel, title, path,
                mark_best=True, ref_lines=None, ref_label="online[best_fit]") -> None:
    """per_scenario = {scenario: (means, stds)} over xvals.

    ``ref_lines`` optionally draws a dashed per-scenario reference level
    (e.g. the online best-fit revenue) in the scenario's color.
    """
    fig, ax = plt.subplots(figsize=(8, 4.4))
    colors = {"low": "#1976d2", "base": "#2e7d32", "high": "#e64a19"}
    for scen, (means, stds) in per_scenario.items():
        means, stds = np.asarray(means), np.asarray(stds)
        ax.errorbar(xvals, means, yerr=stds, marker="o", capsize=3,
                    label=f"{scen} demand", color=colors.get(scen))
        if ref_lines and scen in ref_lines:
            ax.axhline(ref_lines[scen], color=colors.get(scen), linestyle="--",
                       linewidth=1, alpha=0.6)
        if mark_best:
            k = int(np.argmax(means))
            ax.scatter([xvals[k]], [means[k]], s=140, facecolors="none",
                       edgecolors=colors.get(scen), linewidths=2, zorder=5)
    if ref_lines:
        ax.plot([], [], color="grey", linestyle="--", label=f"{ref_label} (ref)")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    _finish(fig, path)


def occupancy_heatmap(occ_snapshot, title, path, transient_ids=None) -> None:
    """Berth-by-day occupancy image: white free, blue booked, grey contract."""
    occ = occ_snapshot if transient_ids is None else occ_snapshot[transient_ids, :]
    img = np.zeros((*occ.shape, 3))
    img[occ == 0] = (1.0, 1.0, 1.0)
    img[occ == 1] = (0.10, 0.42, 0.75)
    img[occ == 2] = (0.82, 0.82, 0.82)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.imshow(img, aspect="auto", interpolation="nearest")
    month_axis(ax)
    ax.set_ylabel("berth (transient pool)" if transient_ids is not None else "berth")
    ax.set_title(title)
    _finish(fig, path)


def gantt_zoom(occ_snapshot, booked_by, berth_ids, day_range, title, path,
               berth_labels=None) -> None:
    """Booking-level Gantt of selected berths over a date window."""
    d0, d1 = day_range
    fig, ax = plt.subplots(figsize=(10, 0.42 * len(berth_ids) + 1.6))
    cmap = plt.get_cmap("tab20")
    for row, i in enumerate(berth_ids):
        t = d0
        while t < d1:
            state = occ_snapshot[i, t]
            if state == 0:
                t += 1
                continue
            rid = booked_by[i, t]
            t2 = t
            while t2 < d1 and occ_snapshot[i, t2] == state and booked_by[i, t2] == rid:
                t2 += 1
            color = (0.85, 0.85, 0.85) if state == 2 else cmap(int(rid) % 20)
            ax.barh(row, t2 - t, left=t, height=0.72, color=color,
                    edgecolor="black", linewidth=0.4)
            if state == 1 and t2 - t >= 2:
                ax.text((t + t2) / 2, row, str(int(rid)), ha="center",
                        va="center", fontsize=6.5)
            t = t2
    ax.set_yticks(range(len(berth_ids)))
    ax.set_yticklabels(berth_labels or [f"berth {i}" for i in berth_ids], fontsize=8)
    ax.invert_yaxis()
    ticks = [t for t in range(d0, d1) if (t - d0) % 7 == 0]
    ax.set_xticks(ticks)
    ax.set_xticklabels([day_to_date(t).strftime("%d %b") for t in ticks], fontsize=8)
    ax.set_xlim(d0, d1)
    ax.set_title(title)
    ax.grid(axis="x", alpha=0.3)
    _finish(fig, path)


def histogram_panel(panels, path, suptitle=None) -> None:
    """panels = list of (data, bins, xlabel, title)."""
    fig, axes = plt.subplots(1, len(panels), figsize=(4.2 * len(panels), 3.6))
    if len(panels) == 1:
        axes = [axes]
    for ax, (data, bins, xlabel, title) in zip(axes, panels):
        ax.hist(data, bins=bins, color="#1976d2", edgecolor="black", linewidth=0.4)
        ax.set_xlabel(xlabel)
        ax.set_title(title, fontsize=10)
        ax.grid(axis="y", alpha=0.3)
    if suptitle:
        fig.suptitle(suptitle)
    _finish(fig, path)
