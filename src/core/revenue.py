"""Canonical revenue definition shared by the model, verifier and heuristics.

Realised revenue depends on how a boat is moored, so it must be computed the
same way everywhere or the verifier's "net = gross - penalty" check will fail.
Two premiums apply on top of the base price * length charge:

- alongside mooring (plagiodetisi): the boat lies parallel, occupying length
  metres of the berth's width budget instead of its beam; charged a large
  premium because it consumes much more shared space.
- multi-berth spanning: an oversized boat occupies two adjacent berths; charged
  a premium and billed once per day (not once per berth).

The premiums are module constants so the model and the verifier always agree.
Adjust them here to tune.
"""
from __future__ import annotations
import numpy as np
from .data_model import MarinaInstance

ALONGSIDE_PREMIUM = 0.6      # +60% for alongside mooring
MULTI_BERTH_PREMIUM = 0.25   # +25% for spanning two adjacent berths


def is_alongside(boat) -> bool:
    return getattr(boat, "mooring_type", "stern_to") == "alongside"


def single_revenue_matrix(inst: MarinaInstance) -> np.ndarray:
    """R[i, j] = price_i * length_j, with the alongside premium folded in per boat."""
    p = np.array([b.price_per_meter for b in inst.berths])
    l = np.array([b.length for b in inst.boats])
    R = np.outer(p, l)
    for j, boat in enumerate(inst.boats):
        if is_alongside(boat):
            R[:, j] *= (1.0 + ALONGSIDE_PREMIUM)
    return R


def span_revenue_matrix(inst: MarinaInstance) -> np.ndarray:
    """Rspan[k, j] for boat j spanning the adjacent pair (k, k+1).

    Uses the average price of the two berths, the multi-berth premium, and the
    alongside premium if applicable. Shape (n-1, m).
    """
    n, m = len(inst.berths), len(inst.boats)
    pz = np.array([(inst.berths[k].price_per_meter + inst.berths[k + 1].price_per_meter) / 2.0
                   for k in range(n - 1)])
    l = np.array([b.length for b in inst.boats])
    R = np.outer(pz, l) * (1.0 + MULTI_BERTH_PREMIUM)
    for j, boat in enumerate(inst.boats):
        if is_alongside(boat):
            R[:, j] *= (1.0 + ALONGSIDE_PREMIUM)
    return R


def consumed_width(inst: MarinaInstance) -> np.ndarray:
    """Width budget consumed by each boat: its length if alongside, else its beam."""
    return np.array([(b.length if is_alongside(b) else b.width) for b in inst.boats])


def realized_revenue(inst: MarinaInstance, assignment: np.ndarray | None) -> float:
    """Gross realised revenue of a 2D or 3D assignment (undiscounted).

    Counts each boat-day once; a boat occupying two adjacent berths on a day is a
    single span charge. This is the common metric for comparing the MILP, greedy
    and online methods - the MILP objective_value is net of penalties.
    """
    if assignment is None:
        return 0.0
    X = assignment
    if X.ndim == 2:
        X = X[:, :, np.newaxis]
    n, m, T = X.shape
    p = [b.price_per_meter for b in inst.berths]
    total = 0.0
    for j, boat in enumerate(inst.boats):
        prem = (1.0 + ALONGSIDE_PREMIUM) if is_alongside(boat) else 1.0
        for t in range(T):
            berths = [i for i in range(n) if X[i, j, t] == 1]
            if not berths:
                continue
            if len(berths) == 1:
                total += p[berths[0]] * boat.length * prem
            else:
                avg_price = sum(p[i] for i in berths) / len(berths)
                total += avg_price * boat.length * (1.0 + MULTI_BERTH_PREMIUM) * prem
    return float(total)
