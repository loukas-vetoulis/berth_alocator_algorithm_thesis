from __future__ import annotations
import time
import numpy as np
import cvxpy as cp
from .data_model import MarinaInstance, SolveResult


def build_feasibility_mask(inst: MarinaInstance) -> np.ndarray:
    n, m = len(inst.berths), len(inst.boats)
    F = np.zeros((n, m), dtype=float)
    for i, berth in enumerate(inst.berths):
        for j, boat in enumerate(inst.boats):
            if (boat.width  <= berth.width  and
                boat.length <= berth.length and
                boat.draft  <= berth.depth):
                F[i, j] = 1.0
    return F


def build_basic_model(
    inst: MarinaInstance,
) -> tuple[cp.Problem, cp.Variable]:
    n, m = len(inst.berths), len(inst.boats)
    x = cp.Variable((n, m), boolean=True)

    p = np.array([b.price_per_meter for b in inst.berths])
    l = np.array([b.length          for b in inst.boats])
    R = np.outer(p, l)

    F = build_feasibility_mask(inst)
    constraints: list = [x <= F]

    for j in range(m):
        constraints.append(cp.sum(x[:, j]) <= 1)
    for i in range(n):
        constraints.append(cp.sum(x[i, :]) <= 1)

    objective = cp.Maximize(cp.sum(cp.multiply(R, x)))
    return cp.Problem(objective, constraints), x


def solve_basic(
    inst: MarinaInstance,
    solver: str = "GLPK_MI",
    verbose: bool = False,
) -> SolveResult:
    t0 = time.perf_counter()
    problem, x = build_basic_model(inst)
    problem.solve(solver=getattr(cp, solver), verbose=verbose)
    elapsed = time.perf_counter() - t0

    assignment = None
    if x.value is not None:
        assignment = np.round(x.value).astype(int)

    return SolveResult(
        status=problem.status,
        objective_value=problem.value,
        assignment=assignment,
        solve_time=elapsed,
        model_name="basic",
    )
