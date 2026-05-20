import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data_generator import generate_instance
from src.model_temporal import solve_temporal
from src.verifier import verify_solution
from src.visualizer import print_assignment_table, plot_temporal_gantt, plot_revenue_comparison

inst = generate_instance(n_berths=10, n_boats=15, seed=7, n_days=7)

print("=== Temporal model: stable (no relocation) ===")
r_stable = solve_temporal(inst, allow_relocation=False)
print_assignment_table(inst, r_stable)
rep = verify_solution(inst, r_stable)
print(f"Verification: {'PASSED' if rep.passed else 'FAILED'}")
for v in rep.violations[:5]:
    print(f"  ! {v}")

print("\n=== Temporal model: with relocation (max 1) ===")
r_reloc = solve_temporal(inst, allow_relocation=True, max_relocations=1)
print_assignment_table(inst, r_reloc)
rep2 = verify_solution(inst, r_reloc)
print(f"Verification: {'PASSED' if rep2.passed else 'FAILED'}")
for v in rep2.violations[:5]:
    print(f"  ! {v}")

print("\n=== Temporal model: with gap discount (delta=0.1) ===")
r_gap = solve_temporal(inst, allow_relocation=True, max_relocations=1, gap_discount_rate=0.1)
print_assignment_table(inst, r_gap)

results = {
    "temporal stable":    r_stable,
    "temporal reloc":     r_reloc,
    "temporal gap 0.1":   r_gap,
}
plot_temporal_gantt(
    inst, r_stable,
    save_path=os.path.join(os.path.dirname(__file__), "..", "results", "gantt_stable.png"),
)
plot_temporal_gantt(
    inst, r_reloc,
    save_path=os.path.join(os.path.dirname(__file__), "..", "results", "gantt_reloc.png"),
)
plot_revenue_comparison(
    results,
    save_path=os.path.join(os.path.dirname(__file__), "..", "results", "temporal_comparison.png"),
)
