"""Berth-by-day occupancy calendar.

State values: 0 = free, 1 = transient booking, 2 = annual contract (blocked
for the whole season). ``booked_by`` keeps the request id per occupied cell
so occupancy heatmaps and Gantt zooms can be drawn from the final state.
"""
from __future__ import annotations
import numpy as np

from ..realistic.marina import RealisticMarina
from ..realistic.demand import BookingRequest

FREE, BOOKED, CONTRACT = 0, 1, 2
_GAP_SCAN_CAP = 45  # days; gaps longer than this are never "dead" anyway


class BerthCalendar:
    def __init__(self, marina: RealisticMarina, horizon: int):
        self.horizon = horizon
        self.occ = np.zeros((marina.n_berths, horizon), dtype=np.int8)
        self.booked_by = np.full((marina.n_berths, horizon), -1, dtype=np.int32)
        for i in marina.contract_ids:
            self.occ[i, :] = CONTRACT

    def is_free(self, berth_id: int, arrival: int, departure: int) -> bool:
        a, d = max(0, arrival), min(departure, self.horizon)
        return not self.occ[berth_id, a:d].any()

    def commit(self, berth_id: int, req: BookingRequest) -> None:
        a, d = max(0, req.arrival_day), min(req.departure_day, self.horizon)
        if self.occ[berth_id, a:d].any():
            raise RuntimeError(
                f"double booking: berth {berth_id}, days [{a},{d}), request {req.id}")
        self.occ[berth_id, a:d] = BOOKED
        self.booked_by[berth_id, a:d] = req.id

    def gap_before(self, berth_id: int, arrival: int) -> tuple[int, bool]:
        """(free days immediately before ``arrival``, enclosed by a booking).

        A gap is "enclosed" when the free run ends at an occupied day rather
        than at the season start; only enclosed short gaps are dead capacity.
        """
        run = 0
        t = arrival - 1
        while t >= 0 and run < _GAP_SCAN_CAP and self.occ[berth_id, t] == FREE:
            run += 1
            t -= 1
        enclosed = t >= 0 and self.occ[berth_id, t] != FREE
        return run, enclosed

    def gap_after(self, berth_id: int, departure: int) -> tuple[int, bool]:
        """(free days from ``departure`` to the next booking, enclosed flag)."""
        run = 0
        t = departure
        while t < self.horizon and run < _GAP_SCAN_CAP and self.occ[berth_id, t] == FREE:
            run += 1
            t += 1
        enclosed = t < self.horizon and self.occ[berth_id, t] != FREE
        return run, enclosed

    def transient_occupancy(self, transient_ids: list[int]) -> float:
        """Fraction of transient berth-days occupied by bookings."""
        sub = self.occ[transient_ids, :]
        return float((sub == BOOKED).mean()) if sub.size else 0.0

    def daily_occupancy_series(self, transient_ids: list[int]) -> np.ndarray:
        """Per-day occupancy rate of the transient pool, shape (horizon,)."""
        sub = self.occ[transient_ids, :]
        return (sub == BOOKED).mean(axis=0)
