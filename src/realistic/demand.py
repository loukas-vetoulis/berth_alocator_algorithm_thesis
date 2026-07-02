"""Seasonal booking-request stream for the realistic marina.

Requests do NOT arrive simultaneously: each booking has a ``booking_day``
(when the marina receives the request) and an ``arrival_day``/``departure_day``
stay window. The stream is generated as an inhomogeneous Poisson process:

- season: 1 April - 31 October (214 days, day 0 = 1 Apr 2025);
- monthly demand factors follow the Mediterranean charter/cruising season
  (peak July-August, quiet April/October);
- weekday factors add the Friday/Saturday arrival peak of weekly charters;
- boat population is a four-segment mixture (day cruisers, sailing
  cruisers/charter, motor yachts, superyachts) with size-dependent beam,
  draft and shore-power needs;
- length of stay: mostly 1-3 night transits, a weekly-charter block, and a
  tail of long stays;
- booking lead time: mixture from same-day VHF calls to months-ahead
  bookings; superyachts book further ahead.

Prices are seasonal: ``season_multiplier(day)`` scales the berth base rate
(high season x1.35, shoulder x1.0, low x0.8), matching the seasonal tariff
sheets published by Greek marinas.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
import numpy as np

SEASON_START = date(2025, 4, 1)
SEASON_DAYS = 214            # 1 Apr - 31 Oct 2025

# Relative transient-demand intensity per calendar month.
MONTH_FACTORS = {4: 0.25, 5: 0.45, 6: 0.75, 7: 0.95, 8: 1.00, 9: 0.65, 10: 0.30}

# Arrival-day-of-week factors, Monday=0 .. Sunday=6 (charter changeover on
# Friday/Saturday).
DOW_FACTORS = [0.85, 0.80, 0.90, 1.00, 1.30, 1.25, 0.90]

# Seasonal price multipliers on the base (shoulder) rate.
PRICE_MULT = {4: 0.80, 5: 1.00, 6: 1.00, 7: 1.35, 8: 1.35, 9: 1.00, 10: 0.80}

# Requests per day at month factor 1.0 (before the scenario demand
# multiplier). Sized so that peak-season demand exceeds the ~200-berth
# transient pool and rejections genuinely occur.
BASE_PEAK_RATE = 52.0


def day_to_date(day: int) -> date:
    return SEASON_START + timedelta(days=int(day))


def month_of_day(day: int) -> int:
    return day_to_date(day).month


def season_multiplier(day: int) -> float:
    return PRICE_MULT[month_of_day(day)]


def demand_pressure(day: int) -> float:
    """Normalised expected demand (0..1) used as the opportunity-cost signal."""
    return MONTH_FACTORS[month_of_day(day)] / max(MONTH_FACTORS.values())


def seasonal_cumsum() -> np.ndarray:
    """S[t] = sum of season_multiplier over days [0, t); length SEASON_DAYS+1."""
    mults = np.array([season_multiplier(t) for t in range(SEASON_DAYS)])
    return np.concatenate([[0.0], np.cumsum(mults)])


def pressure_cumsum() -> np.ndarray:
    """P[t] = sum of demand_pressure over days [0, t); length SEASON_DAYS+1."""
    press = np.array([demand_pressure(t) for t in range(SEASON_DAYS)])
    return np.concatenate([[0.0], np.cumsum(press)])


@dataclass
class BookingRequest:
    id: int
    booking_day: int          # may be negative (booked before season opening)
    arrival_day: int          # 0-based season day
    departure_day: int        # exclusive
    length: float
    beam: float
    draft: float
    power_kw: float
    boat_type: str            # sailboat / motorboat / yacht
    segment: str              # small / sail / motor / super

    @property
    def nights(self) -> int:
        return self.departure_day - self.arrival_day

    @property
    def lead_days(self) -> int:
        return self.arrival_day - self.booking_day


# ── boat population ────────────────────────────────────────────────────────────
# (segment, share, boat_type, beam ratio, draft ratio)
SEGMENTS = [
    ("small", 0.15, "motorboat", 0.340, 0.100),
    ("sail",  0.45, "sailboat",  0.320, 0.165),
    ("motor", 0.30, "motorboat", 0.295, 0.095),
    ("super", 0.10, "yacht",     0.270, 0.120),
]


def _sample_length(rng: np.random.Generator, segment: str) -> float:
    if segment == "small":
        return float(rng.uniform(6.0, 9.5))
    if segment == "sail":
        return float(np.clip(rng.normal(13.0, 2.2), 9.5, 17.0))
    if segment == "motor":
        return float(np.clip(rng.normal(15.0, 3.0), 10.0, 22.0))
    return float(rng.uniform(20.0, 29.0))       # super


def _sample_power(rng: np.random.Generator, segment: str, length: float) -> float:
    p_none = {"small": 0.5, "sail": 0.25, "motor": 0.15, "super": 0.02}[segment]
    if rng.random() < p_none:
        return 0.0
    if length < 10.0:
        return float(rng.uniform(2.0, 3.5))
    if length < 15.0:
        return float(rng.uniform(3.0, 7.0))
    if length < 20.0:
        return float(rng.uniform(6.0, 14.0))
    return float(rng.uniform(12.0, 40.0))


def _sample_los(rng: np.random.Generator) -> int:
    """Length of stay in nights: transit-heavy mixture, mean ~4.9 nights."""
    u = rng.random()
    if u < 0.55:
        return int(rng.integers(1, 4))          # 1-3 transit
    if u < 0.85:
        return int(rng.integers(4, 8))          # 4-7 weekly charter
    if u < 0.95:
        return int(rng.integers(8, 15))         # 8-14
    return int(rng.integers(15, 31))            # 15-30 long stay


def _sample_lead(rng: np.random.Generator, segment: str) -> int:
    """Booking lead time in days before arrival."""
    if segment == "super":
        weights, bins = [0.10, 0.30, 0.40, 0.20], [(0, 3), (3, 15), (15, 61), (61, 151)]
    else:
        weights, bins = [0.35, 0.40, 0.20, 0.05], [(0, 3), (3, 15), (15, 61), (61, 151)]
    k = rng.choice(len(bins), p=weights)
    lo, hi = bins[k]
    return int(rng.integers(lo, hi))


def generate_requests(seed: int = 7, demand_mult: float = 1.0) -> list[BookingRequest]:
    """Generate the season's booking stream (sorted by booking day).

    ``demand_mult`` scales the arrival intensity and defines the scenario
    (0.7 = quiet season, 1.0 = base, 1.3 = record season).
    """
    rng = np.random.default_rng(seed)
    seg_names = [s[0] for s in SEGMENTS]
    seg_probs = [s[1] for s in SEGMENTS]
    seg_meta = {s[0]: s for s in SEGMENTS}

    requests: list[BookingRequest] = []
    rid = 0
    for day in range(SEASON_DAYS):
        lam = BASE_PEAK_RATE * demand_mult * MONTH_FACTORS[month_of_day(day)] \
            * DOW_FACTORS[day_to_date(day).weekday()]
        n_arrivals = int(rng.poisson(lam))
        for _ in range(n_arrivals):
            segment = str(rng.choice(seg_names, p=seg_probs))
            _, _, boat_type, beam_r, draft_r = seg_meta[segment]
            length = _sample_length(rng, segment)
            beam = length * beam_r * float(rng.uniform(0.94, 1.06))
            draft = length * draft_r * float(rng.uniform(0.90, 1.12))
            los = _sample_los(rng)
            departure = min(day + los, SEASON_DAYS)
            if departure <= day:
                continue
            lead = _sample_lead(rng, segment)
            requests.append(BookingRequest(
                id=rid,
                booking_day=day - lead,
                arrival_day=day,
                departure_day=departure,
                length=round(length, 2),
                beam=round(beam, 2),
                draft=round(draft, 2),
                power_kw=round(_sample_power(rng, segment, length), 1),
                boat_type=boat_type,
                segment=segment,
            ))
            rid += 1

    requests.sort(key=lambda r: (r.booking_day, r.id))
    return requests
