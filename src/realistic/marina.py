"""Berth inventory of a large Greek-style coastal marina.

The inventory is synthetic but every parameter is anchored to publicly
available characteristics of large Greek marinas (Alimos, Zea, Gouvia,
Rhodes class facilities):

- ~460 wet berths grouped in piers by boat-length category, most berths in
  the 8-15 m range and a small superyacht quay;
- daily mooring tariffs that grow more than linearly with boat size
  (about 2 EUR/m/day for a 8 m berth up to ~9.5 EUR/m/day for a 30 m berth,
  matching the 25-320 EUR/day range published by Greek marinas);
- shore power tiers 16A / 32A / 63A / 125A by berth size;
- a majority of berths held by annual contracts. Contract berths are
  blocked for the whole season and produce fixed revenue; the allocation
  problem concerns the transient (visitor) pool, as in real operations.

Berths reuse the core ``Berth`` dataclass so the phase 1-3 vocabulary
carries over: ``price_per_meter`` is the *base* (shoulder season) daily
rate per metre of boat length; seasonal multipliers are applied by the
simulation layer (see demand.season_multiplier).
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

from ..core.data_model import Berth


@dataclass(frozen=True)
class BerthCategory:
    code: str
    max_boat_length: float   # m, also the berth length
    count: int
    depth: float             # m
    power_kw: float          # shore power capacity
    base_rate: float         # EUR per metre of boat per day, shoulder season
    contract_share: float    # fraction of berths under annual contract

    @property
    def width(self) -> float:
        # Finger-to-finger width sized for the largest boat of the category
        # (beam ~ 0.31 * length) plus fender clearance.
        return round(0.31 * self.max_boat_length + 0.9, 2)


# Category mix of a ~460-berth marina. Counts follow the typical Greek
# marina size distribution (bulk of berths 8-15 m); contract share is
# highest for small local boats and lowest on the superyacht quay.
CATEGORIES: list[BerthCategory] = [
    BerthCategory("A", 8.0, 90, 2.2, 3.7, 1.9, 0.68),
    BerthCategory("B", 10.0, 100, 2.6, 3.7, 2.4, 0.65),
    BerthCategory("C", 12.0, 95, 3.0, 7.4, 3.0, 0.58),
    BerthCategory("D", 15.0, 80, 3.4, 7.4, 3.9, 0.52),
    BerthCategory("E", 18.0, 45, 3.8, 14.5, 5.0, 0.42),
    BerthCategory("F", 21.0, 25, 4.2, 14.5, 6.2, 0.38),
    BerthCategory("G", 25.0, 15, 4.8, 45.0, 7.5, 0.28),
    BerthCategory("H", 30.0, 10, 5.5, 45.0, 9.5, 0.20),
]


@dataclass
class RealisticMarina:
    berths: list[Berth]
    category_of: list[str]            # category code per berth id
    contract_ids: set[int]            # berths blocked by annual contracts
    walk_order: list[int] = field(default_factory=list)  # naive dock-walk order
    seed: int = 0

    @property
    def n_berths(self) -> int:
        return len(self.berths)

    @property
    def transient_ids(self) -> list[int]:
        return [b.id for b in self.berths if b.id not in self.contract_ids]

    def category_counts(self) -> dict[str, tuple[int, int]]:
        """{code: (total berths, transient berths)}."""
        out: dict[str, tuple[int, int]] = {}
        for cat in CATEGORIES:
            ids = [i for i, c in enumerate(self.category_of) if c == cat.code]
            trans = [i for i in ids if i not in self.contract_ids]
            out[cat.code] = (len(ids), len(trans))
        return out


def build_marina(seed: int = 0) -> RealisticMarina:
    """Build the berth inventory.

    Berth ids run pier by pier from the small categories to the superyacht
    quay, as walking order along the docks. Within each category, rates get
    a small per-berth jitter (position/exposure differences) and contract
    berths are drawn at the category's contract share.
    """
    rng = np.random.default_rng(seed)
    berths: list[Berth] = []
    category_of: list[str] = []
    contract_ids: set[int] = set()

    bid = 0
    for cat in CATEGORIES:
        n_contract = int(round(cat.contract_share * cat.count))
        contract_local = set(rng.choice(cat.count, size=n_contract, replace=False).tolist())
        for k in range(cat.count):
            rate = cat.base_rate * float(rng.uniform(0.97, 1.05))
            berths.append(Berth(
                id=bid,
                width=cat.width * float(rng.uniform(0.99, 1.02)),
                length=cat.max_boat_length,
                depth=cat.depth * float(rng.uniform(0.98, 1.03)),
                price_per_meter=round(rate, 3),
                power_capacity_kw=cat.power_kw,
                berth_type=cat.code,
                max_boats=1,
            ))
            category_of.append(cat.code)
            if k in contract_local:
                contract_ids.add(bid)
            bid += 1

    # Naive dock-walk order for the first-fit baseline: piers are visited in
    # a fixed arbitrary order (real dock layouts are not sorted by size).
    walk = rng.permutation(len(berths)).tolist()

    return RealisticMarina(
        berths=berths,
        category_of=category_of,
        contract_ids=contract_ids,
        walk_order=walk,
        seed=seed,
    )


def contract_season_revenue(marina: RealisticMarina, season_days: int) -> float:
    """Fixed revenue of the annual-contract pool over the season.

    Annual contracts in Greek marinas price at roughly 55-65% of the
    equivalent transient shoulder rate; we use 0.6 with the contracted boat
    assumed to fill ~90% of the berth length.
    """
    total = 0.0
    for i in marina.contract_ids:
        b = marina.berths[i]
        total += 0.6 * b.price_per_meter * (0.9 * b.length) * season_days
    return total
