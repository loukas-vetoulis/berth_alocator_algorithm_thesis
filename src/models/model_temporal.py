from __future__ import annotations
import time
import numpy as np
import cvxpy as cp
from .data_model import MarinaInstance, SolveResult


def build_window_mask(inst: MarinaInstance) -> np.ndarray:
    n, m, T = len(inst.berths), len(inst.boats), inst.n_days
    mask = np.zeros((n, m, T), dtype=float)
    for i in range(n):
        for j, boat in enumerate(inst.boats):
            for t in range(boat.arrival_day, boat.departure_day):
                if 0 <= t < T:
                    mask[i, j, t] = 1.0
    return mask


def build_feasibility_mask_3d(inst: MarinaInstance) -> np.ndarray:
    n, m, T = len(inst.berths), len(inst.boats), inst.n_days
    F3 = np.zeros((n, m, T), dtype=float)
    for i, berth in enumerate(inst.berths):
        for j, boat in enumerate(inst.boats):
            if (boat.width <= berth.width and
                    boat.length <= berth.length and
                    boat.draft  <= berth.depth):
                for t in range(boat.arrival_day, boat.departure_day):
                    if 0 <= t < T:
                        F3[i, j, t] = 1.0
    return F3


def build_temporal_model(
    inst: MarinaInstance,
    allow_relocation: bool = False,
    max_relocations: int = 1,
    gap_discount_rate: float = 0.0,
    short_stay_discount: float = 0.0,
    min_stay_days: int = 5,
    use_compat: bool = False,
    use_utility: bool = False,
) -> tuple[cp.Problem, cp.Variable, cp.Variable | None]:
    n, m, T = len(inst.berths), len(inst.boats), inst.n_days

    x = cp.Variable((n, m, T), boolean=True)

    F3 = build_feasibility_mask_3d(inst)

    # Compatibility: zero out (i,j) pairs forbidden by the compat matrix
    if use_compat and inst.compat_matrix is not None:
        compat_3d = inst.compat_matrix[:, :, np.newaxis] * np.ones(T)
        F3 = F3 * compat_3d

    # Shore power capacity: zero out pairs where berth kW < boat required kW
    if use_utility:
        for i, berth in enumerate(inst.berths):
            for j, boat in enumerate(inst.boats):
                if boat.power_required_kw > berth.power_capacity_kw:
                    F3[i, j, :] = 0.0

    constraints: list = [x <= F3]

    for j in range(m):
        for t in range(T):
            constraints.append(cp.sum(x[:, j, t]) <= 1)
    for i in range(n):
        for t in range(T):
            constraints.append(cp.sum(x[i, :, t]) <= 1)

    p = np.array([b.price_per_meter for b in inst.berths])
    l = np.array([b.length          for b in inst.boats])
    R2 = np.outer(p, l)
    R3 = R2[:, :, np.newaxis] * np.ones(T)

    # Short-stay gap-filling discount: boats that stay fewer than min_stay_days
    # are priced cheaper, making them attractive to fill short gaps in the schedule.
    if short_stay_discount > 0.0:
        for j, boat in enumerate(inst.boats):
            stay = boat.departure_day - boat.arrival_day
            if stay < min_stay_days:
                R3[:, j, :] *= (1.0 - short_stay_discount)

    reloc_penalty = 0.0
    r_var = None

    if allow_relocation:
        r_var = cp.Variable((m, T - 1), boolean=True) if T > 1 else None
        if r_var is not None:
            reloc_costs = np.array([b.relocation_cost for b in inst.boats])
            for j in range(m):
                for t in range(T - 1):
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

    gap_penalty = 0.0
    if gap_discount_rate > 0.0 and T > 1:
        avg_revenue_per_day = float(np.mean(p) * np.mean(l))
        gap = cp.Variable((m, T - 1), nonneg=True)
        for j in range(m):
            for t in range(1, T):
                stay_prev = cp.sum(x[:, j, t - 1])
                stay_curr = cp.sum(x[:, j, t])
                constraints.append(gap[j, t - 1] >= stay_prev - stay_curr)
        gap_penalty = gap_discount_rate * avg_revenue_per_day * cp.sum(gap)

    objective = cp.Maximize(
        cp.sum(cp.multiply(R3, x)) - reloc_penalty - gap_penalty
    )
    return cp.Problem(objective, constraints), x, r_var


def solve_temporal(
    inst: MarinaInstance,
    allow_relocation: bool = False,
    max_relocations: int = 1,
    gap_discount_rate: float = 0.0,
    short_stay_discount: float = 0.0,
    min_stay_days: int = 5,
    use_compat: bool = False,
    use_utility: bool = False,
    solver: str = "GLPK_MI",
    verbose: bool = False,
) -> SolveResult:
    t0 = time.perf_counter()
    problem, x, r_var = build_temporal_model(
        inst,
        allow_relocation=allow_relocation,
        max_relocations=max_relocations,
        gap_discount_rate=gap_discount_rate,
        short_stay_discount=short_stay_discount,
        min_stay_days=min_stay_days,
        use_compat=use_compat,
        use_utility=use_utility,
    )
    problem.solve(solver=getattr(cp, solver), verbose=verbose)
    elapsed = time.perf_counter() - t0

    assignment = None
    penalty = 0.0
    if x.value is not None:
        assignment = np.round(x.value).astype(int)
        # compute gross revenue to determine total penalty applied
        p = np.array([b.price_per_meter for b in inst.berths])
        l = np.array([b.length          for b in inst.boats])
        R2 = np.outer(p, l)
        T = inst.n_days
        R3 = R2[:, :, np.newaxis] * np.ones(T)
        gross = float(np.sum(R3 * assignment))
        penalty = gross - (problem.value or 0.0)

    flags = "+".join(filter(None, [
        "reloc" if allow_relocation else "stable",
        "compat" if use_compat else "",
        "utility" if use_utility else "",
        f"gapdiscount={gap_discount_rate}" if gap_discount_rate > 0 else "",
        f"shortstay={short_stay_discount}" if short_stay_discount > 0 else "",
    ]))

    return SolveResult(
        status=problem.status,
        objective_value=problem.value,
        assignment=assignment,
        solve_time=elapsed,
        model_name=f"temporal[{flags}]",
        penalty_value=max(0.0, penalty),
    )
