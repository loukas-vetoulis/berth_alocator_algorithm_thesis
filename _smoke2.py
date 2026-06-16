"""Temporary smoke test for the Phase-3b features: alongside mooring,
multi-berth spanning, split/relocation, plus a regression check."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from src.core.data_generator import (
    generate_instance, make_multiberth_demo_instance, make_alongside_demo_instance,
)
from src.core.data_model import Berth, Boat, MarinaInstance
from src.core.data_generator import build_compat_matrix
from src.models.model_final import solve_final
from src.heuristics.baselines import first_fit, best_fit, gross_revenue
from src.core.verifier import verify_solution


def served(result):
    X = result.assignment
    if X is None: return 0
    if X.ndim == 2: return int(np.sum(X.sum(axis=0) > 0))
    return int(np.sum(X.sum(axis=(0, 2)) > 0))


def chk(name, inst, result):
    rep = verify_solution(inst, result)
    tag = "OK " if rep.passed else "FAIL"
    print(f"  [{tag}] {name:42s} obj={result.objective_value:>9.1f} "
          f"gross={gross_revenue(inst, result.assignment):>9.1f} served={served(result)}")
    if not rep.passed:
        for v in rep.violations[:4]:
            print("        -", v)
    return rep.passed

ok = True
print("=== Regression: generated temporal instance (no new features) ===")
inst = generate_instance(n_berths=6, n_boats=10, seed=3, n_days=7)
ok &= chk("final base", inst, solve_final(inst))
ok &= chk("final side-by-side", inst, solve_final(inst, side_by_side=True))
ok &= chk("final soft-depth", inst, solve_final(inst, soft_depth=True))
ok &= chk("final relocation", inst, solve_final(inst, allow_relocation=True))

print("\n=== Multi-berth spanning demo (boat 0 too wide for any single berth) ===")
mb = make_multiberth_demo_instance(n_days=4)
no_span = solve_final(mb, allow_multi_berth=False)
span = solve_final(mb, allow_multi_berth=True)
ok &= chk("no multi-berth (wide boat rejected)", mb, no_span)
ok &= chk("multi-berth (wide boat spans pair)", mb, span)
# Inspect boat 0 occupancy under spanning.
X = span.assignment
b0_berths = sorted({i for i in range(len(mb.berths)) for t in range(mb.n_days) if X[i, 0, t] == 1})
print(f"    boat 0 occupies berths {b0_berths} (expect an adjacent pair); "
      f"served no_span={served(no_span)} span={served(span)}")

print("\n=== Alongside mooring demo (boats 6,7 request alongside) ===")
al = make_alongside_demo_instance(n_days=3)
r_al = solve_final(al, side_by_side=True)
ok &= chk("alongside side-by-side", al, r_al)
# Compare revenue if those same boats were stern-to.
al2 = make_alongside_demo_instance(n_days=3)
for b in al2.boats:
    b.mooring_type = "stern_to"
r_stern = solve_final(al2, side_by_side=True)
print(f"    revenue with alongside requests = {gross_revenue(al, r_al.assignment):.1f}; "
      f"all stern-to = {gross_revenue(al2, r_stern.assignment):.1f} "
      f"(alongside pays the +60% premium but hogs width)")

print("\n=== Split berth via relocation (no single berth free for the whole stay) ===")
berths = [Berth(id=i, width=5.0, length=20.0, depth=3.0, price_per_meter=100.0,
                berth_type="standard", max_boats=1) for i in range(2)]
boats = [
    Boat(id=0, width=3.0, length=10.0, draft=1.5, boat_type="sailboat",
         contract_berth_id=0, arrival_day=0, departure_day=2),   # holds berth 0 days 0-1
    Boat(id=1, width=3.0, length=10.0, draft=1.5, boat_type="sailboat",
         contract_berth_id=1, arrival_day=2, departure_day=4),   # holds berth 1 days 2-3
    Boat(id=2, width=3.0, length=10.0, draft=1.5, boat_type="sailboat",
         arrival_day=0, departure_day=4),                        # needs the whole window
]
compat = build_compat_matrix(berths, boats)
split_inst = MarinaInstance(berths=berths, boats=boats, compat_matrix=compat, n_days=4)
r_stable = solve_final(split_inst, allow_relocation=False)
r_reloc = solve_final(split_inst, allow_relocation=True, max_relocations=1)
ok &= chk("stable (boat 2 cannot fit one berth)", split_inst, r_stable)
ok &= chk("relocation (boat 2 splits across berths)", split_inst, r_reloc)
Xr = r_reloc.assignment
b2 = [(t, i) for t in range(split_inst.n_days) for i in range(2) if Xr[i, 2, t] == 1]
print(f"    boat 2 schedule (day,berth) under relocation: {b2}  served stable={served(r_stable)} reloc={served(r_reloc)}")

print(f"\nALL VERIFY OK: {ok}")
