import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data_generator import generate_instance
from src.model_basic import solve_basic
from src.model_extensions import solve_extended
from src.verifier import verify_solution
from src.visualizer import print_assignment_table, plot_revenue_comparison

inst = generate_instance(n_berths=10, n_boats=8, seed=42)

configs = {
    "basic":            dict(mode="basic"),
    "compat":           dict(use_compat=True,  use_utility=False, use_vip=False),
    "utility":          dict(use_compat=False, use_utility=True,  use_vip=False),
    "vip":              dict(use_compat=False, use_utility=False, use_vip=True),
    "compat+utility":   dict(use_compat=True,  use_utility=True,  use_vip=False),
    "all":              dict(use_compat=True,  use_utility=True,  use_vip=True),
    "sbs":              dict(use_compat=False, use_utility=False, use_vip=False, side_by_side=True),
    "all+sbs":          dict(use_compat=True,  use_utility=True,  use_vip=True,  side_by_side=True),
    "soft(M=1000)":     dict(use_compat=True,  use_utility=True,  use_vip=True,  soft_depth=True, penalty_M=1000.0),
    "soft(M=0)":        dict(use_compat=False, use_utility=False, use_vip=False, soft_depth=True, penalty_M=0.0),
}

results = {}
for name, cfg in configs.items():
    if name == "basic":
        r = solve_basic(inst)
    else:
        r = solve_extended(inst, **cfg)
    results[name] = r
    report = verify_solution(inst, r)
    ok = "OK" if report.passed else "FAIL"
    print(f"{name:20s}  revenue={r.objective_value or 0:.2f}  [{ok}]  {r.solve_time:.3f}s")
    if not report.passed:
        for v in report.violations[:3]:
            print(f"    ! {v}")

plot_revenue_comparison(
    results,
    save_path=os.path.join(os.path.dirname(__file__), "..", "results", "extensions_comparison.png"),
)
