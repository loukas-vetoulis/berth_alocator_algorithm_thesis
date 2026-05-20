"""
Full demonstration experiment.
Shows: (1) side-by-side benefit with scarce berths,
       (2) temporal model with clear stay durations,
       (3) gap-filling short-stay discount.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from src.data_generator import generate_instance, generate_gapfill_instance
from src.model_basic import solve_basic
from src.model_extensions import solve_extended
from src.model_temporal import solve_temporal
from src.verifier import verify_solution
from src.visualizer import plot_revenue_comparison, plot_temporal_gantt

RESULTS = os.path.join(os.path.dirname(__file__), "..", "results")


# ─────────────────────────────────────────────────────────────
# PART 1 — Side-by-side benefit (need more boats than berths)
# ─────────────────────────────────────────────────────────────
print("=" * 60)
print("PART 1 -- Side-by-side berthing")
print("  10 berths, 20 boats (twice as many boats as berths)")
print("  Without sbs: only 10 boats can park (one per berth)")
print("  With sbs:    wide berths fit 2 boats side-by-side")
print("=" * 60)

inst_sbs = generate_instance(n_berths=10, n_boats=20, seed=42)

r_no_sbs = solve_extended(inst_sbs, use_compat=False, use_utility=False,
                           use_vip=False, side_by_side=False)
r_sbs    = solve_extended(inst_sbs, use_compat=False, use_utility=False,
                           use_vip=False, side_by_side=True)

print(f"\n  Without side-by-side:")
print(f"    Revenue   : {r_no_sbs.objective_value:.0f}")
print(f"    Boats used: {int(r_no_sbs.assignment.sum())} / {len(inst_sbs.boats)}")

print(f"\n  With side-by-side:")
print(f"    Revenue   : {r_sbs.objective_value:.0f}")
print(f"    Boats used: {int(r_sbs.assignment.sum())} / {len(inst_sbs.boats)}")

gain_sbs = r_sbs.objective_value - r_no_sbs.objective_value
print(f"\n  Extra revenue from side-by-side: +{gain_sbs:.0f}  "
      f"({100*gain_sbs/r_no_sbs.objective_value:.1f}% more)")
print("  (More boats parked = more money earned)")


# ─────────────────────────────────────────────────────────────
# PART 2 — Temporal model: stay durations matter
# ─────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("PART 2 -- Temporal model (10 berths, 20 boats, 14 days)")
print("  Each boat has its own arrival/departure day.")
print("  A boat staying 7 days earns 7x the daily revenue.")
print("  Same berth can serve different boats on different days.")
print("=" * 60)

inst_t = generate_instance(n_berths=10, n_boats=20, seed=42, n_days=14)

print("\n  Boat stay durations:")
print(f"  {'Boat':>5}  {'Arrival':>8}  {'Depart':>8}  {'Days':>5}  {'Length':>8}")
print("  " + "-" * 42)
for boat in inst_t.boats:
    days = boat.departure_day - boat.arrival_day
    tag = " <-- short" if days < 5 else ""
    print(f"  {boat.id:>5}  {boat.arrival_day:>8}  {boat.departure_day:>8}  "
          f"{days:>5}  {boat.length:>7.1f}m{tag}")

r_static = solve_basic(inst_t)
r_stable = solve_temporal(inst_t, allow_relocation=False)

print(f"\n  Static model (ignores time, 1 assignment per berth):")
print(f"    Revenue = {r_static.objective_value:.0f}")
print(f"    Boats assigned: {int(r_static.assignment.sum())} / {len(inst_t.boats)}")

print(f"\n  Temporal model (uses arrival/departure days):")
print(f"    Revenue = {r_stable.objective_value:.0f}")
if r_stable.assignment is not None:
    used_days = int(r_stable.assignment.sum())
    print(f"    Berth-day slots used: {used_days} (berths x days with a boat)")

gain_t = r_stable.objective_value - r_static.objective_value
print(f"\n  Extra revenue by using dates: +{gain_t:.0f}  "
      f"({100*gain_t/r_static.objective_value:.1f}% more)")
print("  Why? Berth 0 can host Boat A days 1-5, then Boat B days 7-14.")
print("  Static model could only pick ONE of them.")


# ─────────────────────────────────────────────────────────────
# PART 3 — Gap-filling short-stay discount
# ─────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("PART 3 -- Gap-filling short-stay discount")
print()
print("  Scenario: 8 berths, 14-day season.")
print("  8 long-stay boats (5-10 days) fill most of the schedule.")
print("  They leave short gaps: e.g. berth free for 3 days between")
print("  two long-stay boats. These 3 days earn ZERO without action.")
print()
print("  Marina strategy: offer short-stay boats (1-4 days) a 20%")
print("  price discount. They fill the gaps. Revenue goes up.")
print("=" * 60)

N_BERTHS = 8
N_DAYS   = 14
inst_long_only = generate_gapfill_instance(
    n_berths=N_BERTHS, n_long_boats=8, n_short_boats=0, n_days=N_DAYS, seed=5)
inst_with_short = generate_gapfill_instance(
    n_berths=N_BERTHS, n_long_boats=8, n_short_boats=16, n_days=N_DAYS, seed=5)

# Solve: long boats only (no short-stay boats available)
r_long_only = solve_temporal(inst_long_only, allow_relocation=False)

# Solve: long + short-stay boats, full price for all
r_full_price = solve_temporal(inst_with_short, allow_relocation=False)

# Solve: long + short-stay boats, 20% discount for stays < 5 days
r_discounted = solve_temporal(inst_with_short, allow_relocation=False,
                               short_stay_discount=0.20, min_stay_days=5)

def count_empty_slots(result, n_berths, n_days):
    if result.assignment is None:
        return n_berths * n_days
    return n_berths * n_days - int(result.assignment.sum())

def count_used_slots(result):
    if result.assignment is None:
        return 0
    return int(result.assignment.sum())

total_slots = N_BERTHS * N_DAYS
e_long    = count_empty_slots(r_long_only,  N_BERTHS, N_DAYS)
e_full    = count_empty_slots(r_full_price, N_BERTHS, N_DAYS)
e_disc    = count_empty_slots(r_discounted, N_BERTHS, N_DAYS)

print(f"\n  Scenario A: only long-stay boats (5-10 days)")
print(f"    Revenue              = {r_long_only.objective_value:.0f}")
print(f"    Berth-days occupied  = {count_used_slots(r_long_only)} / {total_slots}")
print(f"    Berth-days EMPTY     = {e_long} / {total_slots}  (lost revenue)")

print(f"\n  Scenario B: long + short-stay boats, full price")
print(f"    Revenue              = {r_full_price.objective_value:.0f}")
print(f"    Berth-days occupied  = {count_used_slots(r_full_price)} / {total_slots}")
print(f"    Berth-days EMPTY     = {e_full} / {total_slots}")
print(f"    Extra vs A           = +{r_full_price.objective_value - r_long_only.objective_value:.0f} revenue, "
      f"+{e_long - e_full} berth-days filled")

print(f"\n  Scenario C: long + short-stay boats, 20% discount for stays < 5 days")
print(f"    Discounted objective = {r_discounted.objective_value:.0f}  (marina earns less per short day)")
# compute gross revenue at full prices
if r_discounted.assignment is not None:
    p_arr = np.array([b.price_per_meter for b in inst_with_short.berths])
    l_arr = np.array([b.length          for b in inst_with_short.boats])
    R2    = np.outer(p_arr, l_arr)[:, :, np.newaxis] * np.ones(N_DAYS)
    gross_C = float((R2 * r_discounted.assignment).sum())
    print(f"    Gross value of assigned slots = {gross_C:.0f}")
print(f"    Berth-days occupied  = {count_used_slots(r_discounted)} / {total_slots}")
print(f"    Berth-days EMPTY     = {e_disc} / {total_slots}")
print(f"    Extra vs A           = +{r_discounted.objective_value - r_long_only.objective_value:.0f} revenue (after discount)")
print()
print("  Interpretation:")
print("  - Long-only: marina leaves short gaps empty, loses that revenue.")
print("  - Short stays at full price: more boats fill the gaps, revenue rises.")
print("  - Short stays at 20% discount: marina earns slightly less per gap-day")
print("    but still far more than leaving those days completely empty.")
print("  - The discount is a marketing tool: attract short-stay demand that")
print("    would otherwise go to a competitor or not book at all.")

# Show which berths have gaps identified from the long-only solution
print()
if r_long_only.assignment is not None:
    X = r_long_only.assignment
    print("  Gap analysis in long-stay-only schedule:")
    print(f"  {'Berth':>6}  {'Gap start':>10}  {'Gap end':>8}  {'Days':>5}")
    print("  " + "-" * 36)
    for i in range(N_BERTHS):
        occ = X[i, :, :].sum(axis=0)
        t = 0
        while t < N_DAYS:
            if occ[t] == 0:
                gs = t
                while t < N_DAYS and occ[t] == 0:
                    t += 1
                print(f"  {i:>6}  {gs:>10}  {t-1:>8}  {t-gs:>5}  {'(short gap)' if t-gs < 5 else '(long gap)'}")
            else:
                t += 1


# ─────────────────────────────────────────────────────────────
# Summary comparison chart
# ─────────────────────────────────────────────────────────────
results_chart = {
    "static\n(no time)":           r_static,
    "temporal\n14 days":           r_stable,
    "no side-by-side\n20 boats":   r_no_sbs,
    "side-by-side\n20 boats":      r_sbs,
    "long only\n(gaps empty)":     r_long_only,
    "long+short\nfull price":      r_full_price,
    "long+short\n20% discount":    r_discounted,
}
plot_revenue_comparison(
    results_chart,
    save_path=os.path.join(RESULTS, "full_demo_comparison.png"),
)
plot_temporal_gantt(
    inst_long_only, r_long_only,
    save_path=os.path.join(RESULTS, "gantt_long_only.png"),
)
plot_temporal_gantt(
    inst_with_short, r_discounted,
    save_path=os.path.join(RESULTS, "gantt_with_discount.png"),
)
print("\nPlots saved to results/")
