"""Season-level outcome metrics for a simulated policy run."""
from __future__ import annotations
from dataclasses import dataclass, field

import numpy as np

from ..realistic.marina import RealisticMarina
from ..realistic.demand import BookingRequest, month_of_day, seasonal_cumsum
from .calendar import BerthCalendar, BOOKED
from .policies import Decision, fits

_S = seasonal_cumsum()
SEGMENTS = ["small", "sail", "motor", "super"]


@dataclass
class SeasonOutcome:
    policy_name: str
    revenue: float                       # transient revenue over the season (EUR)
    n_requests: int
    n_accepted: int
    acceptance_rate: float
    occupancy: float                     # transient berth-day occupancy
    revpabd: float                       # revenue per available transient berth-day
    mean_waste_m: float                  # mean unused berth metres per accepted booking
    rejected_value: float                # revenue potential of rejected requests
    seg_acceptance: dict[str, float]
    monthly_revenue: dict[int, float]
    monthly_acceptance: dict[int, float]
    daily_occupancy: np.ndarray
    occ_snapshot: np.ndarray             # (n_berths, horizon) int8
    sim_seconds: float
    decisions: list[Decision] = field(repr=False, default_factory=list)

    def row(self) -> dict:
        """Flat summary row for CSV export."""
        return {
            "policy": self.policy_name,
            "revenue": round(self.revenue, 0),
            "acceptance_rate": round(self.acceptance_rate, 4),
            "occupancy": round(self.occupancy, 4),
            "revpabd": round(self.revpabd, 2),
            "mean_waste_m": round(self.mean_waste_m, 2),
            "rejected_value": round(self.rejected_value, 0),
            "sim_seconds": round(self.sim_seconds, 1),
            **{f"acc_{s}": round(self.seg_acceptance.get(s, 0.0), 3) for s in SEGMENTS},
        }


def _rejected_value(marina: RealisticMarina, req: BookingRequest) -> float:
    """Revenue potential of a rejected request: mean rate over feasible berths."""
    rates = [b.price_per_meter for b in marina.berths if fits(b, req)]
    if not rates:
        return 0.0
    seasonal = float(_S[req.departure_day] - _S[req.arrival_day])
    return float(np.mean(rates)) * req.length * seasonal


def compute_outcome(
    marina: RealisticMarina,
    requests: list[BookingRequest],
    decisions: list[Decision],
    cal: BerthCalendar,
    policy_name: str,
    sim_seconds: float,
) -> SeasonOutcome:
    transient = marina.transient_ids
    horizon = cal.horizon

    revenue = sum(d.revenue for d in decisions)
    n_acc = sum(1 for d in decisions if d.accepted)

    wastes = [marina.berths[d.berth_id].length - d.request.length
              for d in decisions if d.accepted]
    rej_value = sum(_rejected_value(marina, d.request)
                    for d in decisions if not d.accepted)

    seg_acc: dict[str, float] = {}
    for seg in SEGMENTS:
        segd = [d for d in decisions if d.request.segment == seg]
        seg_acc[seg] = (sum(1 for d in segd if d.accepted) / len(segd)) if segd else 0.0

    monthly_rev: dict[int, float] = {mth: 0.0 for mth in range(4, 11)}
    monthly_tot: dict[int, int] = {mth: 0 for mth in range(4, 11)}
    monthly_acc: dict[int, int] = {mth: 0 for mth in range(4, 11)}
    for d in decisions:
        mth = month_of_day(d.request.arrival_day)
        monthly_tot[mth] += 1
        if d.accepted:
            monthly_rev[mth] += d.revenue
            monthly_acc[mth] += 1
    monthly_acceptance = {
        mth: (monthly_acc[mth] / monthly_tot[mth] if monthly_tot[mth] else 0.0)
        for mth in monthly_tot}

    return SeasonOutcome(
        policy_name=policy_name,
        revenue=revenue,
        n_requests=len(requests),
        n_accepted=n_acc,
        acceptance_rate=n_acc / len(requests) if requests else 0.0,
        occupancy=cal.transient_occupancy(transient),
        revpabd=revenue / (len(transient) * horizon) if transient else 0.0,
        mean_waste_m=float(np.mean(wastes)) if wastes else 0.0,
        rejected_value=rej_value,
        seg_acceptance=seg_acc,
        monthly_revenue=monthly_rev,
        monthly_acceptance=monthly_acceptance,
        daily_occupancy=cal.daily_occupancy_series(transient),
        occ_snapshot=cal.occ.copy(),
        sim_seconds=sim_seconds,
        decisions=decisions,
    )
