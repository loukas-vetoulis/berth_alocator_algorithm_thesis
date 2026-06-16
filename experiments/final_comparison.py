"""Final-model comparison experiment.

Compares the unified final model (under several parameter configurations)
against greedy baselines and an online arrival simulator, across multiple
random seeds and demand levels. Produces aggregated tables and plots.

  Part A  Main comparison: gross revenue, assignment rate, berth-day
          utilisation and solve time for every method, averaged over seeds at
          each demand level (boats / berths).
  Part B  Smallest-berth focus: greedy first-fit vs best-fit wasted length, and
          a space_weight sweep tracing the revenue-vs-compaction frontier.
  Part C  Online vs offline: realised revenue of online greedy as a fraction of
          the offline optimum (competitive ratio).

All MILP configurations keep the core business rules (compatibility, shore
power, VIP contracts) enabled, so every method is business-feasible and the
comparison is apples-to-apples. Every solution is verified.
"""
import gc
import os
import sys

# Must run before NumPy import — prevents OpenBLAS OOM on Windows (many MILP solves).
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from src.core.data_generator import generate_instance
from src.models.model_final import solve_final, build_waste_length_matrix
from src.heuristics.baselines import first_fit, best_fit, revenue_priority, gross_revenue
from src.heuristics.online_simulator import simulate_online
from src.core.verifier import verify_solution
from src.core.visualizer import plot_grouped_metric, plot_pareto

RESULTS = os.path.join(os.path.dirname(__file__), "..", "results")

N_BERTHS = 8
N_DAYS   = 14
SEEDS    = [0, 1, 2, 3, 4]
DEMANDS  = [0.5, 1.0, 2.0, 3.0]          # boats per berth
BIZ      = dict(use_compat=True, use_utility=True, use_vip=True)

# Final-model configurations (business rules always on; optional features vary).
# The smallest-berth (space_weight) feature is studied separately in Part B.
FINAL_CONFIGS = {
    "base":         dict(),
    "side-by-side": dict(side_by_side=True),
    "soft-penalty": dict(soft_depth=True),
    "relocation":   dict(allow_relocation=True, max_relocations=1),
    "full-mix":     dict(side_by_side=True, soft_depth=True),
}


# ── metrics ───────────────────────────────────────────────────────────────────
def boats_served(result) -> int:
    X = result.assignment
    if X is None:
        return 0
    if X.ndim == 2:
        return int(np.sum(X.sum(axis=0) > 0))
    return int(np.sum(X.sum(axis=(0, 2)) > 0))


def assignment_rate(inst, result) -> float:
    return boats_served(result) / len(inst.boats) if inst.boats else 0.0


def utilization(inst, result) -> float:
    X = result.assignment
    if X is None:
        return 0.0
    n = len(inst.berths)
    if X.ndim == 2:
        occupied = int(np.sum(X.sum(axis=1) > 0))
        total = n
    else:
        occupied = int(np.sum(X.sum(axis=1) > 0))   # (berth, day) slots with >=1 boat
        total = n * X.shape[2]
    return occupied / total if total else 0.0


def wasted_length(inst, result) -> float:
    W = build_waste_length_matrix(inst)
    X = result.assignment
    if X is None:
        return 0.0
    if X.ndim == 2:
        return float(np.sum(W * X))
    return float(np.sum(W[:, :, np.newaxis] * X))


def run_all_methods(inst, seed):
    """Return {method_name: (result, online_metrics_or_None)}."""
    out = {}
    for name, kw in FINAL_CONFIGS.items():
        out[f"final[{name}]"] = (solve_final(inst, **BIZ, **kw), None)
        gc.collect()
    out["greedy[first_fit]"] = (first_fit(inst, **BIZ), None)
    out["greedy[best_fit]"] = (best_fit(inst, **BIZ), None)
    out["greedy[revenue_priority]"] = (revenue_priority(inst, **BIZ), None)
    for policy in ("first_fit", "best_fit"):
        res, met = simulate_online(inst, policy=policy, seed=seed, **BIZ)
        out[f"online[{policy}]"] = (res, met)
    gc.collect()
    return out


def aggregate(values: list[float]) -> tuple[float, float]:
    arr = np.array(values, dtype=float)
    return float(arr.mean()), float(arr.std())


# ── Part A: main comparison across seeds and demand levels ─────────────────────
def main():
    print("=" * 78)
    print("PART A - MAIN COMPARISON (mean over seeds {}, {} berths, {} days)".format(
        SEEDS, N_BERTHS, N_DAYS))
    print("=" * 78)

    method_names = (
        [f"final[{k}]" for k in FINAL_CONFIGS]
        + ["greedy[first_fit]", "greedy[best_fit]", "greedy[revenue_priority]",
           "online[first_fit]", "online[best_fit]"]
    )

    # results[demand][method] = dict of metric lists across seeds
    agg = {d: {mn: {"rev": [], "rate": [], "served": [], "util": [], "waste": [], "time": [], "ok": []}
               for mn in method_names} for d in DEMANDS}
    comp_ratio = {d: {"online[first_fit]": [], "online[best_fit]": []} for d in DEMANDS}

    for demand in DEMANDS:
        n_boats = max(1, int(round(demand * N_BERTHS)))
        for seed in SEEDS:
            print(f"  seed {seed} ...", flush=True)
            inst = generate_instance(n_berths=N_BERTHS, n_boats=n_boats, seed=seed, n_days=N_DAYS)
            methods = run_all_methods(inst, seed)
            base_gross = gross_revenue(inst, methods["final[base]"][0].assignment)
            for mn, (res, met) in methods.items():
                rep = verify_solution(inst, res)
                agg[demand][mn]["rev"].append(gross_revenue(inst, res.assignment))
                agg[demand][mn]["rate"].append(assignment_rate(inst, res))
                agg[demand][mn]["served"].append(boats_served(res))
                agg[demand][mn]["util"].append(utilization(inst, res))
                agg[demand][mn]["waste"].append(wasted_length(inst, res))
                agg[demand][mn]["time"].append(res.solve_time)
                agg[demand][mn]["ok"].append(rep.passed)
                if mn in comp_ratio[demand] and base_gross > 0:
                    comp_ratio[demand][mn].append(
                        gross_revenue(inst, res.assignment) / base_gross)
            del methods, inst
            gc.collect()

        # Print a per-demand table.
        print(f"\nDemand {demand}x  ({n_boats} boats / {N_BERTHS} berths)")
        print(f"  {'method':28s} {'gross_rev':>12s} {'served':>8s} {'assign%':>9s} {'util%':>8s} "
              f"{'waste_m':>9s} {'time(s)':>9s} {'verify':>7s}")
        print("  " + "-" * 94)
        for mn in method_names:
            rev_m, rev_s = aggregate(agg[demand][mn]["rev"])
            rate_m, _ = aggregate(agg[demand][mn]["rate"])
            served_m, _ = aggregate(agg[demand][mn]["served"])
            util_m, _ = aggregate(agg[demand][mn]["util"])
            waste_m, _ = aggregate(agg[demand][mn]["waste"])
            time_m, _ = aggregate(agg[demand][mn]["time"])
            allok = all(agg[demand][mn]["ok"])
            print(f"  {mn:28s} {rev_m:>12.0f} {served_m:>8.1f} {100*rate_m:>8.1f}% {100*util_m:>7.1f}% "
                  f"{waste_m:>9.0f} {time_m:>9.3f} {'OK' if allok else 'FAIL':>7s}")

    # ── plots for Part A ──
    demand_labels = [f"{d}x" for d in DEMANDS]
    plot_methods = ["final[base]", "final[side-by-side]", "final[soft-penalty]",
                    "final[full-mix]", "greedy[best_fit]", "online[best_fit]"]

    rev_series = {mn: ([], []) for mn in plot_methods}
    util_series = {mn: ([], []) for mn in plot_methods}
    for mn in plot_methods:
        for d in DEMANDS:
            rm, rs = aggregate(agg[d][mn]["rev"])
            um, us = aggregate(agg[d][mn]["util"])
            rev_series[mn][0].append(rm); rev_series[mn][1].append(rs)
            util_series[mn][0].append(um * 100); util_series[mn][1].append(us * 100)

    plot_grouped_metric(demand_labels, rev_series,
                        save_path=os.path.join(RESULTS, "final_revenue.png"),
                        ylabel="Gross revenue", title="Final model vs greedy vs online - revenue")
    plot_grouped_metric(demand_labels, util_series,
                        save_path=os.path.join(RESULTS, "final_utilization.png"),
                        ylabel="Berth-day utilisation (%)",
                        title="Berth-day utilisation by method and demand")

    # Boats served summary (mean count across seeds at each demand).
    served_series = {mn: ([], []) for mn in plot_methods}
    for mn in plot_methods:
        for d in DEMANDS:
            sm, ss = aggregate(agg[d][mn]["served"])
            served_series[mn][0].append(sm)
            served_series[mn][1].append(ss)
    plot_grouped_metric(demand_labels, served_series,
                        save_path=os.path.join(RESULTS, "final_boats_served.png"),
                        ylabel="Mean boats served (count)",
                        title="Boats accommodated by method and demand")

    print("\n" + "=" * 78)
    print("SUMMARY - BOATS SERVED (mean count; higher = more boats accommodated)")
    print("=" * 78)
    hdr = f"  {'method':28s}" + "".join(f"{str(d)+'x':>8s}" for d in DEMANDS) + f"{'peak':>8s}"
    print(hdr)
    print("  " + "-" * (28 + 8 * len(DEMANDS) + 8))
    for mn in method_names:
        row = f"  {mn:28s}"
        peak = 0.0
        for d in DEMANDS:
            sm, _ = aggregate(agg[d][mn]["served"])
            peak = max(peak, sm)
            row += f"{sm:>8.1f}"
        row += f"{peak:>8.1f}"
        print(row)

    # ── Part C: online vs offline competitive ratio ──
    print("\n" + "=" * 78)
    print("PART C - ONLINE vs OFFLINE (realised / offline-optimum gross revenue)")
    print("=" * 78)
    print(f"  {'demand':>8s} {'online[first_fit]':>20s} {'online[best_fit]':>20s}")
    cr_series = {"online[first_fit]": ([], []), "online[best_fit]": ([], [])}
    for d in DEMANDS:
        row = [f"  {str(d)+'x':>8s}"]
        for mn in ("online[first_fit]", "online[best_fit]"):
            cm, cs = aggregate(comp_ratio[d][mn]) if comp_ratio[d][mn] else (0.0, 0.0)
            cr_series[mn][0].append(cm); cr_series[mn][1].append(cs)
            row.append(f"{cm:>19.2%}")
        print(" ".join(row))
    plot_grouped_metric(demand_labels, cr_series,
                        save_path=os.path.join(RESULTS, "final_online_vs_offline.png"),
                        ylabel="Competitive ratio (online / offline)",
                        title="Online greedy as a fraction of the offline optimum")

    # ── Part B: smallest-berth focus ──
    print("\n" + "=" * 78)
    print("PART B - SMALLEST-BERTH BEHAVIOUR")
    print("=" * 78)
    inst_b = generate_instance(n_berths=N_BERTHS, n_boats=2 * N_BERTHS, seed=0, n_days=N_DAYS)
    ff = first_fit(inst_b, **BIZ)
    bf = best_fit(inst_b, **BIZ)

    def per_slot_waste(res):
        slots = int(res.assignment.sum())
        return (wasted_length(inst_b, res) / slots) if slots else 0.0

    print("  Greedy first-fit vs best-fit (best-fit = smallest fitting berth):")
    print(f"    {'policy':10s} {'revenue':>9s} {'served':>7s} {'waste/slot(m)':>14s}")
    print(f"    {'first_fit':10s} {gross_revenue(inst_b, ff.assignment):>9.0f} "
          f"{boats_served(ff):>7d} {per_slot_waste(ff):>14.2f}")
    print(f"    {'best_fit':10s} {gross_revenue(inst_b, bf.assignment):>9.0f} "
          f"{boats_served(bf):>7d} {per_slot_waste(bf):>14.2f}")
    print("    -> best-fit packs each boat tighter (lower waste/slot), keeping large")
    print("       berths free, so it serves more boats and earns more under high demand.")

    print("\n  MILP space_weight sweep (revenue vs compaction frontier):")
    weights = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.75, 1.0]
    xs, ys, labs = [], [], []
    print(f"    {'space_weight':>13s} {'gross_rev':>11s} {'wasted_m':>10s} {'served':>7s}")
    for sw in weights:
        r = solve_final(inst_b, space_weight=sw, **BIZ)
        g = gross_revenue(inst_b, r.assignment)
        w = wasted_length(inst_b, r)
        ok = verify_solution(inst_b, r).passed
        sv = boats_served(r)
        print(f"    {sw:>13} {g:>11.0f} {w:>10.0f} {sv:>7d}   {'OK' if ok else 'FAIL'}")
        xs.append(w); ys.append(g); labs.append(f"w={sw}")
        del r
        gc.collect()
    plot_pareto(xs, ys, point_labels=labs,
                save_path=os.path.join(RESULTS, "final_space_tradeoff.png"))

    print("\nDone. Plots written to results/: final_revenue.png, final_utilization.png, "
          "final_boats_served.png, final_online_vs_offline.png, final_space_tradeoff.png")


if __name__ == "__main__":
    main()
