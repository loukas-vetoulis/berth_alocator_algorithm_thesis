from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from .data_model import MarinaInstance, SolveResult


@dataclass
class VerificationReport:
    passed: bool
    violations: list[str]
    computed_revenue: float
    reported_revenue: float


def verify_solution(inst: MarinaInstance, result: SolveResult) -> VerificationReport:
    violations: list[str] = []

    if result.assignment is None:
        return VerificationReport(
            passed=False,
            violations=["No assignment returned (infeasible or error)"],
            computed_revenue=0.0,
            reported_revenue=result.objective_value or 0.0,
        )

    X = result.assignment
    if X.ndim == 2:
        return _verify_static(inst, X, result, violations)
    return _verify_temporal(inst, X, result, violations)


def _verify_static(
    inst: MarinaInstance,
    X: np.ndarray,
    result: SolveResult,
    violations: list[str],
) -> VerificationReport:
    n, m = len(inst.berths), len(inst.boats)
    revenue = 0.0

    for i, berth in enumerate(inst.berths):
        for j, boat in enumerate(inst.boats):
            if X[i, j] != 1:
                continue
            revenue += berth.price_per_meter * boat.length
            if boat.width > berth.width:
                violations.append(f"Width violation: boat {j} (w={boat.width}) > berth {i} (W={berth.width})")
            if boat.length > berth.length:
                violations.append(f"Length violation: boat {j} (l={boat.length}) > berth {i} (L={berth.length})")
            if boat.draft > berth.depth:
                violations.append(f"Depth violation: boat {j} (d={boat.draft}) > berth {i} (D={berth.depth})")
            if inst.compat_matrix is not None and inst.compat_matrix[i, j] == 0:
                violations.append(f"Compatibility violation: boat {j} incompatible with berth {i}")
            if boat.contract_berth_id is not None and boat.contract_berth_id != i:
                violations.append(f"VIP violation: boat {j} assigned to berth {i}, expected {boat.contract_berth_id}")
            if boat.power_required_kw > 0 and berth.power_capacity_kw < boat.power_required_kw:
                violations.append(
                    f"Power violation: boat {j} needs {boat.power_required_kw} kW, "
                    f"berth {i} supplies {berth.power_capacity_kw} kW"
                )

    for j in range(m):
        total = int(X[:, j].sum())
        if total > 1:
            violations.append(f"Multiple berths for boat {j}: {total}")

    for i in range(n):
        total = int(X[i, :].sum())
        if total > inst.berths[i].max_boats:
            violations.append(f"Overcapacity at berth {i}: {total} boats (max {inst.berths[i].max_boats})")

    reported = result.objective_value or 0.0
    net_revenue = revenue - result.penalty_value
    if abs(net_revenue - reported) > max(1.0, abs(reported) * 1e-3):
        violations.append(
            f"Revenue mismatch: gross={revenue:.2f}, penalty={result.penalty_value:.2f}, "
            f"net={net_revenue:.2f}, reported={reported:.2f}"
        )

    return VerificationReport(
        passed=len(violations) == 0,
        violations=violations,
        computed_revenue=revenue,
        reported_revenue=reported,
    )


def _verify_temporal(
    inst: MarinaInstance,
    X: np.ndarray,
    result: SolveResult,
    violations: list[str],
) -> VerificationReport:
    n, m, T = X.shape
    revenue = 0.0

    for i, berth in enumerate(inst.berths):
        for j, boat in enumerate(inst.boats):
            for t in range(T):
                if X[i, j, t] != 1:
                    continue
                revenue += berth.price_per_meter * boat.length
                if t < boat.arrival_day or t >= boat.departure_day:
                    violations.append(f"Window violation: boat {j} at berth {i} on day {t} outside [{boat.arrival_day},{boat.departure_day})")
                if boat.width > berth.width:
                    violations.append(f"Width violation: boat {j} at berth {i} day {t}")
                if boat.length > berth.length:
                    violations.append(f"Length violation: boat {j} at berth {i} day {t}")
                if boat.draft > berth.depth:
                    violations.append(f"Depth violation: boat {j} at berth {i} day {t}")
                if boat.power_required_kw > 0 and berth.power_capacity_kw < boat.power_required_kw:
                    violations.append(
                        f"Power violation: boat {j} needs {boat.power_required_kw} kW, "
                        f"berth {i} supplies {berth.power_capacity_kw} kW (day {t})"
                    )

    for j in range(m):
        for t in range(T):
            if X[:, j, t].sum() > 1:
                violations.append(f"Multiple berths for boat {j} on day {t}")

    for i in range(n):
        for t in range(T):
            if X[i, :, t].sum() > 1:
                violations.append(f"Overcapacity berth {i} on day {t}")

    reported = result.objective_value or 0.0
    net_revenue = revenue - result.penalty_value
    if abs(net_revenue - reported) > max(1.0, abs(reported) * 1e-3):
        violations.append(
            f"Revenue mismatch: gross={revenue:.2f}, penalty={result.penalty_value:.2f}, "
            f"net={net_revenue:.2f}, reported={reported:.2f}"
        )

    return VerificationReport(
        passed=len(violations) == 0,
        violations=violations,
        computed_revenue=revenue,
        reported_revenue=reported,
    )
