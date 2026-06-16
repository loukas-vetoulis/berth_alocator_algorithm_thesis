from __future__ import annotations
import time
import numpy as np
import cvxpy as cp
from .data_model import MarinaInstance, SolveResult
from .model_basic import build_feasibility_mask


def add_compatibility(
    constraints: list,
    x: cp.Variable,
    inst: MarinaInstance,
) -> list:
    if inst.compat_matrix is not None:
        constraints.append(x <= inst.compat_matrix)
    return constraints


def add_utility_services(
    constraints: list,
    x: cp.Variable,
    inst: MarinaInstance,
) -> list:
    for j, boat in enumerate(inst.boats):
        if boat.power_required_kw <= 0.0:
            continue
        for i, berth in enumerate(inst.berths):
            # Berth must supply at least as many kW as the boat requires.
            # A berth with power_capacity_kw = 0 has no shore power at all.
            if berth.power_capacity_kw < boat.power_required_kw:
                constraints.append(x[i, j] == 0)
    return constraints


def add_vip_contracts(
    constraints: list,
    x: cp.Variable,
    inst: MarinaInstance,
) -> list:
    n = len(inst.berths)
    for j, boat in enumerate(inst.boats):
        if boat.contract_berth_id is None:
            continue
        i_vip = boat.contract_berth_id
        constraints.append(x[i_vip, j] == 1)
        for i in range(n):
            if i != i_vip:
                constraints.append(x[i, j] == 0)
    return constraints


def build_extended_model(
    inst: MarinaInstance,
    use_compat: bool = True,
    use_utility: bool = True,
    use_vip: bool = True,
    side_by_side: bool = False,
    soft_depth: bool = False,
    penalty_M: float = 1000.0,
) -> tuple[cp.Problem, cp.Variable, cp.Variable | None]:
    n, m = len(inst.berths), len(inst.boats)
    x = cp.Variable((n, m), boolean=True)

    p = np.array([b.price_per_meter for b in inst.berths])
    l = np.array([b.length          for b in inst.boats])
    R = np.outer(p, l)

    F = build_feasibility_mask(inst)
    constraints: list = [x <= F]

    if use_compat:
        constraints = add_compatibility(constraints, x, inst)
    if use_utility:
        constraints = add_utility_services(constraints, x, inst)
    if use_vip:
        constraints = add_vip_contracts(constraints, x, inst)

    for j in range(m):
        constraints.append(cp.sum(x[:, j]) <= 1)

    width_arr = np.array([b.width for b in inst.boats])

    if side_by_side:
        for i, berth in enumerate(inst.berths):
            constraints.append(x[i, :] @ width_arr <= berth.width)
            constraints.append(cp.sum(x[i, :]) <= berth.max_boats)
    else:
        for i in range(n):
            constraints.append(cp.sum(x[i, :]) <= 1)

    slack = None
    penalty_expr = 0.0
    if soft_depth:
        slack = cp.Variable((n, m), nonneg=True)
        draft_arr = np.array([b.draft for b in inst.boats])
        depth_arr = np.array([b.depth for b in inst.berths])
        for i in range(n):
            for j in range(m):
                constraints.append(
                    draft_arr[j] * x[i, j] <= depth_arr[i] + slack[i, j]
                )
        penalty_expr = penalty_M * cp.sum(slack)

    objective = cp.Maximize(cp.sum(cp.multiply(R, x)) - penalty_expr)
    return cp.Problem(objective, constraints), x, slack


def solve_extended(
    inst: MarinaInstance,
    use_compat: bool = True,
    use_utility: bool = True,
    use_vip: bool = True,
    side_by_side: bool = False,
    soft_depth: bool = False,
    penalty_M: float = 1000.0,
    solver: str = "GLPK_MI",
    verbose: bool = False,
) -> SolveResult:
    t0 = time.perf_counter()
    problem, x, _ = build_extended_model(
        inst,
        use_compat=use_compat,
        use_utility=use_utility,
        use_vip=use_vip,
        side_by_side=side_by_side,
        soft_depth=soft_depth,
        penalty_M=penalty_M,
    )
    problem.solve(solver=getattr(cp, solver), verbose=verbose)
    elapsed = time.perf_counter() - t0

    assignment = None
    if x.value is not None:
        assignment = np.round(x.value).astype(int)

    flags = "+".join(filter(None, [
        "compat" if use_compat else "",
        "utility" if use_utility else "",
        "vip" if use_vip else "",
        "sbs" if side_by_side else "",
        "soft" if soft_depth else "",
    ]))

    return SolveResult(
        status=problem.status,
        objective_value=problem.value,
        assignment=assignment,
        solve_time=elapsed,
        model_name=f"extended[{flags}]",
    )
