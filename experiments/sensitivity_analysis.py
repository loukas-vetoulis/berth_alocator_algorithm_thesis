import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.data_generator import generate_instance
from src.models.model_basic import solve_basic
import numpy as np

boat_counts = list(range(5, 51, 5))
results = []

print(f"{'n_boats':>8}  {'revenue':>10}  {'assigned':>9}  {'rate%':>7}  {'time(s)':>8}")
print("-" * 52)

for n_boats in boat_counts:
    inst = generate_instance(n_berths=15, n_boats=n_boats, seed=0)
    r = solve_basic(inst)
    if r.assignment is not None:
        n_assigned = int(r.assignment.sum())
    else:
        n_assigned = 0
    rate = 100.0 * n_assigned / n_boats
    results.append((n_boats, r.objective_value or 0.0, n_assigned, rate, r.solve_time))
    print(f"{n_boats:>8}  {r.objective_value or 0:>10.2f}  {n_assigned:>9}  {rate:>7.1f}  {r.solve_time:>8.4f}")

try:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    xs = [r[0] for r in results]

    axes[0].plot(xs, [r[1] for r in results], marker="o", color="steelblue")
    axes[0].set_title("Revenue vs n_boats")
    axes[0].set_xlabel("n_boats"); axes[0].set_ylabel("Revenue")

    axes[1].plot(xs, [r[3] for r in results], marker="s", color="darkorange")
    axes[1].set_title("Assignment rate vs n_boats")
    axes[1].set_xlabel("n_boats"); axes[1].set_ylabel("Assignment rate (%)")

    axes[2].plot(xs, [r[4] for r in results], marker="^", color="green")
    axes[2].set_title("Solve time vs n_boats")
    axes[2].set_xlabel("n_boats"); axes[2].set_ylabel("Time (s)")

    plt.tight_layout()
    out = os.path.join(os.path.dirname(__file__), "..", "results", "sensitivity.png")
    plt.savefig(out, dpi=150)
    print(f"\nSaved sensitivity plot to {out}")
    plt.close()
except ImportError:
    print("matplotlib not available; skipping plot.")
