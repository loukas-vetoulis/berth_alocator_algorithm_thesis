import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data_generator import make_hand_crafted_instance, generate_instance
from src.model_basic import solve_basic
from src.verifier import verify_solution
from src.visualizer import print_assignment_table, plot_marina_layout

print("=== Hand-crafted instance (known optimal = 3050) ===")
inst_hc = make_hand_crafted_instance()
result_hc = solve_basic(inst_hc)
print_assignment_table(inst_hc, result_hc)
report_hc = verify_solution(inst_hc, result_hc)
print(f"Verification: {'PASSED' if report_hc.passed else 'FAILED'}")
for v in report_hc.violations:
    print(f"  ! {v}")

print("\n=== Generated instance: 10 berths / 8 boats ===")
inst = generate_instance(n_berths=10, n_boats=8, seed=42)
result = solve_basic(inst)
print_assignment_table(inst, result)
report = verify_solution(inst, result)
print(f"Verification: {'PASSED' if report.passed else 'FAILED'}")
for v in report.violations:
    print(f"  ! {v}")

plot_marina_layout(inst, result,
    save_path=os.path.join(os.path.dirname(__file__), "..", "results", "basic_layout.png"))
