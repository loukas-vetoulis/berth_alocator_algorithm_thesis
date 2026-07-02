"""Final policy comparison on the realistic dynamic booking stream.

Requests arrive over time (booking day != arrival day); policies decide
without knowing future demand:

  online[first_fit]    naive dock-walk, decide at booking instant
  online[best_fit]     tightest free berth, decide at booking instant
  online[revenue_max]  myopic highest-rate berth, decide at booking instant
  batch[plain]         nightly MILP, pure revenue objective (no weights)
  batch[tuned]         nightly MILP with the tuned weights per scenario
                       (from tune_weights.py; falls back to space=1 if the
                       tuning results are missing)

Each is run for three demand scenarios x three request seeds. A clairvoyant
LP upper bound and an LP-rounded feasible clairvoyant plan bracket the
perfect-information optimum (seed 7 per scenario).

Run from the project root:  python -X utf8 experiments/phase4/run_dynamic_simulation.py
"""
from __future__ import annotations
import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np

from src.realistic.dataset import SCENARIOS, build_dataset
from src.realistic.demand import SEASON_DAYS
from src.simulation.engine import simulate_season
from src.simulation.metrics import SEGMENTS, compute_outcome
from src.simulation.policies import (
    BatchMILP, OnlineGreedy, OracleBounds, Weights, category_upper_bound,
    clairvoyant_greedy, oracle_bounds,
)
from experiments.phase4.plotting import (
    grouped_bars, occupancy_heatmap, gantt_zoom, season_lines, _finish,
)
import matplotlib.pyplot as plt

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
FIG_DIR = os.path.join(ROOT, "results", "phase4")
DATA_DIR = os.path.join(FIG_DIR, "data")

SEEDS = [7, 11, 23]
ORACLE_SEED = 7
# The exact season pair LP (~700k variables) does not finish in practical
# time even with the interior-point solver, so the comparison uses the fast
# category-level upper bound plus a clairvoyant greedy plan by default.
ORACLE_EXACT = False
ORACLE_TIME_LIMIT = 1500.0
POLICIES = ["online[first_fit]", "online[best_fit]", "online[revenue_max]",
            "batch[plain]", "batch[tuned]"]

FALLBACK_TUNED = {"space": 1.0, "frag": 0.0, "opp": 0.0, "batch_days": 1}


def load_tuned() -> dict:
    path = os.path.join(DATA_DIR, "tuned_weights.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    print("WARNING: tuned_weights.json not found, using fallback weights")
    return {scen: dict(FALLBACK_TUNED) for scen in SCENARIOS}


def make_policy(name: str, marina, tuned_cfg: dict):
    if name.startswith("online"):
        return OnlineGreedy(marina, name.split("[")[1].rstrip("]"))
    if name == "batch[plain]":
        return BatchMILP(marina, Weights(), batch_days=1, name="batch[plain]")
    if name == "batch[tuned]":
        w = Weights(space=tuned_cfg["space"], frag=tuned_cfg["frag"],
                    opp=tuned_cfg["opp"])
        return BatchMILP(marina, w, batch_days=tuned_cfg["batch_days"],
                         name="batch[tuned]")
    raise ValueError(name)


def compute_oracle(ds) -> OracleBounds:
    """Exact clairvoyant LP bounds, falling back to the aggregated category
    upper bound plus a clairvoyant greedy plan if the season LP fails."""
    import time as _time
    if ORACLE_EXACT:
        try:
            return oracle_bounds(ds.marina, ds.requests, SEASON_DAYS,
                                 time_limit=ORACLE_TIME_LIMIT)
        except RuntimeError as e:
            print(f"  WARNING: exact oracle LP failed ({e}); using category UB")
    t0 = _time.perf_counter()
    ub = category_upper_bound(ds.marina, ds.requests, SEASON_DAYS)
    decisions, cal = clairvoyant_greedy(ds.marina, ds.requests, SEASON_DAYS)
    return OracleBounds(
        upper_bound=ub,
        decisions=decisions,
        calendar=cal,
        feasible_revenue=sum(d.revenue for d in decisions),
        lp_seconds=0.0,
        total_seconds=_time.perf_counter() - t0,
    )


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    tuned = load_tuned()

    rows = []
    outcomes = {}     # (scen, seed, policy) -> SeasonOutcome
    oracle = {}       # scen -> dict

    for scen in SCENARIOS:
        print(f"\n=== scenario {scen} (x{SCENARIOS[scen]}) ===")
        for seed in SEEDS:
            ds = build_dataset(scen, seed=seed)
            for pname in POLICIES:
                out = simulate_season(
                    ds.marina, ds.requests, make_policy(pname, ds.marina, tuned[scen]))
                outcomes[(scen, seed, pname)] = out
                rows.append({"scenario": scen, "seed": seed, **out.row()})
                print(f"  seed={seed} {pname:22s} rev={out.revenue:>10.0f} "
                      f"acc={out.acceptance_rate:.3f} occ={out.occupancy:.3f}",
                      flush=True)

        print(f"  oracle bounds (seed {ORACLE_SEED}) ...", flush=True)
        ds = build_dataset(scen, seed=ORACLE_SEED)
        ob = compute_oracle(ds)
        oracle_out = compute_outcome(ds.marina, ds.requests, ob.decisions,
                                     ob.calendar, "oracle", ob.total_seconds)
        outcomes[(scen, ORACLE_SEED, "oracle")] = oracle_out
        oracle[scen] = {
            "upper_bound": round(ob.upper_bound, 0),
            "feasible_revenue": round(ob.feasible_revenue, 0),
            "acceptance_rate": round(oracle_out.acceptance_rate, 4),
            "occupancy": round(oracle_out.occupancy, 4),
            "lp_seconds": round(ob.lp_seconds, 1),
        }
        print(f"  oracle UB={ob.upper_bound:,.0f}  feasible={ob.feasible_revenue:,.0f} "
              f"({ob.feasible_revenue / ob.upper_bound:.1%} of UB, "
              f"LP {ob.lp_seconds:.0f}s)", flush=True)

    # ── summary ──
    summary = {}
    for scen in SCENARIOS:
        summary[scen] = {"oracle": oracle[scen]}
        for pname in POLICIES:
            revs = [outcomes[(scen, s, pname)].revenue for s in SEEDS]
            accs = [outcomes[(scen, s, pname)].acceptance_rate for s in SEEDS]
            occs = [outcomes[(scen, s, pname)].occupancy for s in SEEDS]
            summary[scen][pname] = {
                "revenue_mean": round(float(np.mean(revs)), 0),
                "revenue_std": round(float(np.std(revs)), 0),
                "acceptance_mean": round(float(np.mean(accs)), 4),
                "occupancy_mean": round(float(np.mean(occs)), 4),
                "vs_oracle_ub": round(float(np.mean(revs)) / oracle[scen]["upper_bound"], 4),
            }

    with open(os.path.join(DATA_DIR, "comparison_summary.json"), "w",
              encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    with open(os.path.join(DATA_DIR, "comparison_runs.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print("\n=== summary (mean over seeds) ===")
    for scen in SCENARIOS:
        print(f"\n  {scen} demand  (oracle UB {oracle[scen]['upper_bound']:,.0f})")
        for pname in POLICIES:
            s = summary[scen][pname]
            print(f"    {pname:22s} rev={s['revenue_mean']:>10,.0f} "
                  f"(+-{s['revenue_std']:,.0f})  acc={s['acceptance_mean']:.3f}  "
                  f"occ={s['occupancy_mean']:.3f}  vs UB {s['vs_oracle_ub']:.1%}")

    make_figures(summary, outcomes, oracle)
    print("\nDone. Data in results/phase4/data/, figures in results/phase4/")


def make_figures(summary, outcomes, oracle):
    scens = list(SCENARIOS)
    print("\nFigures:")

    # c1: revenue by policy and scenario (+ oracle bracket)
    series = {p: [summary[s][p]["revenue_mean"] for s in scens] for p in POLICIES}
    series["oracle"] = [oracle[s]["feasible_revenue"] for s in scens]
    grouped_bars(scens, series, "season revenue (EUR)",
                 "Season revenue by policy and demand scenario "
                 "(oracle = clairvoyant feasible plan)",
                 os.path.join(FIG_DIR, "c1_revenue_by_policy.png"))

    # c2: competitive ratio vs clairvoyant upper bound
    ratio = {p: [summary[s][p]["revenue_mean"] / oracle[s]["upper_bound"]
                 for s in scens] for p in POLICIES}
    ratio["oracle"] = [oracle[s]["feasible_revenue"] / oracle[s]["upper_bound"]
                       for s in scens]
    grouped_bars(scens, ratio, "revenue / clairvoyant upper bound",
                 "Competitive ratio against the perfect-information bound",
                 os.path.join(FIG_DIR, "c2_competitive_ratio.png"))

    # c3: acceptance by boat segment, base scenario
    seg_series = {}
    for p in POLICIES:
        accs = np.mean([[outcomes[("base", s, p)].seg_acceptance[seg]
                         for seg in SEGMENTS] for s in SEEDS], axis=0)
        seg_series[p] = accs.tolist()
    grouped_bars([f"{seg}" for seg in SEGMENTS], seg_series,
                 "acceptance rate",
                 "Acceptance by boat segment (base demand)",
                 os.path.join(FIG_DIR, "c3_acceptance_by_segment.png"))

    # c4: monthly revenue, base scenario, seed 7
    months = list(range(4, 11))
    fig, ax = plt.subplots(figsize=(9, 4.4))
    from experiments.phase4.plotting import POLICY_COLORS
    for p in POLICIES + ["oracle"]:
        key = ("base", ORACLE_SEED, p)
        if key not in outcomes:
            continue
        ax.plot(months, [outcomes[key].monthly_revenue[m] for m in months],
                marker="o", label=p, color=POLICY_COLORS.get(p))
    ax.set_xticks(months)
    ax.set_xticklabels(["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct"])
    ax.set_ylabel("revenue (EUR)")
    ax.set_title("Monthly revenue by policy (base demand, seed 7)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    _finish(fig, os.path.join(FIG_DIR, "c4_monthly_revenue.png"))

    # c5: daily occupancy curves, base scenario, seed 7
    occ_series = {p: outcomes[("base", ORACLE_SEED, p)].daily_occupancy
                  for p in ["online[best_fit]", "online[revenue_max]",
                            "batch[plain]", "batch[tuned]", "oracle"]}
    season_lines(occ_series, "transient pool occupancy",
                 "Daily occupancy of the transient pool (base demand, seed 7)",
                 os.path.join(FIG_DIR, "c5_daily_occupancy.png"))

    # c6/c7: occupancy heatmaps, base scenario, seed 7
    ds = build_dataset("base", seed=ORACLE_SEED)
    trans = ds.marina.transient_ids
    for p, fname in [("online[best_fit]", "c6_heatmap_online_bestfit.png"),
                     ("batch[tuned]", "c7_heatmap_batch_tuned.png")]:
        out = outcomes[("base", ORACLE_SEED, p)]
        occupancy_heatmap(out.occ_snapshot,
                          f"Berth occupancy, {p} (base demand): blue=booked, white=free",
                          os.path.join(FIG_DIR, fname), transient_ids=trans)

    # c8: booking-level Gantt zoom of the large-berth piers in August
    out = outcomes[("base", ORACLE_SEED, "batch[tuned]")]
    big = [i for i in trans if ds.marina.category_of[i] in ("G", "H")]
    aug1 = 122
    labels = [f"{ds.marina.category_of[i]}-{i}" for i in big]
    # reconstruct booked_by from decisions for the Gantt
    booked_by = np.full_like(out.occ_snapshot, -1, dtype=np.int32)
    for d in out.decisions:
        if d.accepted:
            booked_by[d.berth_id, d.request.arrival_day:d.request.departure_day] = d.request.id
    gantt_zoom(out.occ_snapshot, booked_by, big, (aug1, aug1 + 21),
               "Superyacht piers (categories G/H), batch[tuned], 1-21 August",
               os.path.join(FIG_DIR, "c8_gantt_zoom_august.png"),
               berth_labels=labels)


if __name__ == "__main__":
    main()
