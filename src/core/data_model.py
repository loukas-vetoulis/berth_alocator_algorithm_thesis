from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np


@dataclass
class Berth:
    id: int
    width: float
    length: float
    depth: float
    price_per_meter: float
    power_capacity_kw: float = 0.0  # 0 = no shore power; >0 = kW available (implies 3-phase)
    berth_type: str = "standard"
    max_boats: int = 1  # k_i for side-by-side mode


@dataclass
class Boat:
    id: int
    width: float
    length: float
    draft: float
    power_required_kw: float = 0.0  # 0 = no power needed; >0 = kW required from berth
    boat_type: str = "sailboat"
    contract_berth_id: int | None = None
    arrival_day: int = 0
    departure_day: int = 1
    relocation_cost: float = 50.0
    mooring_type: str = "stern_to"  # "stern_to" (default) or "alongside" (parallel / plagiodetisi)


@dataclass
class MarinaInstance:
    berths: list[Berth]
    boats: list[Boat]
    compat_matrix: np.ndarray | None = None  # shape (n, m), binary
    n_days: int = 1


@dataclass
class SolveResult:
    status: str
    objective_value: float | None
    assignment: np.ndarray | None  # shape (n,m) or (n,m,T)
    solve_time: float
    model_name: str
    penalty_value: float = 0.0  # total penalty subtracted from gross revenue
