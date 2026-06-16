from __future__ import annotations
import time
from dataclasses import dataclass, field
import numpy as np
from ..core.data_model import MarinaInstance, SolveResult
from ..core.revenue import consumed_width
from .baselines import boat_fits_berth, gross_revenue, _stay_window


@dataclass
class OnlineMetrics:
    """Outcome of an online simulation, alongside the returned SolveResult."""
    num_requests: int
    num_assigned: int
    num_rejected: int
    rejected_boat_ids: list[int]
    realized_revenue: float
    assignment_rate: float
    competitive_ratio: float | None = None  # realized / offline optimum (filled by caller)


def arrival_order(
    inst: MarinaInstance,
    seed: int = 0,
    mode: str = "by_arrival",
    boat_indices: list[int] | None = None,
) -> list[int]:
    """Order in which requests arrive.

    "by_arrival" sorts by arrival_day with a deterministic random tie-break;
    "shuffle" returns a full random permutation. Restrict to ``boat_indices``
    when some boats (e.g. VIP contracts) are handled separately.
    """
    rng = np.random.default_rng(seed)
    idx = list(range(len(inst.boats))) if boat_indices is None else list(boat_indices)
    if mode == "shuffle":
        perm = rng.permutation(len(idx))
        return [idx[k] for k in perm]
    tiebreak = {j: rng.random() for j in idx}
    return sorted(idx, key=lambda j: (inst.boats[j].arrival_day, tiebreak[j]))


def simulate_online(
    inst: MarinaInstance,
    policy: str = "best_fit",
    seed: int = 0,
    order_mode: str = "by_arrival",
    use_compat: bool = True,
    use_utility: bool = True,
    use_vip: bool = True,
    side_by_side: bool = False,
) -> tuple[SolveResult, OnlineMetrics]:
    """Simulate online (sequential) arrivals with irrevocable decisions.

    Requests arrive one-by-one in ``arrival_order``; each is placed immediately
    with no knowledge of future requests (or rejected if no berth is free for
    its whole stay), and the decision is never undone. VIP contracts are treated
    as known reservations and committed up front. The natural comparison point
    is the offline MILP optimum (``solve_final``) on the full instance, which
    quantifies the value of knowing the future.

    Note: online ``revenue_priority`` is identical to ``best_fit`` because future
    requests cannot be reordered; it is accepted for convenience.
    """
    t0 = time.perf_counter()
    n, m = len(inst.berths), len(inst.boats)
    T = max(inst.n_days, 1)
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

    def commit(i: int, j: int, days: range) -> None:
        for t in days:
            X[i, j, t] = 1
            count[i, t] += 1
            used_width[i, t] += cons[j]

    def pick(j: int, days: range) -> int | None:
        candidates = [i for i in range(n) if can_place(i, j, days)]
        if not candidates:
            return None
        if policy == "first_fit":
            return candidates[0]
        # best_fit (and revenue_priority, which degenerates to best_fit online)
        return min(candidates, key=lambda i: (inst.berths[i].length, i))

    # VIP contracts are known reservations: commit them before streaming walk-ins.
    vip_boats = [j for j in range(m) if use_vip and inst.boats[j].contract_berth_id is not None]
    for j in vip_boats:
        days = _stay_window(inst, j, T)
        i_vip = inst.boats[j].contract_berth_id
        if can_place(i_vip, j, days):
            commit(i_vip, j, days)

    stream = arrival_order(
        inst, seed=seed, mode=order_mode,
        boat_indices=[j for j in range(m) if j not in set(vip_boats)],
    )
    for j in stream:
        days = _stay_window(inst, j, T)
        chosen = pick(j, days)
        if chosen is not None:
            commit(chosen, j, days)

    assignment = X if inst.n_days > 1 else X[:, :, 0]
    revenue = gross_revenue(inst, assignment)
    elapsed = time.perf_counter() - t0

    assigned_mask = [int(X[:, j, :].sum()) > 0 for j in range(m)]
    n_assigned = int(sum(assigned_mask))
    rejected_ids = [j for j in range(m) if not assigned_mask[j]]

    result = SolveResult(
        status="online",
        objective_value=revenue,
        assignment=assignment,
        solve_time=elapsed,
        model_name=f"online[{policy}]",
        penalty_value=0.0,
    )
    metrics = OnlineMetrics(
        num_requests=m,
        num_assigned=n_assigned,
        num_rejected=m - n_assigned,
        rejected_boat_ids=rejected_ids,
        realized_revenue=revenue,
        assignment_rate=(n_assigned / m if m else 0.0),
        competitive_ratio=None,
    )
    return result, metrics
