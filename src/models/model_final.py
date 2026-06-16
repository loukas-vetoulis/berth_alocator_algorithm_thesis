from __future__ import annotations
import os
import time

# Cap BLAS threads before NumPy loads (avoids OpenBLAS OOM on Windows with CVXPY 3D tensors).
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np
import cvxpy as cp
from ..core.data_model import MarinaInstance, SolveResult
from ..core.revenue import (
    single_revenue_matrix, span_revenue_matrix, consumed_width, realized_revenue,
)


def build_waste_length_matrix(inst: MarinaInstance) -> np.ndarray:
    """Wasted berth length (metres) if boat j is moored in berth i.

    waste[i, j] = max(0, berth.length - boat.length)

    Used both as an interpretable metric (total unused metres) and as the basis
    for the smallest-berth penalty. Infeasible pairs are irrelevant because the
    constraint ``x <= F3`` already forces those variables to zero.
    """
    n, m = len(inst.berths), len(inst.boats)
    W = np.zeros((n, m), dtype=float)
    for i, berth in enumerate(inst.berths):
        for j, boat in enumerate(inst.boats):
            W[i, j] = max(0.0, berth.length - boat.length)
    return W


def build_final_feasibility_mask(
    inst: MarinaInstance,
    soft_depth: bool,
    use_compat: bool,
    use_utility: bool,
    use_vip: bool,
) -> np.ndarray:
    """3D feasibility / time-window mask F3[i, j, t] for the final model.

    Combines physical fit (width, length, and depth unless ``soft_depth``),
    arrival/departure windows, compatibility and shore-power capacity. When
    ``soft_depth`` is on, the draft test is dropped from the mask so that the
    soft-depth slack variable can absorb depth shortfalls in the objective.

    VIP contracts are a hard reservation: a boat with a ``contract_berth_id`` is
    allowed only on its contract berth, and the shore-power capacity restriction
    does not block it there (the berth is reserved and provisioned for that
    boat). Compatibility and physical fit on the contract berth are guaranteed
    by the data generator, so they need no special handling.
    """
    n, m, T = len(inst.berths), len(inst.boats), inst.n_days
    F3 = np.zeros((n, m, T), dtype=float)
    for i, berth in enumerate(inst.berths):
        for j, boat in enumerate(inst.boats):
            if boat.width > berth.width or boat.length > berth.length:
                continue
            if not soft_depth and boat.draft > berth.depth:
                continue
            for t in range(boat.arrival_day, boat.departure_day):
                if 0 <= t < T:
                    F3[i, j, t] = 1.0

    if use_compat and inst.compat_matrix is not None:
        F3 = F3 * (inst.compat_matrix[:, :, np.newaxis] * np.ones(T))

    if use_utility:
        for i, berth in enumerate(inst.berths):
            for j, boat in enumerate(inst.boats):
                if boat.power_required_kw > berth.power_capacity_kw:
                    # A VIP contract berth overrides the power restriction.
                    if use_vip and boat.contract_berth_id == i:
                        continue
                    F3[i, j, :] = 0.0

    if use_vip:
        for j, boat in enumerate(inst.boats):
            if boat.contract_berth_id is None:
                continue
            i_vip = boat.contract_berth_id
            for i in range(n):
                if i != i_vip:
                    F3[i, j, :] = 0.0
    return F3


def build_span_mask(
    inst: MarinaInstance, use_compat: bool, use_utility: bool, use_vip: bool,
) -> np.ndarray:
    """Zmask[k, j, t] = 1 if boat j may span the adjacent pair (k, k+1) on day t.

    Spanning requires the boat to fit the combined width and the shorter of the
    two berths' length/depth, and (if enabled) to be compatible and powered on
    BOTH berths. VIP-contracted boats never span (they are pinned).
    """
    n, m, T = len(inst.berths), len(inst.boats), inst.n_days
    Z = np.zeros((max(n - 1, 0), m, T), dtype=float)
    for k in range(n - 1):
        b0, b1 = inst.berths[k], inst.berths[k + 1]
        comb_width = b0.width + b1.width
        comb_len = min(b0.length, b1.length)
        comb_depth = min(b0.depth, b1.depth)
        for j, boat in enumerate(inst.boats):
            if use_vip and boat.contract_berth_id is not None:
                continue
            if not (boat.width <= comb_width and boat.length <= comb_len and boat.draft <= comb_depth):
                continue
            if use_compat and inst.compat_matrix is not None:
                if inst.compat_matrix[k, j] == 0 or inst.compat_matrix[k + 1, j] == 0:
                    continue
            if use_utility and (boat.power_required_kw > b0.power_capacity_kw
                                or boat.power_required_kw > b1.power_capacity_kw):
                continue
            for t in range(boat.arrival_day, boat.departure_day):
                if 0 <= t < T:
                    Z[k, j, t] = 1.0
    return Z


def _berth_fits_boat_hard(
    inst: MarinaInstance,
    i: int,
    j: int,
    use_compat: bool,
    use_utility: bool,
    use_vip: bool,
) -> bool:
    """Hard physical/business fit (no soft-depth slack) for smallest-berth ranking."""
    berth = inst.berths[i]
    boat = inst.boats[j]
    if boat.width > berth.width or boat.length > berth.length or boat.draft > berth.depth:
        return False
    on_contract = use_vip and boat.contract_berth_id == i
    if use_vip and boat.contract_berth_id is not None and boat.contract_berth_id != i:
        return False
    if use_compat and inst.compat_matrix is not None and inst.compat_matrix[i, j] == 0:
        if not on_contract:
            return False
    if use_utility and boat.power_required_kw > berth.power_capacity_kw:
        if not on_contract:
            return False
    return True


def _add_smallest_berth_constraints(
    constraints: list,
    x: cp.Variable,
    inst: MarinaInstance,
    T: int,
    n: int,
    m: int,
    use_compat: bool,
    use_utility: bool,
    use_vip: bool,
    allow_relocation: bool,
) -> None:
    """Hard rule: on each day, boat j in berth i only if every smaller fitting berth is occupied.

    Matches marina practice and the greedy best-fit heuristic. VIP-contracted boats
    are exempt (pinned berth). ``allow_relocation`` is accepted for API symmetry; the
    rule is enforced per day in all modes.
    """
    del allow_relocation, m
    for j, boat in enumerate(inst.boats):
        if use_vip and boat.contract_berth_id is not None:
            continue
        stay = list(range(max(0, boat.arrival_day), min(boat.departure_day, T)))
        if not stay:
            continue
        fitting = [i for i in range(n) if _berth_fits_boat_hard(inst, i, j, use_compat, use_utility, use_vip)]
        for k in fitting:
            lk = inst.berths[k].length
            for i in fitting:
                if i == k or inst.berths[i].length <= lk:
                    continue
                for t in stay:
                    occ_k = cp.sum(x[k, :, t])
                    constraints.append(x[i, j, t] <= occ_k)


def build_final_model(
    inst: MarinaInstance,
    use_compat: bool = True,
    use_utility: bool = True,
    use_vip: bool = True,
    side_by_side: bool = False,
    soft_depth: bool = False,
    penalty_M: float = 1000.0,
    allow_relocation: bool = False,
    max_relocations: int = 1,
    gap_discount_rate: float = 0.0,
    short_stay_discount: float = 0.0,
    min_stay_days: int = 5,
    space_weight: float = 0.0,
    allow_multi_berth: bool = False,
    enforce_smallest_berth: bool = False,
) -> tuple[cp.Problem, cp.Variable, dict]:
    """Build the unified final model.

    A single temporal MILP (3D x[i, j, t]) combining every extension:
    compatibility, shore power, VIP contracts, side-by-side berthing, soft-depth,
    relocation/stable assignment, gap and short-stay discounts, the smallest-berth
    penalty, alongside mooring (per boat, via the revenue/width helpers), and
    optional multi-berth spanning (z[k, j, t] for the adjacent pair (k, k+1)).

    Returns (problem, x, aux) where aux carries optional variables
    {"r_var", "slack", "gap", "z"} (any may be None).
    """
    n, m, T = len(inst.berths), len(inst.boats), inst.n_days

    x = cp.Variable((n, m, T), boolean=True)
    aux: dict = {"r_var": None, "slack": None, "gap": None, "z": None}

    F3 = build_final_feasibility_mask(inst, soft_depth, use_compat, use_utility, use_vip)
    constraints: list = [x <= F3]

    # Multi-berth spanning variables (oversized boats take two adjacent berths).
    z = None
    span_revenue: cp.Expression | float = 0.0
    use_span = allow_multi_berth and n >= 2
    if use_span:
        Zmask = build_span_mask(inst, use_compat, use_utility, use_vip)
        z = cp.Variable((n - 1, m, T), boolean=True)
        aux["z"] = z
        constraints.append(z <= Zmask)

    # One assignment per boat per day: at most one single berth OR one span.
    for j in range(m):
        for t in range(T):
            lhs = cp.sum(x[:, j, t])
            if use_span:
                lhs = lhs + cp.sum(z[:, j, t])
            constraints.append(lhs <= 1)

    consumed = consumed_width(inst)  # length for alongside boats, else beam

    def span_use(i: int, t: int):
        """Spanning occupancy of berth i on day t (0/1 expression), or 0."""
        if not use_span:
            return 0
        terms = []
        if i <= n - 2:
            terms.append(cp.sum(z[i, :, t]))      # pair starting at i
        if i >= 1:
            terms.append(cp.sum(z[i - 1, :, t]))  # pair ending at i
        return cp.sum(terms) if terms else 0

    # Per-berth, per-day capacity. A spanning boat consumes the whole berth.
    if side_by_side:
        for i, berth in enumerate(inst.berths):
            for t in range(T):
                constraints.append(
                    cp.sum(cp.multiply(consumed, x[i, :, t])) + berth.width * span_use(i, t)
                    <= berth.width)
                # No max_boats cap: only the shared width budget limits how many fit.
    else:
        for i in range(n):
            for t in range(T):
                constraints.append(cp.sum(x[i, :, t]) + span_use(i, t) <= 1)

    # VIP pins: force occupancy of the contract berth across the stay window.
    if use_vip:
        for j, boat in enumerate(inst.boats):
            if boat.contract_berth_id is None:
                continue
            i_vip = boat.contract_berth_id
            for t in range(boat.arrival_day, min(boat.departure_day, T)):
                if 0 <= t < T:
                    constraints.append(x[i_vip, j, t] == 1)

    # Smallest fitting berth (hard): cannot skip an empty smaller berth for the stay.
    if enforce_smallest_berth:
        _add_smallest_berth_constraints(
            constraints, x, inst, T, n, m, use_compat, use_utility, use_vip, allow_relocation,
        )

    # Revenue tensor (per day). single_revenue_matrix folds in the alongside
    # premium; the short-stay discount lowers the per-slot price for short stays.
    R = single_revenue_matrix(inst)
    R3 = R[:, :, np.newaxis] * np.ones(T)
    if short_stay_discount > 0.0:
        for j, boat in enumerate(inst.boats):
            if (boat.departure_day - boat.arrival_day) < min_stay_days:
                R3[:, j, :] *= (1.0 - short_stay_discount)

    if use_span:
        Rspan = span_revenue_matrix(inst)
        Rspan3 = Rspan[:, :, np.newaxis] * np.ones(T)
        if short_stay_discount > 0.0:
            for j, boat in enumerate(inst.boats):
                if (boat.departure_day - boat.arrival_day) < min_stay_days:
                    Rspan3[:, j, :] *= (1.0 - short_stay_discount)
        span_revenue = cp.sum(cp.multiply(Rspan3, z))
        # Spanning boats keep their pair for the whole stay (stable spans).
        for j, boat in enumerate(inst.boats):
            for t in range(boat.arrival_day, min(boat.departure_day - 1, T - 1)):
                for k in range(n - 1):
                    constraints.append(z[k, j, t] == z[k, j, t + 1])

    # Relocation (allow moves at a per-move cost) vs stable (fixed berth for stay).
    reloc_penalty: cp.Expression | float = 0.0
    if allow_relocation and T > 1:
        r_var = cp.Variable((m, T - 1), boolean=True)
        aux["r_var"] = r_var
        reloc_costs = np.array([b.relocation_cost for b in inst.boats])
        for j, boat in enumerate(inst.boats):
            # Only count berth changes *within* the stay window; arrival and
            # departure at the window edges are not relocations.
            for t in range(boat.arrival_day, min(boat.departure_day - 1, T - 1)):
                constraints.append(cp.sum(x[:, j, t]) == cp.sum(x[:, j, t + 1]))
                for i in range(n):
                    constraints.append(x[i, j, t] - x[i, j, t + 1] <= r_var[j, t])
                    constraints.append(x[i, j, t + 1] - x[i, j, t] <= r_var[j, t])
            constraints.append(cp.sum(r_var[j, :]) <= max_relocations)
        reloc_penalty = cp.sum(cp.multiply(
            reloc_costs.reshape(-1, 1) * np.ones((m, T - 1)),
            r_var,
        ))
    else:
        for j, boat in enumerate(inst.boats):
            for t in range(boat.arrival_day, min(boat.departure_day - 1, T - 1)):
                for i in range(n):
                    constraints.append(x[i, j, t] == x[i, j, t + 1])

    # Gap penalty: discourage a boat from vacating a berth and leaving a hole.
    gap_penalty: cp.Expression | float = 0.0
    if gap_discount_rate > 0.0 and T > 1:
        p = np.array([b.price_per_meter for b in inst.berths])
        l = np.array([b.length for b in inst.boats])
        avg_revenue_per_day = float(np.mean(p) * np.mean(l))
        gap = cp.Variable((m, T - 1), nonneg=True)
        aux["gap"] = gap
        for j in range(m):
            for t in range(1, T):
                constraints.append(gap[j, t - 1] >= cp.sum(x[:, j, t - 1]) - cp.sum(x[:, j, t]))
        gap_penalty = gap_discount_rate * avg_revenue_per_day * cp.sum(gap)

    # Soft depth: allow a boat too deep for a berth at a steep penalty.
    depth_penalty: cp.Expression | float = 0.0
    if soft_depth:
        slack = cp.Variable((n, m, T), nonneg=True)
        aux["slack"] = slack
        draft = np.array([b.draft for b in inst.boats])
        depth = np.array([b.depth for b in inst.berths])
        for i in range(n):
            for j, boat in enumerate(inst.boats):
                for t in range(boat.arrival_day, min(boat.departure_day, T)):
                    if 0 <= t < T:
                        constraints.append(draft[j] * x[i, j, t] <= depth[i] + slack[i, j, t])
        depth_penalty = penalty_M * cp.sum(slack)

    # Smallest-berth penalty: push each boat into the tightest-fitting berth by
    # charging for unused berth length (lost revenue potential of empty metres),
    # so a modest space_weight breaks ties toward smaller berths and a larger
    # weight visibly trades revenue for compactness. Applies to single berthing.
    space_penalty: cp.Expression | float = 0.0
    if space_weight > 0.0:
        waste = build_waste_length_matrix(inst)
        p = np.array([b.price_per_meter for b in inst.berths])
        WP = p[:, np.newaxis] * waste
        WP3 = WP[:, :, np.newaxis] * np.ones(T)
        space_penalty = space_weight * cp.sum(cp.multiply(WP3, x))

    objective = cp.Maximize(
        cp.sum(cp.multiply(R3, x)) + span_revenue
        - reloc_penalty - gap_penalty - depth_penalty - space_penalty
    )
    return cp.Problem(objective, constraints), x, aux


def _assignment_from_vars(inst, x, z) -> np.ndarray | None:
    """Build the (n, m, T) occupancy array. A spanning boat marks both berths."""
    if x.value is None:
        return None
    n, m, T = len(inst.berths), len(inst.boats), inst.n_days
    X = np.round(x.value).astype(int)
    if z is not None and z.value is not None:
        Z = np.round(z.value).astype(int)
        for k in range(n - 1):
            for j in range(m):
                for t in range(T):
                    if Z[k, j, t] == 1:
                        X[k, j, t] = 1
                        X[k + 1, j, t] = 1
    return X


def solve_final(
    inst: MarinaInstance,
    use_compat: bool = True,
    use_utility: bool = True,
    use_vip: bool = True,
    side_by_side: bool = False,
    soft_depth: bool = False,
    penalty_M: float = 1000.0,
    allow_relocation: bool = False,
    max_relocations: int = 1,
    gap_discount_rate: float = 0.0,
    short_stay_discount: float = 0.0,
    min_stay_days: int = 5,
    space_weight: float = 0.0,
    allow_multi_berth: bool = False,
    enforce_smallest_berth: bool = False,
    solver: str = "GLPK_MI",
    verbose: bool = False,
) -> SolveResult:
    t0 = time.perf_counter()
    problem, x, aux = build_final_model(
        inst,
        use_compat=use_compat,
        use_utility=use_utility,
        use_vip=use_vip,
        side_by_side=side_by_side,
        soft_depth=soft_depth,
        penalty_M=penalty_M,
        allow_relocation=allow_relocation,
        max_relocations=max_relocations,
        gap_discount_rate=gap_discount_rate,
        short_stay_discount=short_stay_discount,
        min_stay_days=min_stay_days,
        space_weight=space_weight,
        allow_multi_berth=allow_multi_berth,
        enforce_smallest_berth=enforce_smallest_berth,
    )
    problem.solve(solver=getattr(cp, solver), verbose=verbose)
    elapsed = time.perf_counter() - t0
    status = problem.status
    objective = problem.value

    assignment = _assignment_from_vars(inst, x, aux.get("z"))
    penalty = 0.0
    if assignment is not None:
        out = assignment if inst.n_days > 1 else assignment[:, :, 0]
        assignment = out
        # Gross realised revenue (undiscounted, including premiums) matches the
        # verifier. The total penalty (short-stay discount + relocation + gap +
        # depth + space) is therefore gross - objective.
        gross = realized_revenue(inst, assignment)
        penalty = gross - (objective or 0.0)
    del problem, x, aux

    flags = "+".join(filter(None, [
        "reloc" if allow_relocation else "stable",
        "compat" if use_compat else "",
        "utility" if use_utility else "",
        "vip" if use_vip else "",
        "sbs" if side_by_side else "",
        "soft" if soft_depth else "",
        "multiberth" if allow_multi_berth else "",
        "smallest" if enforce_smallest_berth else "",
        f"gap={gap_discount_rate}" if gap_discount_rate > 0 else "",
        f"short={short_stay_discount}" if short_stay_discount > 0 else "",
        f"space={space_weight}" if space_weight > 0 else "",
    ]))

    return SolveResult(
        status=status,
        objective_value=objective,
        assignment=assignment,
        solve_time=elapsed,
        model_name=f"final[{flags}]",
        penalty_value=max(0.0, penalty),
    )
