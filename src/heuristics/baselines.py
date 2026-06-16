from __future__ import annotations
import time
import numpy as np
from ..core.data_model import MarinaInstance, SolveResult
from ..core.revenue import realized_revenue, consumed_width, ALONGSIDE_PREMIUM, is_alongside


def gross_revenue(inst: MarinaInstance, assignment: np.ndarray | None) -> float:
    """Realised gross revenue of an assignment (2D or 3D), undiscounted.

    This is the common metric for comparing the MILP, greedy and online methods
    (the MILP's ``objective_value`` is net of penalties). It accounts for the
    alongside and multi-berth premiums via core.revenue.
    """
    return realized_revenue(inst, assignment)


def boat_fits_berth(
    inst: MarinaInstance,
    i: int,
    j: int,
    use_compat: bool = True,
    use_utility: bool = True,
    use_vip: bool = True,
) -> bool:
    """Single source of truth for whether boat j may occupy berth i.

    Mirrors the final model's feasibility rules: physical fit (width, length,
    draft), compatibility, shore power, and VIP contracts. A VIP boat fits only
    its contract berth, and on that berth the power restriction is overridden
    (the berth is reserved and provisioned for the contracted boat).
    """
    berth = inst.berths[i]
    boat = inst.boats[j]
    if boat.width > berth.width or boat.length > berth.length or boat.draft > berth.depth:
        return False
    is_contract_berth = use_vip and boat.contract_berth_id == i
    if use_vip and boat.contract_berth_id is not None and boat.contract_berth_id != i:
        return False
    if use_compat and inst.compat_matrix is not None and inst.compat_matrix[i, j] == 0:
        if not is_contract_berth:
            return False
    if use_utility and boat.power_required_kw > berth.power_capacity_kw:
        if not is_contract_berth:
            return False
    return True


def _stay_window(inst: MarinaInstance, j: int, T: int) -> range:
    boat = inst.boats[j]
    arr = max(0, boat.arrival_day)
    dep = min(boat.departure_day, T)
    if dep <= arr:
        dep = arr + 1
    return range(arr, min(dep, T))


def _revenue_order(
    inst: MarinaInstance,
    use_compat: bool,
    use_utility: bool,
    use_vip: bool,
) -> list[int]:
    """Boats sorted by maximum achievable revenue (descending).

    Revenue depends on the berth, so the ranking uses each boat's best-case
    value: length * max price over all berths the boat could feasibly occupy.
    """
    proxies = []
    for j, boat in enumerate(inst.boats):
        feas_prices = [
            inst.berths[i].price_per_meter
            for i in range(len(inst.berths))
            if boat_fits_berth(inst, i, j, use_compat, use_utility, use_vip)
        ]
        prem = (1.0 + ALONGSIDE_PREMIUM) if is_alongside(boat) else 1.0
        proxies.append(boat.length * max(feas_prices) * prem if feas_prices else 0.0)
    return sorted(range(len(inst.boats)), key=lambda j: proxies[j], reverse=True)


def greedy_allocate(
    inst: MarinaInstance,
    policy: str = "first_fit",
    placement: str = "best_fit",
    boat_order: list[int] | None = None,
    use_compat: bool = True,
    use_utility: bool = True,
    use_vip: bool = True,
    side_by_side: bool = False,
) -> SolveResult:
    """Offline greedy allocator (stable, no relocation).

    ``policy`` selects both the boat processing order and the berth-selection
    rule:
      - "first_fit":        natural order, place in the first fitting free berth.
      - "best_fit":         natural order, place in the smallest fitting free berth.
      - "revenue_priority": highest-value boats first, placed by ``placement``
                            ("best_fit" by default, "first_fit" for ablation).

    Returns a SolveResult with a 3D assignment when n_days > 1, else 2D, so the
    verifier and visualizer work unchanged. ``objective_value`` is the realised
    gross revenue; ``penalty_value`` is 0.
    """
    t0 = time.perf_counter()
    n, m = len(inst.berths), len(inst.boats)
    T = max(inst.n_days, 1)

    if policy == "first_fit":
        selection = "first_fit"
        order = list(boat_order) if boat_order is not None else list(range(m))
    elif policy == "best_fit":
        selection = "best_fit"
        order = list(boat_order) if boat_order is not None else list(range(m))
    elif policy == "revenue_priority":
        selection = placement
        order = list(boat_order) if boat_order is not None else _revenue_order(
            inst, use_compat, use_utility, use_vip)
    else:
        raise ValueError(f"Unknown greedy policy: {policy!r}")

    # VIP boats first so they secure their contract berths (stable sort keeps
    # the chosen order among non-VIP boats).
    order = sorted(
        order,
        key=lambda j: 0 if (use_vip and inst.boats[j].contract_berth_id is not None) else 1,
    )

    cons = consumed_width(inst)  # length for alongside boats, else beam
    count = np.zeros((n, T), dtype=int)
    used_width = np.zeros((n, T), dtype=float)
    X = np.zeros((n, m, T), dtype=int)

    def can_place(i: int, j: int, days: range) -> bool:
        if not boat_fits_berth(inst, i, j, use_compat, use_utility, use_vip):
            return False
        for t in days:
            if not side_by_side and count[i, t] >= 1:
                return False
            if side_by_side and used_width[i, t] + cons[j] > inst.berths[i].width + 1e-9:
                return False
        return True

    for j in order:
        days = _stay_window(inst, j, T)
        candidates = [i for i in range(n) if can_place(i, j, days)]
        if not candidates:
            continue
        if selection == "best_fit":
            chosen = min(candidates, key=lambda i: (inst.berths[i].length, i))
        else:  # first_fit
            chosen = candidates[0]
        for t in days:
            X[chosen, j, t] = 1
            count[chosen, t] += 1
            used_width[chosen, t] += cons[j]

    assignment = X if inst.n_days > 1 else X[:, :, 0]
    revenue = gross_revenue(inst, assignment)
    elapsed = time.perf_counter() - t0

    return SolveResult(
        status="heuristic",
        objective_value=revenue,
        assignment=assignment,
        solve_time=elapsed,
        model_name=f"greedy[{policy}]",
        penalty_value=0.0,
    )


def first_fit(inst: MarinaInstance, **kwargs) -> SolveResult:
    return greedy_allocate(inst, policy="first_fit", **kwargs)


def best_fit(inst: MarinaInstance, **kwargs) -> SolveResult:
    return greedy_allocate(inst, policy="best_fit", **kwargs)


def revenue_priority(inst: MarinaInstance, placement: str = "best_fit", **kwargs) -> SolveResult:
    return greedy_allocate(inst, policy="revenue_priority", placement=placement, **kwargs)
