from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from .data_model import MarinaInstance, SolveResult
from .revenue import realized_revenue, consumed_width


@dataclass
class VerificationReport:
    passed: bool
    violations: list[str]
    computed_revenue: float
    reported_revenue: float


def verify_solution(inst: MarinaInstance, result: SolveResult) -> VerificationReport:
    """Check that an assignment respects every hard constraint and that its
    reported objective reconciles with the realised revenue.

    Handles 2D (static) and 3D (temporal) assignments uniformly. The realised
    revenue accounts for alongside and multi-berth premiums (see core.revenue),
    so the "net = gross - penalty" check holds for the final model too.
    """
    violations: list[str] = []

    if result.assignment is None:
        return VerificationReport(
            passed=False,
            violations=["No assignment returned (infeasible or error)"],
            computed_revenue=0.0,
            reported_revenue=result.objective_value or 0.0,
        )

    X = result.assignment
    X3 = X[:, :, np.newaxis] if X.ndim == 2 else X
    temporal = X.ndim == 3
    n, m, T = X3.shape

    name = result.model_name or ""
    # Soft-depth in the FINAL model intentionally permits depth shortfalls (paid
    # for in the objective); extended[soft] keeps depth hard (Phase 2 behaviour).
    soft_suppress = ("soft" in name) and ("final" in name)
    allow_span = "multiberth" in name
    cons = consumed_width(inst)  # length for alongside boats, else beam

    # Per boat-day checks. A boat occupies one berth (single) or, when the model
    # allows it, two adjacent berths (span); physical fit is checked against the
    # single berth or the combined pair accordingly.
    def sfx(t):
        return f" day {t}" if temporal else ""

    for j, boat in enumerate(inst.boats):
        for t in range(T):
            occ = sorted(i for i in range(n) if X3[i, j, t] == 1)
            if not occ:
                continue
            if temporal and (t < boat.arrival_day or t >= boat.departure_day):
                violations.append(
                    f"Window violation: boat {j} on day {t} "
                    f"outside [{boat.arrival_day},{boat.departure_day})")
            valid_span = allow_span and len(occ) == 2 and abs(occ[0] - occ[1]) == 1

            if len(occ) == 1:
                i = occ[0]
                berth = inst.berths[i]
                on_contract = boat.contract_berth_id == i
                if boat.width > berth.width:
                    violations.append(f"Width violation: boat {j} at berth {i}" + sfx(t))
                if boat.length > berth.length:
                    violations.append(f"Length violation: boat {j} at berth {i}" + sfx(t))
                if boat.draft > berth.depth and not soft_suppress:
                    violations.append(f"Depth violation: boat {j} at berth {i}" + sfx(t))
                if (inst.compat_matrix is not None and inst.compat_matrix[i, j] == 0
                        and not on_contract):
                    violations.append(f"Compatibility violation: boat {j} incompatible with berth {i}")
                if boat.contract_berth_id is not None and boat.contract_berth_id != i:
                    violations.append(f"VIP violation: boat {j} at berth {i}, expected {boat.contract_berth_id}")
                if (boat.power_required_kw > 0 and berth.power_capacity_kw < boat.power_required_kw
                        and not on_contract):
                    violations.append(
                        f"Power violation: boat {j} needs {boat.power_required_kw} kW, "
                        f"berth {i} supplies {berth.power_capacity_kw} kW")
            elif valid_span:
                i0, i1 = occ
                b0, b1 = inst.berths[i0], inst.berths[i1]
                if boat.width > b0.width + b1.width:
                    violations.append(f"Width violation: boat {j} spanning {occ}" + sfx(t))
                if boat.length > min(b0.length, b1.length):
                    violations.append(f"Length violation: boat {j} spanning {occ}" + sfx(t))
                if boat.draft > min(b0.depth, b1.depth) and not soft_suppress:
                    violations.append(f"Depth violation: boat {j} spanning {occ}" + sfx(t))
                if inst.compat_matrix is not None and (inst.compat_matrix[i0, j] == 0 or inst.compat_matrix[i1, j] == 0):
                    violations.append(f"Compatibility violation: boat {j} spanning {occ}")
                if boat.power_required_kw > 0 and (b0.power_capacity_kw < boat.power_required_kw
                                                   or b1.power_capacity_kw < boat.power_required_kw):
                    violations.append(f"Power violation: boat {j} spanning {occ} needs {boat.power_required_kw} kW")
                if boat.contract_berth_id is not None:
                    violations.append(f"VIP violation: contracted boat {j} should not span berths")
            else:
                violations.append(f"Multiple/invalid berths for boat {j}" + sfx(t) + f": {occ}")

    # Per-berth, per-day capacity and shared-width budget.
    for i, berth in enumerate(inst.berths):
        for t in range(T):
            present = [j for j in range(m) if X3[i, j, t] == 1]
            if len(present) > 1 and "sbs" not in name:
                violations.append(
                    f"Overcapacity berth {i}" + (f" day {t}" if temporal else "")
                    + f": {len(present)} boats (single-occupancy mode)")
            if len(present) > 1:
                total = sum(cons[j] for j in present)
                if total > berth.width + 1e-6:
                    violations.append(
                        f"Width-budget violation at berth {i}" + (f" day {t}" if temporal else "")
                        + f": consumed {total:.2f} > {berth.width:.2f}")

    revenue = realized_revenue(inst, X)
    reported = result.objective_value or 0.0
    net_revenue = revenue - result.penalty_value
    if abs(net_revenue - reported) > max(1.0, abs(reported) * 1e-3):
        violations.append(
            f"Revenue mismatch: gross={revenue:.2f}, penalty={result.penalty_value:.2f}, "
            f"net={net_revenue:.2f}, reported={reported:.2f}")

    return VerificationReport(
        passed=len(violations) == 0,
        violations=violations,
        computed_revenue=revenue,
        reported_revenue=reported,
    )
