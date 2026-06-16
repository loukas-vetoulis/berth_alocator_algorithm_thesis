"""
Phase 3 feature demonstrations: multi-berth spanning, alongside mooring
(plagiodetisi), and split-berth via relocation.

Each demo uses a small hand-crafted instance where the feature clearly triggers,
prints the outcome, and verifies the solution. Two Gantt charts are saved.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.data_generator import (
    make_multiberth_demo_instance, make_alongside_demo_instance, build_compat_matrix,
)
from src.core.data_model import Berth, Boat, MarinaInstance
from src.models.model_final import solve_final
from src.heuristics.baselines import gross_revenue
from src.core.verifier import verify_solution
from src.core.visualizer import plot_temporal_gantt

RESULTS = os.path.join(os.path.dirname(__file__), "..", "results")


def served(result):
    X = result.assignment
    if X is None:
        return 0
    return int((X.sum(axis=(0, 2)) > 0).sum()) if X.ndim == 3 else int((X.sum(axis=0) > 0).sum())


def show(name, inst, result):
    rep = verify_solution(inst, result)
    print(f"  [{'OK' if rep.passed else 'FAIL'}] {name:38s} "
          f"revenue={gross_revenue(inst, result.assignment):>8.0f}  served={served(result)}/{len(inst.boats)}")
    for v in rep.violations[:3]:
        print("        -", v)
    return rep.passed


def main():
    print("=" * 70)
    print("1. MULTI-BERTH SPANNING (one boat too wide for any single berth)")
    print("=" * 70)
    mb = make_multiberth_demo_instance(n_days=4)
    print(f"  Boat 0 beam = {mb.boats[0].width} m; every berth is {mb.berths[0].width} m wide.")
    off = solve_final(mb, allow_multi_berth=False)
    on = solve_final(mb, allow_multi_berth=True)
    show("multi-berth OFF (boat 0 rejected)", mb, off)
    show("multi-berth ON  (boat 0 spans a pair)", mb, on)
    X = on.assignment
    pair = sorted({i for i in range(len(mb.berths)) for t in range(mb.n_days) if X[i, 0, t] == 1})
    print(f"  -> boat 0 spans adjacent berths {pair}; revenue {gross_revenue(mb, off.assignment):.0f}"
          f" -> {gross_revenue(mb, on.assignment):.0f} (+25% span premium on the wide boat).")
    plot_temporal_gantt(mb, on, save_path=os.path.join(RESULTS, "final_multiberth_gantt.png"))

    print("\n" + "=" * 70)
    print("2. ALONGSIDE MOORING / PLAGIODETISI (length consumes the width budget)")
    print("=" * 70)
    al = make_alongside_demo_instance(n_days=3)
    along = [b.id for b in al.boats if b.mooring_type == "alongside"]
    print(f"  Boats {along} request alongside; each consumes its {al.boats[along[0]].length} m length"
          f" of the {al.berths[0].width} m width budget instead of its {al.boats[along[0]].width} m beam.")
    r_al = solve_final(al, side_by_side=True)
    show("alongside requests (side-by-side)", al, r_al)
    al2 = make_alongside_demo_instance(n_days=3)
    for b in al2.boats:
        b.mooring_type = "stern_to"
    r_st = solve_final(al2, side_by_side=True)
    show("same boats all stern-to", al2, r_st)
    print(f"  -> alongside boats pay the +60% premium but hog width, so total served/revenue falls:"
          f" {gross_revenue(al2, r_st.assignment):.0f} (stern-to) vs {gross_revenue(al, r_al.assignment):.0f} (alongside).")

    print("\n" + "=" * 70)
    print("3. SPLIT BERTH VIA RELOCATION (no single berth free for the whole stay)")
    print("=" * 70)
    berths = [Berth(id=i, width=5.0, length=20.0, depth=3.0, price_per_meter=100.0,
                    berth_type="standard", max_boats=1) for i in range(2)]
    boats = [
        Boat(id=0, width=3.0, length=10.0, draft=1.5, boat_type="sailboat",
             contract_berth_id=0, arrival_day=0, departure_day=2),
        Boat(id=1, width=3.0, length=10.0, draft=1.5, boat_type="sailboat",
             contract_berth_id=1, arrival_day=2, departure_day=4),
        Boat(id=2, width=3.0, length=10.0, draft=1.5, boat_type="sailboat",
             arrival_day=0, departure_day=4),
    ]
    inst = MarinaInstance(berths=berths, boats=boats,
                          compat_matrix=build_compat_matrix(berths, boats), n_days=4)
    stable = solve_final(inst, allow_relocation=False)
    reloc = solve_final(inst, allow_relocation=True, max_relocations=1)
    show("stable (boat 2 cannot fit one berth)", inst, stable)
    show("relocation (boat 2 splits berths)", inst, reloc)
    Xr = reloc.assignment
    sched = [(t, i) for t in range(inst.n_days) for i in range(2) if Xr[i, 2, t] == 1]
    print(f"  -> boat 2 schedule (day, berth): {sched}  (served {served(stable)} -> {served(reloc)} boats).")
    plot_temporal_gantt(inst, reloc, save_path=os.path.join(RESULTS, "final_split_gantt.png"))

    print("\nDone. Gantt charts: results/final_multiberth_gantt.png, results/final_split_gantt.png")


if __name__ == "__main__":
    main()
