from __future__ import annotations
import numpy as np
from .data_model import Berth, Boat, MarinaInstance

ALLOWED_PAIRS: dict[str, list[str]] = {
    "sailboat":  ["standard", "vip", "sailing"],
    "motorboat": ["standard", "vip", "motor"],
    "yacht":     ["vip"],
}

BERTH_TYPES = ["standard", "vip", "sailing", "motor"]
BOAT_TYPES  = ["sailboat", "motorboat", "yacht"]


def generate_instance(
    n_berths: int,
    n_boats: int,
    seed: int = 42,
    vip_fraction: float = 0.1,
    n_days: int = 1,
    alongside_fraction: float = 0.0,
) -> MarinaInstance:
    rng = np.random.default_rng(seed)

    berths = []
    for i in range(n_berths):
        btype = rng.choice(BERTH_TYPES)
        # 60% of berths have shore power; capacity in common marina tiers: 16A~3.7kW, 32A~7.4kW, 63A~14.5kW
        power_kw = float(rng.choice([0.0, 0.0, 3.7, 7.4, 14.5, 32.0])) if rng.random() > 0.4 else 0.0
        berths.append(Berth(
            id=i,
            width=float(rng.uniform(3, 12)),
            length=float(rng.uniform(8, 40)),
            depth=float(rng.uniform(1.5, 5.0)),
            price_per_meter=float(rng.uniform(50, 200)),
            power_capacity_kw=power_kw,
            berth_type=btype,
            max_boats=2,
        ))

    max_w = max(b.width  for b in berths)
    max_l = max(b.length for b in berths)
    max_d = max(b.depth  for b in berths)

    boats = []
    n_vip = max(1, int(vip_fraction * n_boats))
    for j in range(n_boats):
        scale = 0.85 if rng.random() < 0.7 else 1.1
        btype = rng.choice(BOAT_TYPES)
        # 40% of boats need shore power; requirement sampled from realistic values
        power_req = float(rng.choice([0.0, 3.7, 7.4, 14.5, 32.0, 50.0])) if rng.random() > 0.6 else 0.0
        boats.append(Boat(
            id=j,
            width=float(rng.uniform(1.5, max_w * scale)),
            length=float(rng.uniform(4.0, max_l * scale)),
            draft=float(rng.uniform(0.5, max_d * scale)),
            power_required_kw=power_req,
            boat_type=btype,
            contract_berth_id=None,
            arrival_day=int(rng.integers(0, max(1, n_days - 1))) if n_days > 1 else 0,
            departure_day=0,  # filled below
            relocation_cost=float(rng.uniform(20, 100)),
        ))

    for boat in boats:
        max_start = max(1, n_days)
        stay = int(rng.integers(1, max(2, n_days - boat.arrival_day + 1)))
        boat.departure_day = min(boat.arrival_day + stay, n_days)
        if boat.departure_day <= boat.arrival_day:
            boat.departure_day = boat.arrival_day + 1

    compat = build_compat_matrix(berths, boats)

    vip_indices = rng.choice(n_boats, size=n_vip, replace=False).tolist()
    for j in vip_indices:
        boat = boats[j]
        valid_berths = [
            i for i, berth in enumerate(berths)
            if (compat[i, j] == 1
                and boat.width  <= berth.width
                and boat.length <= berth.length
                and boat.draft  <= berth.depth)
        ]
        if valid_berths:
            boats[j].contract_berth_id = int(rng.choice(valid_berths))

    # A fraction of (non-VIP) boats request alongside mooring (plagiodetisi).
    if alongside_fraction > 0.0:
        eligible = [j for j in range(n_boats) if boats[j].contract_berth_id is None]
        n_along = int(round(alongside_fraction * n_boats))
        for j in rng.choice(eligible, size=min(n_along, len(eligible)), replace=False).tolist():
            boats[j].mooring_type = "alongside"

    return MarinaInstance(berths=berths, boats=boats, compat_matrix=compat, n_days=n_days)


def build_compat_matrix(berths: list[Berth], boats: list[Boat]) -> np.ndarray:
    n, m = len(berths), len(boats)
    compat = np.ones((n, m), dtype=float)
    for i, berth in enumerate(berths):
        for j, boat in enumerate(boats):
            allowed = ALLOWED_PAIRS.get(boat.boat_type, [])
            if berth.berth_type not in allowed:
                compat[i, j] = 0.0
    return compat


def generate_gapfill_instance(
    n_berths: int,
    n_long_boats: int,
    n_short_boats: int,
    n_days: int,
    long_min: int = 5,
    long_max: int = 10,
    short_min: int = 1,
    short_max: int = 4,
    seed: int = 0,
) -> MarinaInstance:
    """
    Instance with two boat populations:
    - Long-stay boats (5-10 days): fill berths for long stretches.
    - Short-stay boats (1-4 days): represent discount-attracted demand to fill gaps.
    """
    rng = np.random.default_rng(seed)

    berths = []
    for i in range(n_berths):
        power_kw = float(rng.choice([0.0, 3.7, 7.4, 14.5, 32.0])) if rng.random() > 0.4 else 0.0
        berths.append(Berth(
            id=i,
            width=float(rng.uniform(5, 12)),
            length=float(rng.uniform(15, 35)),
            depth=float(rng.uniform(2.0, 4.5)),
            price_per_meter=float(rng.uniform(80, 180)),
            power_capacity_kw=power_kw,
            berth_type="standard",
            max_boats=1,
        ))

    boats = []
    bid = 0

    for _ in range(n_long_boats):
        w = float(rng.uniform(3, 9))
        l = float(rng.uniform(10, 28))
        d = float(rng.uniform(1.0, 3.5))
        arr = int(rng.integers(0, n_days - long_min))
        stay = int(rng.integers(long_min, long_max + 1))
        dep = min(arr + stay, n_days)
        boats.append(Boat(id=bid, width=w, length=l, draft=d,
                          arrival_day=arr, departure_day=dep))
        bid += 1

    for _ in range(n_short_boats):
        w = float(rng.uniform(2, 7))
        l = float(rng.uniform(5, 18))
        d = float(rng.uniform(0.5, 2.5))
        arr = int(rng.integers(0, n_days - short_min))
        stay = int(rng.integers(short_min, short_max + 1))
        dep = min(arr + stay, n_days)
        boats.append(Boat(id=bid, width=w, length=l, draft=d,
                          arrival_day=arr, departure_day=dep))
        bid += 1

    return MarinaInstance(berths=berths, boats=boats, n_days=n_days)


def make_hand_crafted_instance() -> MarinaInstance:
    berths = [
        Berth(id=0, width=5.0,  length=10.0, depth=2.0, price_per_meter=100.0),
        Berth(id=1, width=8.0,  length=20.0, depth=3.0, price_per_meter=150.0),
    ]
    boats = [
        Boat(id=0, width=4.0, length=8.0,  draft=1.5),
        Boat(id=1, width=7.0, length=15.0, draft=2.5),
        Boat(id=2, width=3.0, length=6.0,  draft=1.0),
    ]
    return MarinaInstance(berths=berths, boats=boats)


def make_multiberth_demo_instance(n_days: int = 4) -> MarinaInstance:
    """Four narrow adjacent berths plus one boat too wide for any single berth.

    Boat 0 (beam 7 m) fits no single 4 m berth but fits an adjacent pair
    (4 + 4 = 8 m). With multi-berth spanning it is served (at a premium);
    without it, it is rejected.
    """
    berths = [
        Berth(id=i, width=4.0, length=18.0, depth=3.0, price_per_meter=120.0,
              berth_type="standard", max_boats=2)
        for i in range(4)
    ]
    boats = [
        Boat(id=0, width=7.0, length=14.0, draft=2.0, boat_type="motorboat",
             arrival_day=0, departure_day=n_days),
        Boat(id=1, width=3.0, length=10.0, draft=1.5, boat_type="sailboat",
             arrival_day=0, departure_day=n_days),
        Boat(id=2, width=3.0, length=9.0,  draft=1.5, boat_type="sailboat",
             arrival_day=0, departure_day=n_days),
    ]
    compat = build_compat_matrix(berths, boats)
    return MarinaInstance(berths=berths, boats=boats, compat_matrix=compat, n_days=n_days)


def make_alongside_demo_instance(n_days: int = 3) -> MarinaInstance:
    """Two wide berths with small boats, some requesting alongside mooring.

    A stern-to boat consumes its 3 m beam of the 12 m width budget (four share a
    berth); an alongside boat consumes its 8 m length (it hogs the berth) and
    pays the alongside premium. Best shown with side_by_side=True.
    """
    berths = [
        Berth(id=i, width=12.0, length=30.0, depth=4.0, price_per_meter=100.0,
              berth_type="standard", max_boats=4)
        for i in range(2)
    ]
    boats = []
    for bid in range(6):
        boats.append(Boat(id=bid, width=3.0, length=8.0, draft=1.5, boat_type="sailboat",
                          arrival_day=0, departure_day=n_days))
    for bid in range(6, 8):
        boats.append(Boat(id=bid, width=3.0, length=8.0, draft=1.5, boat_type="sailboat",
                          arrival_day=0, departure_day=n_days, mooring_type="alongside"))
    compat = build_compat_matrix(berths, boats)
    return MarinaInstance(berths=berths, boats=boats, compat_matrix=compat, n_days=n_days)
