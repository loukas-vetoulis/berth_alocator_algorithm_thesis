"""Allocation policies for the dynamic booking simulation.

Online greedy policies decide each request the moment it is booked
(first-fit, best-fit / tightest berth, or myopic revenue-max). The batch
MILP policy collects the day's requests and solves an assignment MILP at
the end of each batching window, with a tunable objective:

    net value(i, j) = revenue(i, j)
                    - space  * rate_i * wasted metres * nights          (tight packing)
                    - frag   * rate_i * length_i * dead gap days        (fragmentation)
                    - opp    * rate_i * length_i * sum pressure(stay)   (opportunity cost)

- revenue(i, j) = rate_i * boat length * seasonal price sum of the stay;
- "dead gap days" are enclosed free runs shorter than MIN_USEFUL_GAP that
  the booking would strand against existing bookings on that berth;
- pressure(t) in [0, 1] is the marina's known seasonality: a berth-day
  consumed in August carries opportunity cost, one in April does not.
  With opp = L the policy only accepts a boat in peak season if it fills
  more than fraction L of the berth's revenue potential - a yield-
  management protection level.

A request whose every candidate pair has non-positive net value is
rejected (strategic rejection). The MILP is solved with HiGHS through
scipy.optimize.milp on feasible (berth, request) pairs only, so daily
batches at 460-berth scale solve in milliseconds.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field

import numpy as np
from scipy import sparse
from scipy.optimize import Bounds, LinearConstraint, linprog, milp

from ..core.data_model import Berth
from ..realistic.marina import RealisticMarina
from ..realistic.demand import BookingRequest, seasonal_cumsum, pressure_cumsum
from .calendar import BerthCalendar

MIN_USEFUL_GAP = 3  # enclosed gaps shorter than this count as dead capacity

_S = seasonal_cumsum()   # seasonal price multiplier, cumulative
_P = pressure_cumsum()   # demand pressure, cumulative


@dataclass(frozen=True)
class Weights:
    space: float = 0.0
    frag: float = 0.0
    opp: float = 0.0

    def label(self) -> str:
        return f"space={self.space:g},frag={self.frag:g},opp={self.opp:g}"


@dataclass
class Decision:
    request: BookingRequest
    day_decided: int
    berth_id: int | None
    revenue: float = 0.0

    @property
    def accepted(self) -> bool:
        return self.berth_id is not None


def fits(berth: Berth, req: BookingRequest) -> bool:
    return (req.length <= berth.length
            and req.beam <= berth.width
            and req.draft <= berth.depth
            and req.power_kw <= berth.power_capacity_kw + 1e-9)


def revenue_of(berth: Berth, req: BookingRequest) -> float:
    return berth.price_per_meter * req.length * float(_S[req.departure_day] - _S[req.arrival_day])


def pair_net_value(berth: Berth, req: BookingRequest, cal: BerthCalendar,
                   w: Weights) -> float:
    value = revenue_of(berth, req)
    if w.space > 0.0:
        value -= (w.space * berth.price_per_meter
                  * max(0.0, berth.length - req.length) * req.nights)
    if w.frag > 0.0:
        dead = 0
        g, enclosed = cal.gap_before(berth.id, req.arrival_day)
        if enclosed and 0 < g < MIN_USEFUL_GAP:
            dead += g
        g, enclosed = cal.gap_after(berth.id, req.departure_day)
        if enclosed and 0 < g < MIN_USEFUL_GAP:
            dead += g
        value -= w.frag * berth.price_per_meter * berth.length * dead
    if w.opp > 0.0:
        pressure = float(_P[req.departure_day] - _P[req.arrival_day])
        value -= w.opp * berth.price_per_meter * berth.length * pressure
    return value


def candidate_berths(marina: RealisticMarina, cal: BerthCalendar,
                     req: BookingRequest, k: int | None = 30) -> list[Berth]:
    """Feasible berths free for the whole stay, capped at k per request.

    When more than k berths qualify, keep the k/2 tightest (smallest berth
    length) and the k/2 highest-rate ones, so both the packing-optimal and
    the revenue-optimal choices stay available to the MILP. ``k=None``
    returns all (used by the clairvoyant LP bound).
    """
    free = [b for b in marina.berths
            if fits(b, req) and cal.is_free(b.id, req.arrival_day, req.departure_day)]
    if k is None or len(free) <= k:
        return free
    tight = sorted(free, key=lambda b: (b.length, b.id))[: k // 2]
    rich = sorted(free, key=lambda b: (-b.price_per_meter, b.id))[: k // 2]
    return list({b.id: b for b in tight + rich}.values())


# ── policy interface ───────────────────────────────────────────────────────────
class Policy:
    name: str = "policy"

    def observe(self, day: int, requests: list[BookingRequest]) -> None:
        raise NotImplementedError

    def decide(self, day: int, cal: BerthCalendar) -> list[Decision]:
        raise NotImplementedError


class OnlineGreedy(Policy):
    """Decide each request immediately at booking time, no lookahead.

    rule = "first_fit"    first free feasible berth walking the docks;
           "best_fit"     tightest free feasible berth (smallest length);
           "revenue_max"  highest-rate free feasible berth (myopic).
    """

    def __init__(self, marina: RealisticMarina, rule: str = "best_fit"):
        if rule not in ("first_fit", "best_fit", "revenue_max"):
            raise ValueError(f"unknown rule {rule!r}")
        self.marina = marina
        self.rule = rule
        self.name = f"online[{rule}]"
        self._new: list[BookingRequest] = []
        self._walk_pos = {bid: k for k, bid in enumerate(marina.walk_order)} \
            if marina.walk_order else {b.id: b.id for b in marina.berths}

    def observe(self, day: int, requests: list[BookingRequest]) -> None:
        self._new = list(requests)

    def decide(self, day: int, cal: BerthCalendar) -> list[Decision]:
        out = []
        for req in self._new:
            free = [b for b in self.marina.berths
                    if fits(b, req) and cal.is_free(b.id, req.arrival_day, req.departure_day)]
            if not free:
                out.append(Decision(req, day, None))
                continue
            if self.rule == "first_fit":
                chosen = min(free, key=lambda b: self._walk_pos[b.id])
            elif self.rule == "best_fit":
                chosen = min(free, key=lambda b: (b.length, b.id))
            else:
                chosen = max(free, key=lambda b: (b.price_per_meter, -b.id))
            cal.commit(chosen.id, req)
            out.append(Decision(req, day, chosen.id, revenue_of(chosen, req)))
        self._new = []
        return out


class BatchMILP(Policy):
    """Collect requests and solve a joint assignment MILP per batching window.

    ``batch_days = 1`` answers every request at the end of its booking day
    (overnight optimization). With longer windows, requests whose arrival is
    imminent are still decided the same evening (urgent mini-batch), so no
    boat arrives before its booking is answered.
    """

    def __init__(self, marina: RealisticMarina, weights: Weights = Weights(),
                 batch_days: int = 1, cand_k: int = 30, time_limit: float = 30.0,
                 name: str | None = None):
        self.marina = marina
        self.weights = weights
        self.batch_days = max(1, int(batch_days))
        self.cand_k = cand_k
        self.time_limit = time_limit
        self.name = name or (f"batch[{self.batch_days}d,{weights.label()}]")
        self._pending: list[BookingRequest] = []
        self.solve_seconds = 0.0
        self.n_solves = 0

    def observe(self, day: int, requests: list[BookingRequest]) -> None:
        self._pending.extend(requests)

    def decide(self, day: int, cal: BerthCalendar) -> list[Decision]:
        if (day + 1) % self.batch_days == 0:
            due = self._pending
            self._pending = []
        else:
            due = [r for r in self._pending if r.arrival_day <= day + 1]
            self._pending = [r for r in self._pending if r.arrival_day > day + 1]
        if not due:
            return []
        t0 = time.perf_counter()
        assignment = solve_assignment_milp(
            self.marina, cal, due, self.weights,
            cand_k=self.cand_k, time_limit=self.time_limit)
        self.solve_seconds += time.perf_counter() - t0
        self.n_solves += 1
        out = []
        for req in due:
            berth = assignment.get(req.id)
            if berth is None:
                out.append(Decision(req, day, None))
            else:
                cal.commit(berth.id, req)
                out.append(Decision(req, day, berth.id, revenue_of(berth, req)))
        return out


# ── the assignment MILP ────────────────────────────────────────────────────────
def _build_pairs(marina, cal, requests, weights, cand_k):
    """Candidate (berth, request) pairs with positive net value."""
    pair_req: list[BookingRequest] = []
    pair_berth: list[Berth] = []
    values: list[float] = []
    req_pairs: dict[int, list[int]] = {}
    for req in requests:
        req_pairs[req.id] = []
        for b in candidate_berths(marina, cal, req, k=cand_k):
            v = pair_net_value(b, req, cal, weights)
            if v > 1e-9:
                req_pairs[req.id].append(len(values))
                pair_req.append(req)
                pair_berth.append(b)
                values.append(v)
    return pair_req, pair_berth, values, req_pairs


def _build_constraints(pair_req, pair_berth, req_pairs):
    """Sparse constraint matrix: one berth per request + interval cliques.

    On each berth, overlapping stays exclude each other; for intervals it is
    sufficient to add one clique constraint per distinct stay-start point.
    Conflicts with already committed bookings cannot occur because
    candidates are free for the whole stay.
    """
    n_pairs = len(pair_req)
    rows, cols = [], []
    n_rows = 0
    for idxs in req_pairs.values():
        if not idxs:
            continue
        rows.extend([n_rows] * len(idxs))
        cols.extend(idxs)
        n_rows += 1

    by_berth: dict[int, list[int]] = {}
    for p in range(n_pairs):
        by_berth.setdefault(pair_berth[p].id, []).append(p)
    for idxs in by_berth.values():
        if len(idxs) == 1:
            continue
        idx_arr = np.asarray(idxs)
        arr = np.asarray([pair_req[p].arrival_day for p in idxs])
        dep = np.asarray([pair_req[p].departure_day for p in idxs])
        for a in np.unique(arr):
            covering = idx_arr[(arr <= a) & (a < dep)]
            if covering.size > 1:
                rows.extend([n_rows] * covering.size)
                cols.extend(covering.tolist())
                n_rows += 1

    if n_rows == 0:
        return None, 0
    A = sparse.coo_matrix(
        (np.ones(len(rows)), (rows, cols)), shape=(n_rows, n_pairs)).tocsc()
    return A, n_rows


def solve_assignment_milp(
    marina: RealisticMarina,
    cal: BerthCalendar,
    requests: list[BookingRequest],
    weights: Weights,
    cand_k: int | None = 30,
    time_limit: float = 30.0,
) -> dict[int, Berth | None]:
    """Assign a batch of requests to free berths, maximizing total net value.

    Returns {request_id: Berth or None}; None means rejected (infeasible or
    strategically declined when every pair has non-positive net value).
    """
    pair_req, pair_berth, values, req_pairs = _build_pairs(
        marina, cal, requests, weights, cand_k)

    result: dict[int, Berth | None] = {req.id: None for req in requests}
    n_pairs = len(values)
    if n_pairs == 0:
        return result

    A, n_rows = _build_constraints(pair_req, pair_berth, req_pairs)
    if A is None:
        x = np.ones(n_pairs)
    else:
        res = milp(
            c=-np.asarray(values),
            constraints=[LinearConstraint(A, -np.inf, np.ones(n_rows))],
            integrality=np.ones(n_pairs),
            bounds=Bounds(0, 1),
            options={"time_limit": time_limit, "presolve": True},
        )
        if res.x is None:
            return _greedy_fallback(pair_req, pair_berth, values, result)
        x = res.x

    for req in requests:
        chosen, best_v = None, 0.0
        for p in req_pairs[req.id]:
            if x[p] > 0.5 and values[p] > best_v - 1e-12:
                chosen, best_v = pair_berth[p], values[p]
        result[req.id] = chosen
    return result


def _greedy_fallback(pair_req, pair_berth, values, result):
    """Value-ordered greedy if the MILP solver fails (should be rare)."""
    taken: set[tuple[int, int]] = set()  # (berth_id, day)
    assigned: set[int] = set()
    for p in sorted(range(len(values)), key=lambda p: -values[p]):
        req, b = pair_req[p], pair_berth[p]
        if req.id in assigned:
            continue
        days = range(req.arrival_day, req.departure_day)
        if any((b.id, t) in taken for t in days):
            continue
        for t in days:
            taken.add((b.id, t))
        assigned.add(req.id)
        result[req.id] = b
    return result


def clairvoyant_greedy(marina: RealisticMarina, requests: list[BookingRequest],
                       horizon: int) -> tuple[list[Decision], BerthCalendar]:
    """Perfect-information greedy: process by arrival day (not booking day),
    best-fit placement. A feasible clairvoyant plan usable as a fallback
    lower bound when the season LP is unavailable."""
    cal = BerthCalendar(marina, horizon)
    decisions = []
    for req in sorted(requests, key=lambda r: (r.arrival_day, -r.length * r.nights)):
        free = [b for b in marina.berths
                if fits(b, req) and cal.is_free(b.id, req.arrival_day, req.departure_day)]
        if not free:
            decisions.append(Decision(req, req.booking_day, None))
            continue
        b = min(free, key=lambda b_: (b_.length, b_.id))
        cal.commit(b.id, req)
        decisions.append(Decision(req, req.booking_day, b.id, revenue_of(b, req)))
    return decisions, cal


def category_upper_bound(marina: RealisticMarina, requests: list[BookingRequest],
                         horizon: int, time_limit: float = 300.0) -> float:
    """Aggregated clairvoyant upper bound (fast fallback).

    Berths are pooled per category with the category's maximum rate and most
    permissive dimensions, an LP assigns request fractions to categories
    under per-day pool capacities. Any feasible berth-level plan maps into
    this LP with no smaller objective, so its optimum is a valid (slightly
    looser, rate jitter ~+4%) upper bound on every policy's revenue.
    """
    cats = sorted(set(marina.category_of))
    cat_idx = {c: k for k, c in enumerate(cats)}
    trans = set(marina.transient_ids)
    pool: dict[str, list] = {c: [] for c in cats}
    for b in marina.berths:
        if b.id in trans:
            pool[marina.category_of[b.id]].append(b)
    cap = {c: len(pool[c]) for c in cats}
    max_rate = {c: max((b.price_per_meter for b in pool[c]), default=0.0) for c in cats}
    max_w = {c: max((b.width for b in pool[c]), default=0.0) for c in cats}
    max_d = {c: max((b.depth for b in pool[c]), default=0.0) for c in cats}
    max_l = {c: max((b.length for b in pool[c]), default=0.0) for c in cats}
    max_p = {c: max((b.power_capacity_kw for b in pool[c]), default=0.0) for c in cats}

    var_req, var_cat, values = [], [], []
    for req in requests:
        for c in cats:
            if cap[c] == 0 or req.length > max_l[c] or req.beam > max_w[c] \
                    or req.draft > max_d[c] or req.power_kw > max_p[c] + 1e-9:
                continue
            seasonal = float(_S[req.departure_day] - _S[req.arrival_day])
            var_req.append(req)
            var_cat.append(c)
            values.append(max_rate[c] * req.length * seasonal)
    if not values:
        return 0.0

    rows, cols, caps = [], [], []
    n_rows = 0
    by_req: dict[int, list[int]] = {}
    for p, req in enumerate(var_req):
        by_req.setdefault(req.id, []).append(p)
    for idxs in by_req.values():
        rows.extend([n_rows] * len(idxs))
        cols.extend(idxs)
        caps.append(1.0)
        n_rows += 1
    by_cat_day: dict[tuple[str, int], list[int]] = {}
    for p, req in enumerate(var_req):
        for t in range(req.arrival_day, min(req.departure_day, horizon)):
            by_cat_day.setdefault((var_cat[p], t), []).append(p)
    for (c, _), idxs in by_cat_day.items():
        rows.extend([n_rows] * len(idxs))
        cols.extend(idxs)
        caps.append(float(cap[c]))
        n_rows += 1

    A = sparse.coo_matrix(
        (np.ones(len(rows)), (rows, cols)), shape=(n_rows, len(values))).tocsc()
    res = linprog(
        c=-np.asarray(values),
        A_ub=A,
        b_ub=np.asarray(caps),
        bounds=(0, 1),
        method="highs",
        options={"time_limit": time_limit, "presolve": True},
    )
    if res.x is None:
        raise RuntimeError(f"category UB LP failed: {res.message}")
    return float(-res.fun)


@dataclass
class OracleBounds:
    """Two-sided clairvoyant benchmark for a full season.

    The exact clairvoyant MILP (~700k pairs) is out of reach, so we bracket
    it: ``upper_bound`` is the LP relaxation over ALL feasible pairs (a valid
    upper bound on any policy's revenue); ``decisions`` is a feasible
    clairvoyant plan obtained by LP-guided rounding, whose revenue is a
    lower bound on the clairvoyant optimum. Interval-assignment LPs are
    near-integral, so the bracket is tight in practice.
    """
    upper_bound: float
    decisions: list[Decision]
    calendar: BerthCalendar
    feasible_revenue: float
    lp_seconds: float
    total_seconds: float


def oracle_bounds(
    marina: RealisticMarina,
    requests: list[BookingRequest],
    horizon: int,
    time_limit: float = 900.0,
) -> OracleBounds:
    t0 = time.perf_counter()
    cal = BerthCalendar(marina, horizon)
    pair_req, pair_berth, values, req_pairs = _build_pairs(
        marina, cal, requests, Weights(), cand_k=None)
    A, n_rows = _build_constraints(pair_req, pair_berth, req_pairs)

    values_arr = np.asarray(values)
    # Interior point scales to the ~700k-variable season LP where simplex
    # (and the milp() code path) time out.
    res = linprog(
        c=-values_arr,
        A_ub=A,
        b_ub=np.ones(n_rows),
        bounds=(0, 1),
        method="highs-ipm",
        options={"time_limit": time_limit, "presolve": True},
    )
    if res.x is None:
        raise RuntimeError(f"oracle LP failed: {res.message}")
    upper = float(-res.fun)
    lp_seconds = time.perf_counter() - t0

    # LP-guided rounding: commit pairs by (fractional value, net value).
    order = sorted(range(len(values)),
                   key=lambda p: (-res.x[p], -values_arr[p]))
    assigned: dict[int, Berth] = {}
    for p in order:
        if res.x[p] < 1e-6:
            break
        req = pair_req[p]
        if req.id in assigned:
            continue
        b = pair_berth[p]
        if cal.is_free(b.id, req.arrival_day, req.departure_day):
            cal.commit(b.id, req)
            assigned[req.id] = b
    # Second pass: place still-unassigned requests best-fit in leftover space.
    for req in requests:
        if req.id in assigned:
            continue
        free = [b for b in marina.berths
                if fits(b, req) and cal.is_free(b.id, req.arrival_day, req.departure_day)]
        if free:
            b = min(free, key=lambda b_: (b_.length, b_.id))
            cal.commit(b.id, req)
            assigned[req.id] = b

    decisions = []
    for req in requests:
        b = assigned.get(req.id)
        if b is None:
            decisions.append(Decision(req, req.booking_day, None))
        else:
            decisions.append(Decision(req, req.booking_day, b.id, revenue_of(b, req)))
    feasible_rev = sum(d.revenue for d in decisions)
    return OracleBounds(
        upper_bound=upper,
        decisions=decisions,
        calendar=cal,
        feasible_revenue=feasible_rev,
        lp_seconds=lp_seconds,
        total_seconds=time.perf_counter() - t0,
    )
