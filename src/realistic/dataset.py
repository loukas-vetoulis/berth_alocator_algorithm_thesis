"""Scenario assembly and CSV export for the realistic datasets.

A dataset = one marina inventory + one seasonal booking stream. Scenarios
differ in the demand multiplier; the marina is shared. Everything is fully
deterministic given (scenario, seed), so experiments regenerate datasets
instead of depending on files, and the CSVs exist for inspection and for
the report appendix.
"""
from __future__ import annotations
import csv
import json
import os
from dataclasses import dataclass

from .marina import RealisticMarina, build_marina
from .demand import BookingRequest, generate_requests, SEASON_DAYS, SEASON_START

SCENARIOS = {
    "low":  0.70,   # quiet season
    "base": 1.00,   # normal season
    "high": 1.30,   # record season
}

MARINA_SEED = 2025


@dataclass
class RealisticDataset:
    marina: RealisticMarina
    requests: list[BookingRequest]
    scenario: str
    demand_mult: float
    seed: int


def build_dataset(scenario: str = "base", seed: int = 7) -> RealisticDataset:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario {scenario!r}; expected one of {list(SCENARIOS)}")
    marina = build_marina(seed=MARINA_SEED)
    requests = generate_requests(seed=seed, demand_mult=SCENARIOS[scenario])
    return RealisticDataset(
        marina=marina,
        requests=requests,
        scenario=scenario,
        demand_mult=SCENARIOS[scenario],
        seed=seed,
    )


def save_dataset(ds: RealisticDataset, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)

    berth_path = os.path.join(out_dir, "berths.csv")
    with open(berth_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["berth_id", "category", "length_m", "width_m", "depth_m",
                    "base_rate_eur_per_m_day", "power_kw", "annual_contract"])
        for b, cat in zip(ds.marina.berths, ds.marina.category_of):
            w.writerow([b.id, cat, f"{b.length:.1f}", f"{b.width:.2f}", f"{b.depth:.2f}",
                        f"{b.price_per_meter:.3f}", b.power_capacity_kw,
                        int(b.id in ds.marina.contract_ids)])

    req_path = os.path.join(out_dir, f"requests_{ds.scenario}_seed{ds.seed}.csv")
    with open(req_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["request_id", "segment", "boat_type", "length_m", "beam_m",
                    "draft_m", "power_kw", "booking_day", "arrival_day",
                    "departure_day", "nights", "lead_days"])
        for r in ds.requests:
            w.writerow([r.id, r.segment, r.boat_type, r.length, r.beam, r.draft,
                        r.power_kw, r.booking_day, r.arrival_day, r.departure_day,
                        r.nights, r.lead_days])

    meta = {
        "scenario": ds.scenario,
        "demand_mult": ds.demand_mult,
        "request_seed": ds.seed,
        "marina_seed": ds.marina.seed,
        "n_berths": ds.marina.n_berths,
        "n_transient_berths": len(ds.marina.transient_ids),
        "n_contract_berths": len(ds.marina.contract_ids),
        "n_requests": len(ds.requests),
        "season_start": SEASON_START.isoformat(),
        "season_days": SEASON_DAYS,
    }
    with open(os.path.join(out_dir, f"meta_{ds.scenario}_seed{ds.seed}.json"),
              "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
