# 06 — The Final Model: Unified Optimization, Smallest-Berth Packing, Baselines and Online Arrivals

This chapter describes the **final model**, which brings together every layer
developed in the previous chapters into a single optimization model, adds a
**smallest-berth** (space-efficiency) objective, and evaluates the model against
**greedy baselines** and an **online (sequential arrival)** scenario across many
random instances.

It builds directly on:
- [01_model_theory.md](01_model_theory.md) — the basic ILP and Extensions 2.1-2.5.
- [05_model_comparison.md](05_model_comparison.md) — the model progression.

---

## 1. What the final model is

The earlier models were specialised:

| Model | Time | Compat / Power / VIP | Side-by-side | Soft depth | Relocation / Gap |
|---|---|---|---|---|---|
| `model_basic`      | static  | no  | no  | no  | no  |
| `model_extensions` | static  | yes | yes | yes | no  |
| `model_temporal`   | multi-day | compat + power only | no | no | yes |

No single model combined the **temporal dimension** (different boats on the same
berth on different days) with **all** the business and packing extensions. The
final model (`src/models/model_final.py`) does exactly that. It is a single
mixed-integer program over the 3D assignment variable

```
x[i][j][t] in {0, 1}   = 1 if boat j occupies berth i on day t
```

and supports every option through flags:

```
solve_final(inst,
    use_compat, use_utility, use_vip,   # business rules (Extension 2.1)
    side_by_side, soft_depth, penalty_M, # packing / soft depth (Extension 2.2)
    allow_relocation, max_relocations,   # relocation / split-berth (Extension 2.4)
    gap_discount_rate,                   # gap pricing (Extension 2.5)
    short_stay_discount, min_stay_days,  # short-stay pricing (Extension 2.5)
    space_weight,                        # smallest-berth packing
    allow_multi_berth)                   # one boat spanning two adjacent berths
```

Alongside mooring is requested per boat via `boat.mooring_type = "alongside"`
(see Section 2c); it needs no model flag. The premiums for alongside and
multi-berth live in `src/core/revenue.py`.

When `n_days == 1` the model degenerates to the static extended model; with
`n_days > 1` it is the full temporal model. (A unit check confirms that
`final` with `T = 1` reproduces `model_extensions` exactly.)

### 1.1 Objective

```
maximise   sum over i,j,t of  R[i][j][t] * x[i][j][t]
         - relocation penalty
         - gap penalty
         - soft-depth penalty
         - smallest-berth penalty
```

where `R[i][j][t] = price_per_meter[i] * length[j]` (optionally reduced by the
short-stay discount). The first four terms are exactly as defined in chapters
01/05; the smallest-berth term is new (Section 2).

### 1.2 Constraints (temporal generalisation of the extensions)

- **Feasibility / time window:** `x[i][j][t] <= F3[i][j][t]`, where `F3` encodes
  physical fit (width, length, and depth unless `soft_depth`), the stay window
  `[arrival_day, departure_day)`, compatibility and shore-power capacity.
- **One berth per boat per day:** `sum_i x[i][j][t] <= 1`.
- **Per-berth, per-day capacity:**
  - single occupancy: `sum_j x[i][j][t] <= 1`; or
  - side-by-side: `sum_j x[i][j][t] * width[j] <= W[i]` and
    `sum_j x[i][j][t] <= max_boats[i]`.
- **VIP contracts:** a contracted boat is pinned to its berth for the whole stay
  (`x[contract][j][t] = 1`) and excluded from all other berths. A contract berth
  overrides the shore-power restriction (the berth is reserved and provisioned
  for that boat); this override is applied consistently in the verifier.
- **Relocation vs stable:** in stable mode a boat keeps one berth for its whole
  stay; in relocation mode it may change berth up to `max_relocations` times,
  each move costing `relocation_cost`. The relocation count is measured **only
  for berth changes within the stay window** — arrival and departure at the
  window edges are not mistaken for relocations (a subtlety that, if ignored,
  makes a VIP-pinned boat infeasible under a relocation budget).

---

## 2. Smallest-berth packing (space efficiency)

The requirement is that **each boat should go into the smallest available berth
that fits**, so large berths stay free for large boats. This is implemented as a
soft penalty on wasted berth length:

```
smallest-berth penalty = space_weight * sum over i,j,t of  price[i] * (L[i] - l[j]) * x[i][j][t]
```

`(L[i] - l[j])` is the unused metres of berth length; multiplying by the berth's
`price_per_meter` expresses it as the **lost revenue potential of the empty
length**, putting the penalty on the same scale as revenue. `space_weight` is a
single dial:

- `space_weight = 0` — pure revenue maximisation.
- small `space_weight` — breaks near-ties toward smaller berths.
- larger `space_weight` — visibly trades revenue for compactness.

### 2.1 Why a weight, not a tie-break

Revenue is `price[i] * length[j]`, so it **depends on which berth** a boat takes.
A tiny epsilon tie-break is therefore invisible: the model always prefers the
higher-priced berth, and price differences swamp any epsilon. The penalty must be
a genuine, tunable objective term on the revenue scale to influence the choice.
This makes "smallest berth" a controllable trade-off rather than a free
guarantee — which is the honest situation when berths are priced differently.

### 2.2 The trade-off, measured

`space_weight` sweep on an 8-berth, 16-boat, 14-day instance
(`experiments/final_comparison.py`, Part B):

| space_weight | gross revenue | wasted length (m) |
|---|---|---|
| 0.0 - 0.2 | 90,966 | 662 |
| 0.3 - 1.0 | 77,351 | 335 |

Below a threshold the revenue-optimal packing is already tight and the penalty
changes nothing; past the threshold the model halves the wasted length, at a
~15% revenue cost. The frontier is shown in `results/final_space_tradeoff.png`.

The **pure** smallest-berth rule lives in the greedy best-fit baseline
(Section 3), which always chooses the smallest fitting berth regardless of price.

---

## 2b. Multi-berth spanning (oversized boats)

A boat too wide for any single berth may occupy **two adjacent berths**. This is
modelled with extra binary variables `z[k][j][t] = 1` if boat j spans the pair
`(k, k+1)` on day t. A boat is served by either one single berth or one span per
day (`sum_i x[i][j][t] + sum_k z[k][j][t] <= 1`), and a spanning boat consumes
both berths fully (no sharing). Spanning is allowed only where the boat fits the
**combined** width and the shorter berth's length/depth, and is compatible and
powered on **both** berths; VIP-contracted boats never span.

Because it ties up two berths, a span is billed at the average of the two berths'
prices with a **+25% premium** (`MULTI_BERTH_PREMIUM` in `core/revenue.py`),
charged once per day. Enable it with `allow_multi_berth=True`.

Demo (`experiments/final_features.py`, four 4 m berths, one 7 m-beam boat):

| | boats served | revenue |
|---|---|---|
| multi-berth OFF | 2 / 3 (wide boat rejected) | 9,120 |
| multi-berth ON  | 3 / 3 (wide boat spans berths 0-1) | 17,520 |

## 2c. Alongside mooring (plagiodetisi)

A boat may request **alongside** (parallel) mooring via
`boat.mooring_type = "alongside"`. Moored side-on, it lies along the berth so its
**length** — not its beam — occupies the shared-width budget. Since length is
usually much larger than beam, an alongside boat consumes far more shared space
(`sum_j consumed[j] * x[i][j][t] <= W[i]`, with `consumed = length` for alongside
boats), and it is charged a **+60% premium** (`ALONGSIDE_PREMIUM`).

Demo (two 12 m berths, eight 8 m boats, two requesting alongside, side-by-side
on): all stern-to serves 8 boats for 19,200; with two alongside requests the
hogged width drops it to 6 boats / 15,840 even though the alongside boats pay the
premium. Alongside is therefore a premium, space-hungry option best suited to
wide berths or quays.

## 2d. Split berth (via relocation)

If no single berth is free for a boat's whole stay, the booking can be **split**
across berths — e.g. berth 1 for days 0-1 then berth 0 for days 2-3. This is
exactly the relocation feature (`allow_relocation=True`): the boat is present for
its whole window, changing berth up to `max_relocations` times. In the demo, a
boat needing days 0-3 is rejected under stable assignment (neither berth is free
the whole time) but served when relocation lets it split across the two berths.

---

## 3. Greedy baselines

`src/heuristics/baselines.py` provides three offline heuristics. Each respects the
same feasibility rules as the MILP (physical fit, compatibility, power, VIP,
per-day capacity) and returns a `SolveResult` of the same shape, so it can be
verified and visualised identically.

- **first-fit** — "if it fits, put it there": place each boat in the
  lowest-index berth that is free for its whole stay.
- **best-fit** — place each boat in the **smallest fitting free berth**. This is
  the pure smallest-berth heuristic.
- **revenue-priority** — sort boats by maximum achievable revenue
  (`length * best feasible price`) and place the most valuable first (best-fit
  placement by default).

### 3.1 Best-fit really is the smallest-berth rule

On a high-demand instance (8 berths, 16 boats, 14 days):

| policy | revenue | boats served | wasted length / slot (m) |
|---|---|---|---|
| first-fit | 73,997 | 6 | 16.13 |
| best-fit  | 85,275 | 7 | 14.54 |

Best-fit packs each boat into a tighter berth (lower waste per occupied
berth-day), which keeps large berths free, lets it serve **one more boat**, and
earns **15% more** than first-fit. This is the operational value of the
smallest-berth rule.

---

## 4. Online arrivals (requests do not all arrive at once)

The offline models assume every request is known up front. In reality requests
arrive over time. `src/online_simulator.py` models this:

- Requests arrive one-by-one in arrival-day order (random tie-break).
- Each request is placed **immediately and irrevocably** with **no knowledge of
  future requests**, or rejected if no berth is free for its whole stay.
- VIP contracts are treated as known reservations and committed up front.

The natural yardstick is the **offline optimum** (`solve_final` on the full
instance), which can see all requests. The ratio

```
competitive ratio = online realised revenue / offline optimum revenue
```

is the "value of knowing the future". Note that online `revenue-priority` is
identical to online `best-fit`, because future requests cannot be reordered.

### 4.1 Result

Mean competitive ratio over 5 seeds (`final_online_vs_offline.png`):

| demand | online first-fit | online best-fit |
|---|---|---|
| 0.5x | 88% | 98% |
| 1.0x | 83% | 92% |
| 2.0x | 82% | 88% |
| 3.0x | 86% | 93% |

Even without lookahead, an online best-fit policy captures 88-98% of the offline
optimum; first-fit trails it by 5-10 points. The gap is the cost of committing to
each boat before seeing the rest of the season.

---

## 5. Main comparison

`experiments/final_comparison.py`, Part A — mean gross revenue over 5 seeds, 8
berths, 14 days. All configurations keep compatibility, shore power and VIP on,
so every method is business-feasible (all rows verify OK).

| demand | base | side-by-side | soft-penalty | full-mix | greedy best-fit | online best-fit |
|---|---|---|---|---|---|---|
| 1.0x | 45,532 | 45,814 | 48,992 | 49,274 | 41,337 | 41,018 |
| 2.0x | 89,361 | 91,057 | 93,633 | 98,959 | 74,899 | 79,817 |
| 3.0x | 113,749 | 131,743 | 129,471 | 151,697 | 105,417 | 106,559 |

Reading the table (`results/final_revenue.png`, `results/final_utilization.png`):

1. **The optimizer beats every heuristic at every demand level.** At 3x demand
   the full-mix final model earns 44% more than greedy best-fit and online.
2. **Side-by-side matters only when berths are scarce.** Negligible at 1x,
   +16% at 3x — it adds capacity precisely when boats would otherwise be turned
   away.
3. **Soft depth and the mix add the most when demand is high**, by squeezing in
   boats that a hard model would reject.
4. **Greedy is fast but myopic.** Greedy/online solve in milliseconds; the MILP
   takes up to ~4 s here, and pays for it in revenue. Greedy revenue-priority can
   even underperform best-fit, because committing a long high-value boat early
   can block several smaller boats worth more together.

---

## 6. Implementation notes and changes to existing files

Source code is organised under `src/core/`, `src/models/`, and `src/heuristics/`
(Phase 3 folder restructure):

- `src/models/model_final.py` — unified model (`build_final_model`, `solve_final`,
  `build_waste_length_matrix`, multi-berth spanning via `z[k,j,t]`).
- `src/core/revenue.py` — shared revenue matrices, `ALONGSIDE_PREMIUM` (+60%),
  `MULTI_BERTH_PREMIUM` (+25%), `consumed_width()` for alongside mooring.
- `src/heuristics/baselines.py` — greedy heuristics and the shared `gross_revenue` /
  `boat_fits_berth` helpers.
- `src/heuristics/online_simulator.py` — `simulate_online` and `OnlineMetrics`.
- `src/core/solver.py` — the unified `solve()` gained a `mode="final"` branch and the
  `short_stay_discount`, `min_stay_days`, `space_weight` parameters.
- `src/core/verifier.py` — the temporal verification path now also checks
  compatibility and VIP contracts, enforces the per-day `max_boats` capacity and
  the side-by-side total-width limit, applies the VIP power override, treats
  soft-depth shortfalls as intentional (paid for in the objective) rather than
  hard violations, and validates multi-berth span assignments.
- `src/core/visualizer.py` — added `plot_grouped_metric` (grouped bars with error
  bars) and `plot_pareto` (trade-off frontier).
- `src/core/data_generator.py` — added `make_multiberth_demo_instance()` and
  `make_alongside_demo_instance()` for Phase 3 feature demos.

### 6.1 A note on comparing methods fairly

The MILP `objective_value` is **net of penalties**; the greedy and online
`objective_value` is raw realised revenue. Always compare methods on
**gross realised revenue** via `gross_revenue(inst, assignment)`, never on the
raw objective, to avoid an apples-to-oranges comparison. The verifier confirms
that `gross - penalty == reported objective` for every MILP result.

### 6.2 Solver scaling

The model uses CVXPY with the GLPK_MI backend. Variable count is `n*m*T` plus
auxiliary variables for relocation, gap and soft depth. The heaviest
configurations (side-by-side + soft depth, or relocation, at high demand) solve
in a few seconds at the sizes used here (8 berths, up to 24 boats, 14 days);
larger instances grow quickly, so keep experiment sizes modest and report solve
time honestly.

---

## 7. How to run

**Phase 3 feature demos** (multi-berth, alongside, split berth):

```bash
python -X utf8 experiments/final_features.py
```

Prints three targeted demos with verification status and saves Gantt charts to
`results/final_multiberth_gantt.png` and `results/final_split_gantt.png`.

**Full benchmark** (final model vs greedy vs online):

```bash
python -X utf8 experiments/final_comparison.py
```

Outputs the Part A / B / C tables and writes four plots to `results/`:
`final_revenue.png`, `final_utilization.png`, `final_online_vs_offline.png`,
`final_space_tradeoff.png`.
