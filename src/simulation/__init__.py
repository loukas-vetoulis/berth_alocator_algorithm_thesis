"""Phase 4: dynamic booking simulation.

calendar.py  Berth-by-day occupancy calendar with gap (fragmentation) queries.
policies.py  Allocation policies: online greedy rules and the batch MILP
             (HiGHS) with tunable objective weights, plus the offline oracle.
engine.py    Event-driven season simulator: requests are revealed on their
             booking day and decided by the policy, never all at once.
metrics.py   Season-level outcome metrics.
"""
