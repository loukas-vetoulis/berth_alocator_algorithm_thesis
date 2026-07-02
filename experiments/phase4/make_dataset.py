"""Generate the realistic datasets, export CSVs, and draw dataset figures.

Run from the project root:  python -X utf8 experiments/phase4/make_dataset.py
"""
from __future__ import annotations
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np

from src.realistic.dataset import SCENARIOS, build_dataset, save_dataset
from src.realistic.demand import (
    SEASON_DAYS, day_to_date, season_multiplier,
)
from src.realistic.marina import CATEGORIES, contract_season_revenue
from experiments.phase4.plotting import (
    _finish, histogram_panel, month_axis, MONTH_STARTS, MONTH_LABELS,
)
import matplotlib.pyplot as plt

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
DATA_DIR = os.path.join(ROOT, "data", "realistic")
FIG_DIR = os.path.join(ROOT, "results", "phase4")
SEED = 7


def fig_berth_mix(marina):
    codes = [c.code for c in CATEGORIES]
    counts = marina.category_counts()
    contract = [counts[c][0] - counts[c][1] for c in codes]
    transient = [counts[c][1] for c in codes]
    rates = [c.base_rate for c in CATEGORIES]

    fig, ax = plt.subplots(figsize=(9, 4.4))
    xs = np.arange(len(codes))
    ax.bar(xs, contract, label="annual contract (blocked)", color="#b0bec5",
           edgecolor="black", linewidth=0.4)
    ax.bar(xs, transient, bottom=contract, label="transient (bookable)",
           color="#1976d2", edgecolor="black", linewidth=0.4)
    ax.set_xticks(xs)
    ax.set_xticklabels([f"{c.code}\n<= {c.max_boat_length:.0f} m" for c in CATEGORIES])
    ax.set_ylabel("berths")
    ax.set_title("Berth inventory by category (460 berths)")
    ax.legend(loc="upper right")
    ax2 = ax.twinx()
    ax2.plot(xs, rates, "o-", color="#e64a19", label="base rate")
    ax2.set_ylabel("base rate (EUR / m / day)", color="#e64a19")
    ax2.tick_params(axis="y", labelcolor="#e64a19")
    _finish(fig, os.path.join(FIG_DIR, "d1_berth_mix.png"))


def fig_demand_timeline(datasets):
    fig, axes = plt.subplots(2, 1, figsize=(10, 6.4), sharex=True)
    colors = {"low": "#1976d2", "base": "#2e7d32", "high": "#e64a19"}
    for scen, ds in datasets.items():
        arrivals = np.zeros(SEASON_DAYS)
        load = np.zeros(SEASON_DAYS)
        for r in ds.requests:
            arrivals[r.arrival_day] += 1
            load[r.arrival_day:r.departure_day] += 1
        kernel = np.ones(7) / 7
        smooth = np.convolve(arrivals, kernel, mode="same")
        axes[0].plot(smooth, color=colors[scen], label=f"{scen} (x{ds.demand_mult})")
        axes[1].plot(load, color=colors[scen], label=f"{scen}")
    cap = len(datasets["base"].marina.transient_ids)
    axes[1].axhline(cap, color="black", linestyle="--", linewidth=1,
                    label=f"transient capacity ({cap})")
    axes[0].set_ylabel("booking requests / day (7-day avg)")
    axes[0].set_title("Seasonal demand: requested arrivals and berth-day load")
    axes[1].set_ylabel("requested berth-days per day")
    for ax in axes:
        month_axis(ax)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    _finish(fig, os.path.join(FIG_DIR, "d2_demand_timeline.png"))


def fig_boat_population(ds):
    reqs = ds.requests
    histogram_panel(
        [
            ([r.length for r in reqs], 30, "boat length (m)", "Boat length"),
            ([r.nights for r in reqs], range(1, 32), "nights", "Length of stay"),
            ([r.lead_days for r in reqs], 40, "days before arrival", "Booking lead time"),
        ],
        os.path.join(FIG_DIR, "d3_boat_population.png"),
        suptitle=f"Booking stream, base scenario ({len(reqs)} requests)",
    )


def fig_price_calendar():
    mults = [season_multiplier(t) for t in range(SEASON_DAYS)]
    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.step(range(SEASON_DAYS), mults, where="post", color="#1976d2")
    ax.set_ylabel("price multiplier on base rate")
    ax.set_title("Seasonal pricing (low x0.8, shoulder x1.0, high season x1.35)")
    month_axis(ax)
    ax.set_ylim(0.6, 1.5)
    ax.grid(alpha=0.3)
    _finish(fig, os.path.join(FIG_DIR, "d4_price_calendar.png"))


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(FIG_DIR, exist_ok=True)

    datasets = {}
    print("Building datasets (seed %d)..." % SEED)
    for scen in SCENARIOS:
        ds = build_dataset(scen, seed=SEED)
        save_dataset(ds, DATA_DIR)
        datasets[scen] = ds
        seg = Counter(r.segment for r in ds.requests)
        print(f"  {scen:5s} x{ds.demand_mult:<4} {len(ds.requests):5d} requests  "
              f"segments={dict(seg)}")

    m = datasets["base"].marina
    print(f"\nMarina: {m.n_berths} berths, {len(m.contract_ids)} contract, "
          f"{len(m.transient_ids)} transient")
    print(f"Fixed contract revenue over the season: "
          f"EUR {contract_season_revenue(m, SEASON_DAYS):,.0f}")

    print("\nFigures:")
    fig_berth_mix(m)
    fig_demand_timeline(datasets)
    fig_boat_population(datasets["base"])
    fig_price_calendar()
    print("Done. CSVs in data/realistic/, figures in results/phase4/")


if __name__ == "__main__":
    main()
