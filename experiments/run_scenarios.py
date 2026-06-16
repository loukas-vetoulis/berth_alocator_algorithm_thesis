"""
Multi-scenario comparison experiment.

Runs four models across five demand/supply scenarios in one pass.
No variables need to be changed — all scenarios are predefined.

Scenarios (fixed, 8 berths, seed=42):
  Under-demand  0.5x   4 boats  Marina half-empty
  Balanced      1.0x   8 boats  One boat per berth
  Light excess  1.5x  12 boats  Some boats turned away
  Over-demand   2.0x  16 boats  Clear scarcity
  High demand   3.0x  24 boats  Intense competition

Models (run for every scenario):
  1. Basic              unconstrained static
  2. Extended           static + compat + power capacity
  3. Side-by-side       extended + two boats per wide berth
  4. Temporal           14-day season + compat + power capacity
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.core.data_generator import generate_instance
from src.models.model_basic import solve_basic
from src.models.model_extensions import solve_extended
from src.models.model_temporal import solve_temporal
from src.core.verifier import verify_solution

RESULTS  = os.path.join(os.path.dirname(__file__), "..", "results")
N_BERTHS = 8
N_DAYS   = 14
SEED     = 42

SCENARIOS = [
    ("Under-demand", 4),
    ("Balanced",     8),
    ("Light excess", 12),
    ("Over-demand",  16),
    ("High demand",  24),
]

MODEL_LABELS = ["Basic", "Extended", "Side-by-side", "Temporal"]

# ── Helpers ───────────────────────────────────────────────────────────────────

def count_assigned(result, inst):
    if result.assignment is None:
        return 0, len(inst.boats)
    if result.assignment.ndim == 2:
        return int(result.assignment.sum()), len(inst.boats)
    return int((result.assignment.sum(axis=(0, 2)) > 0).sum()), len(inst.boats)

# ── Run all scenarios ─────────────────────────────────────────────────────────
# revenue_matrix[scenario_idx][model_idx]
revenue_matrix = []
scenario_data  = []

for scenario_label, n_boats in SCENARIOS:
    ratio      = n_boats / N_BERTHS
    inst       = generate_instance(n_berths=N_BERTHS, n_boats=n_boats, seed=SEED)
    inst_temp  = generate_instance(n_berths=N_BERTHS, n_boats=n_boats, seed=SEED,
                                   n_days=N_DAYS)

    results = [
        solve_basic(inst),
        solve_extended(inst, use_compat=True, use_utility=True, use_vip=True),
        solve_extended(inst, use_compat=True, use_utility=True,
                       use_vip=True, side_by_side=True),
        solve_temporal(inst_temp, allow_relocation=False,
                       use_compat=True, use_utility=True),
    ]
    insts = [inst, inst, inst, inst_temp]

    revenues = [r.objective_value or 0.0 for r in results]
    revenue_matrix.append(revenues)
    scenario_data.append((scenario_label, ratio, n_boats, results, insts, revenues))

# ── Print per-scenario tables ─────────────────────────────────────────────────
for scenario_label, ratio, n_boats, results, insts, revenues in scenario_data:
    base_rev = revenues[0] or 1.0
    print()
    print("=" * 66)
    print(f"  SCENARIO: {scenario_label:<14}  |  {N_BERTHS} berths, "
          f"{n_boats} boats ({ratio:.1f}x), {N_DAYS} days, seed={SEED}")
    print("=" * 66)
    print(f"  {'Model':<16}  {'Revenue':>10}  {'vs Basic':>9}  "
          f"{'Assigned':>9}  {'Status'}")
    print("  " + "-" * 60)

    for label, result, inst in zip(MODEL_LABELS, results, insts):
        rev   = result.objective_value or 0.0
        delta = rev - revenues[0]
        sign  = "+" if delta >= 0 else ""
        pct   = f"{sign}{100*delta/base_rev:.1f}%" if base_rev else "-"
        assigned, total = count_assigned(result, inst)
        status = "OK" if verify_solution(inst, result).passed else "FAIL"
        print(f"  {label:<16}  {rev:>10,.0f}  {pct:>9}  "
              f"{assigned:>4}/{total:<4}  {status}")

    print("=" * 66)

# ── Print summary revenue matrix ──────────────────────────────────────────────
col_w = 10
header_labels = [f"{n/N_BERTHS:.1f}x" for _, n in SCENARIOS]

print()
print("=" * (20 + col_w * len(SCENARIOS) + 4))
print(f"  REVENUE MATRIX  ({N_BERTHS} berths, seed={SEED})")
print(f"  Rows = model, Columns = demand/supply ratio")
print("=" * (20 + col_w * len(SCENARIOS) + 4))

header = "  " + f"{'Model':<16}  " + "  ".join(f"{h:>{col_w}}" for h in header_labels)
print(header)
print("  " + "-" * (16 + 2 + (col_w + 2) * len(SCENARIOS)))

for model_idx, model_label in enumerate(MODEL_LABELS):
    row = "  " + f"{model_label:<16}  "
    row += "  ".join(
        f"{revenue_matrix[s][model_idx]:>{col_w},.0f}"
        for s in range(len(SCENARIOS))
    )
    print(row)

print("=" * (20 + col_w * len(SCENARIOS) + 4))
print()
print("  How to read the matrix:")
print("  - Each column is a scenario (ratio = boats / berths).")
print("  - Each row is a model. Read left to right to see how a model scales")
print("    as competition increases.")
print("  - Read top to bottom within a column to see what each model layer")
print("    adds (or costs) for that level of demand.")
print("  - Basic revenue plateaus once berths are full (around 1.5x).")
print("  - Temporal revenue keeps growing because more boats = more booking")
print("    combinations to choose from across 14 days.")
print()

# ── Plot: grouped bar chart ───────────────────────────────────────────────────
ratios     = [n / N_BERTHS for _, n in SCENARIOS]
ratio_labels = [f"{r:.1f}x" for r in ratios]
x          = np.arange(len(SCENARIOS))
n_models   = len(MODEL_LABELS)
bar_width  = 0.18
colors     = ["#4878CF", "#6ACC65", "#D65F5F", "#B47CC7"]

fig, ax = plt.subplots(figsize=(12, 6))

for m_idx, (label, color) in enumerate(zip(MODEL_LABELS, colors)):
    offsets = (m_idx - (n_models - 1) / 2) * bar_width
    vals = [revenue_matrix[s][m_idx] for s in range(len(SCENARIOS))]
    bars = ax.bar(x + offsets, vals, bar_width, label=label, color=color, alpha=0.85)

ax.set_xlabel("Demand / Supply Ratio (boats / berths)", fontsize=11)
ax.set_ylabel("Revenue (EUR)", fontsize=11)
ax.set_title(
    f"Model Revenue across Demand/Supply Scenarios\n"
    f"({N_BERTHS} berths, {N_DAYS}-day season, seed={SEED})",
    fontsize=12,
)
ax.set_xticks(x)
ax.set_xticklabels(ratio_labels)
ax.legend(title="Model")
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()

os.makedirs(RESULTS, exist_ok=True)
plot_path = os.path.join(RESULTS, "scenario_comparison.png")
fig.savefig(plot_path, dpi=150)
plt.close(fig)
print(f"  Plot saved to results/scenario_comparison.png")
