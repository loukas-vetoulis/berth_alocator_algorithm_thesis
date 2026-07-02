"""Event-driven season simulator.

Requests are revealed to the policy on their booking day - never all at
once. Each simulated day d:

1. requests booked on day d are revealed (``policy.observe``);
2. the policy decides whichever requests are due (``policy.decide``) and
   commits accepted bookings to the shared occupancy calendar.

Accepted bookings are guaranteed (stable assignment, no relocation) and
rejections are final, which is how marina reservations work in practice.
"""
from __future__ import annotations
import time
from collections import defaultdict

from ..realistic.marina import RealisticMarina
from ..realistic.demand import BookingRequest, SEASON_DAYS
from .calendar import BerthCalendar
from .metrics import SeasonOutcome, compute_outcome
from .policies import Policy


def simulate_season(
    marina: RealisticMarina,
    requests: list[BookingRequest],
    policy: Policy,
    horizon: int = SEASON_DAYS,
) -> SeasonOutcome:
    cal = BerthCalendar(marina, horizon)
    by_day: dict[int, list[BookingRequest]] = defaultdict(list)
    for r in requests:
        by_day[r.booking_day].append(r)
    first_day = min(by_day, default=0)

    decisions = []
    t0 = time.perf_counter()
    for day in range(first_day, horizon):
        policy.observe(day, by_day.get(day, []))
        decisions.extend(policy.decide(day, cal))
    elapsed = time.perf_counter() - t0

    if len(decisions) != len(requests):
        raise RuntimeError(
            f"{policy.name}: {len(decisions)} decisions for {len(requests)} requests")
    return compute_outcome(marina, requests, decisions, cal, policy.name, elapsed)
