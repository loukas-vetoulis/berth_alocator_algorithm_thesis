"""Weight and parameter tuning for the batch MILP policy.

Staged sweep over the three objective weights and the batching interval,
for each demand scenario (low / base / high), across seeds:

  Stage 1  space weight (tight packing)      frag = opp = 0
  Stage 2  opp weight (opportunity cost)     at the stage-1 winner
  Stage 3  frag weight (fragmentation)       at the stage-1/2 winner
  Stage 4  batching interval 1 / 3 / 7 days  at the winning weights

The winner per scenario (by mean season revenue across seeds) is written
to results/phase4/data/tuned_weights.json and used by the final policy
comparison. Every run's summary row goes to tuning_runs.csv.

Run from the project root:  python -X utf8 experiments/phase4/tune_weights.py
"""
from __future__ import annotations
import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np

from src.realistic.dataset import SCENARIOS, build_dataset
from src.simulation.engine import simulate_season
from src.simulation.policies import BatchMILP, OnlineGreedy, Weights
from experiments.phase4.plotting import sweep_lines

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
FIG_DIR = os.path.join(ROOT, "results", "phase4")
DATA_DIR = os.path.join(FIG_DIR, "data")

SEEDS = [7, 11]
SPACE_GRID = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0]
OPP_GRID = [0.0, 0.05, 0.1, 0.2, 0.3, 0.5]
FRAG_GRID = [0.0, 0.25, 0.5, 1.0]
BATCH_GRID = [1, 3, 7]

_datasets: dict[tuple[str, int], object] = {}
_cache: dict[tuple, dict] = {}
_rows: list[dict] = []


def dataset(scen: str, seed: int):
    key = (scen, seed)
    if key not in _datasets:
        _datasets[key] = build_dataset(scen, seed=seed)
    return _datasets[key]


def run_batch(scen: str, seed: int, w: Weights, batch_days: int = 1) -> dict:
    key = (scen, seed, w.space, w.frag, w.opp, batch_days)
    if key in _cache:
        return _cache[key]
    ds = dataset(scen, seed)
    out = simulate_season(ds.marina, ds.requests, BatchMILP(ds.marina, w, batch_days))
    row = {"scenario": scen, "seed": seed, "space": w.space, "frag": w.frag,
           "opp": w.opp, "batch_days": batch_days, **out.row()}
    _cache[key] = row
    _rows.append(row)
    print(f"  {scen:5s} seed={seed} space={w.space:<5g} frag={w.frag:<5g} "
          f"opp={w.opp:<5g} b={batch_days}  rev={row['revenue']:>9.0f} "
          f"acc={row['acceptance_rate']:.3f} occ={row['occupancy']:.3f}", flush=True)
    return row


def run_online_ref(scen: str, seed: int) -> dict:
    key = (scen, seed, "online_bf")
    if key in _cache:
        return _cache[key]
    ds = dataset(scen, seed)
    out = simulate_season(ds.marina, ds.requests, OnlineGreedy(ds.marina, "best_fit"))
    row = {"scenario": scen, "seed": seed, "space": None, "frag": None,
           "opp": None, "batch_days": None, **out.row()}
    _cache[key] = row
    _rows.append(row)
    return row


def mean_rev(rows: list[dict]) -> float:
    return float(np.mean([r["revenue"] for r in rows]))


def sweep(name: str, grid, make_weights, batch_days_of=lambda v: 1,
          fig_path: str | None = None, xlabel: str = "", refs=None):
    """Run grid x scenarios x seeds; return {scenario: best grid value}."""
    print(f"\n=== {name} ===")
    best: dict[str, float] = {}
    per_scen = {}
    for scen in SCENARIOS:
        means, stds = [], []
        for v in grid:
            rows = [run_batch(scen, s, make_weights(scen, v), batch_days_of(v))
                    for s in SEEDS]
            revs = [r["revenue"] for r in rows]
            means.append(float(np.mean(revs)))
            stds.append(float(np.std(revs)))
        k = int(np.argmax(means))
        best[scen] = grid[k]
        per_scen[scen] = (means, stds)
        print(f"  -> {scen}: best {name} = {grid[k]} "
              f"(mean revenue {means[k]:,.0f})")
    if fig_path:
        sweep_lines(grid, per_scen, xlabel, "season revenue (EUR)",
                    f"{name} sweep", fig_path, ref_lines=refs)
    return best


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    print("Reference: online[best_fit] per scenario")
    refs = {}
    for scen in SCENARIOS:
        rows = [run_online_ref(scen, s) for s in SEEDS]
        refs[scen] = mean_rev(rows)
        print(f"  {scen:5s} online[best_fit] mean revenue = {refs[scen]:,.0f}")

    best_space = sweep(
        "space weight", SPACE_GRID,
        lambda scen, v: Weights(space=v),
        fig_path=os.path.join(FIG_DIR, "t1_space_sweep.png"),
        xlabel="space weight (waste penalty)", refs=refs)

    best_opp = sweep(
        "opportunity weight", OPP_GRID,
        lambda scen, v: Weights(space=best_space[scen], opp=v),
        fig_path=os.path.join(FIG_DIR, "t2_opp_sweep.png"),
        xlabel="opportunity-cost weight", refs=refs)

    best_frag = sweep(
        "fragmentation weight", FRAG_GRID,
        lambda scen, v: Weights(space=best_space[scen], opp=best_opp[scen], frag=v),
        fig_path=os.path.join(FIG_DIR, "t3_frag_sweep.png"),
        xlabel="fragmentation weight", refs=refs)

    print("\n=== batching interval ===")
    best_batch = {}
    per_scen = {}
    for scen in SCENARIOS:
        w = Weights(space=best_space[scen], frag=best_frag[scen], opp=best_opp[scen])
        means, stds = [], []
        for b in BATCH_GRID:
            rows = [run_batch(scen, s, w, b) for s in SEEDS]
            revs = [r["revenue"] for r in rows]
            means.append(float(np.mean(revs)))
            stds.append(float(np.std(revs)))
        k = int(np.argmax(means))
        best_batch[scen] = BATCH_GRID[k]
        per_scen[scen] = (means, stds)
        print(f"  -> {scen}: best batch interval = {BATCH_GRID[k]} days")
    sweep_lines(BATCH_GRID, per_scen, "batching interval (days)",
                "season revenue (EUR)", "Batching interval sweep",
                os.path.join(FIG_DIR, "t4_batch_interval.png"), ref_lines=refs)

    tuned = {
        scen: {
            "space": best_space[scen],
            "frag": best_frag[scen],
            "opp": best_opp[scen],
            "batch_days": best_batch[scen],
            "mean_revenue": mean_rev([
                run_batch(scen, s, Weights(space=best_space[scen],
                                           frag=best_frag[scen],
                                           opp=best_opp[scen]),
                          best_batch[scen]) for s in SEEDS]),
            "online_best_fit_revenue": refs[scen],
        }
        for scen in SCENARIOS
    }
    with open(os.path.join(DATA_DIR, "tuned_weights.json"), "w", encoding="utf-8") as f:
        json.dump(tuned, f, indent=2)

    fieldnames = list(_rows[0].keys())
    with open(os.path.join(DATA_DIR, "tuning_runs.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(_rows)

    print("\n=== tuned configuration per scenario ===")
    for scen, cfg in tuned.items():
        gain = cfg["mean_revenue"] / cfg["online_best_fit_revenue"] - 1
        print(f"  {scen:5s} space={cfg['space']:<5g} frag={cfg['frag']:<5g} "
              f"opp={cfg['opp']:<5g} batch={cfg['batch_days']}d  "
              f"revenue={cfg['mean_revenue']:,.0f}  vs online-BF {gain:+.1%}")
    print("\nWrote tuned_weights.json and tuning_runs.csv to results/phase4/data/")


if __name__ == "__main__":
    main()
