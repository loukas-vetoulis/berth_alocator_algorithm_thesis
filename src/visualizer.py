from __future__ import annotations
import numpy as np
from .data_model import MarinaInstance, SolveResult


def print_assignment_table(inst: MarinaInstance, result: SolveResult) -> None:
    print(f"\nModel: {result.model_name}  |  Status: {result.status}  |  Revenue: {result.objective_value:.2f}  |  Time: {result.solve_time:.3f}s")

    if result.assignment is None:
        print("  No assignment available.")
        return

    X = result.assignment
    is_temporal = X.ndim == 3
    T = X.shape[2] if is_temporal else 1

    print(f"  {'Berth':>5}  {'Boat':>5}  {'Day':>4}  {'Revenue':>10}  {'W':>5}  {'L':>5}  {'D':>5}")
    print("  " + "-" * 55)

    for i, berth in enumerate(inst.berths):
        for j, boat in enumerate(inst.boats):
            if is_temporal:
                for t in range(T):
                    if X[i, j, t] == 1:
                        rev = berth.price_per_meter * boat.length
                        print(f"  {i:>5}  {j:>5}  {t:>4}  {rev:>10.2f}  {boat.width:>5.1f}  {boat.length:>5.1f}  {boat.draft:>5.1f}")
            else:
                if X[i, j] == 1:
                    rev = berth.price_per_meter * boat.length
                    print(f"  {i:>5}  {j:>5}  {'--':>4}  {rev:>10.2f}  {boat.width:>5.1f}  {boat.length:>5.1f}  {boat.draft:>5.1f}")

    assigned = int(X.sum())
    print(f"\n  Assigned: {assigned} {'(berth,boat,day) slots' if is_temporal else 'boats'} out of {len(inst.boats)}")


def plot_marina_layout(
    inst: MarinaInstance,
    result: SolveResult,
    save_path: str | None = None,
) -> None:
    try:
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
    except ImportError:
        print("matplotlib not available; skipping plot.")
        return

    if result.assignment is None or result.assignment.ndim != 2:
        print("plot_marina_layout requires a static (2D) assignment.")
        return

    X = result.assignment
    colors = plt.cm.tab10.colors

    fig, ax = plt.subplots(figsize=(max(8, len(inst.berths) * 0.9), 6))
    for i, berth in enumerate(inst.berths):
        ax.add_patch(mpatches.Rectangle(
            (i, 0), 0.9, berth.length,
            linewidth=1.2, edgecolor="navy", facecolor="lightsteelblue", alpha=0.4,
        ))
        ax.text(i + 0.45, berth.length + 0.3, f"B{i}", ha="center", fontsize=7)

        for j, boat in enumerate(inst.boats):
            if X[i, j] == 1:
                color = colors[j % len(colors)]
                ax.add_patch(mpatches.Rectangle(
                    (i + 0.05, 0), 0.8, boat.length,
                    linewidth=1, edgecolor="black", facecolor=color, alpha=0.75,
                ))
                ax.text(i + 0.45, boat.length / 2, f"V{j}", ha="center", va="center", fontsize=8, fontweight="bold")

    ax.set_xlim(-0.2, len(inst.berths) + 0.2)
    ax.set_ylim(-1, max(b.length for b in inst.berths) + 2)
    ax.set_xlabel("Berth index")
    ax.set_ylabel("Length (m)")
    ax.set_title(f"Marina layout — {result.model_name}  revenue={result.objective_value:.0f}")
    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150)
        print(f"Saved layout plot to {save_path}")
    else:
        plt.show()
    plt.close()


def plot_temporal_gantt(
    inst: MarinaInstance,
    result: SolveResult,
    save_path: str | None = None,
) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not available; skipping plot.")
        return

    if result.assignment is None or result.assignment.ndim != 3:
        print("plot_temporal_gantt requires a temporal (3D) assignment.")
        return

    X = result.assignment
    n, m, T = X.shape
    colors = plt.cm.tab20.colors

    fig, ax = plt.subplots(figsize=(max(8, T * 0.8), max(4, n * 0.6)))

    for i in range(n):
        for j in range(m):
            days = [t for t in range(T) if X[i, j, t] == 1]
            if not days:
                continue
            for t in days:
                ax.broken_barh([(t, 1)], (i - 0.4, 0.8),
                               facecolors=colors[j % len(colors)],
                               edgecolors="black", linewidth=0.5)
                ax.text(t + 0.5, i, f"V{j}", ha="center", va="center", fontsize=7)

    ax.set_yticks(range(n))
    ax.set_yticklabels([f"Berth {i}" for i in range(n)])
    ax.set_xticks(range(T + 1))
    ax.set_xlabel("Day")
    ax.set_title(f"Temporal assignment — {result.model_name}  revenue={result.objective_value:.0f}")
    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150)
        print(f"Saved Gantt chart to {save_path}")
    else:
        plt.show()
    plt.close()


def plot_revenue_comparison(
    results: dict[str, SolveResult],
    save_path: str | None = None,
) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not available; skipping plot.")
        return

    labels = list(results.keys())
    values = [r.objective_value or 0.0 for r in results.values()]

    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 1.2), 5))
    bars = ax.bar(labels, values, color="steelblue", edgecolor="black")
    ax.bar_label(bars, fmt="%.0f", padding=3)
    ax.set_ylabel("Objective value (revenue)")
    ax.set_title("Revenue comparison across model variants")
    plt.xticks(rotation=25, ha="right")
    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=150)
        print(f"Saved comparison plot to {save_path}")
    else:
        plt.show()
    plt.close()
