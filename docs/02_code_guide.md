# Code Guide — Source Files

This document explains every file under `src/`, its purpose, key functions, and any non-obvious design decisions. Source code is organised in three packages:

- `src/core/` — shared data types, revenue logic, solver entry point, verifier, visualizer
- `src/models/` — ILP model builders (basic → extensions → temporal → final)
- `src/heuristics/` — greedy baselines and online simulator

Legacy duplicate files may still exist at the flat `src/` root from before the Phase 3 refactor; the active code lives in the packages above.

---

## `src/core/data_model.py`

Defines the four core dataclasses used throughout the project. No logic — pure data containers.

### `Berth`
Represents one marina berth (parking slot).

| Field | Type | Meaning |
|---|---|---|
| `id` | int | Index (0-based) |
| `width` | float | W_i — maximum boat beam it can accept |
| `length` | float | L_i — maximum boat length |
| `depth` | float | D_i — water depth |
| `price_per_meter` | float | p_i — EUR per metre of boat length per day |
| `power_capacity_kw` | float | Shore power capacity in kW. 0 = no power. Common values: 3.7, 7.4, 14.5, 32 kW |
| `berth_type` | str | `"standard"`, `"vip"`, `"sailing"`, `"motor"` |
| `max_boats` | int | k_i — maximum boats in side-by-side mode (default 1) |

### `Boat`
Represents one boat requesting a berth.

| Field | Type | Meaning |
|---|---|---|
| `id` | int | Index (0-based) |
| `width` | float | w_j — beam of the boat |
| `length` | float | l_j — length of the boat |
| `draft` | float | d_j — depth below waterline |
| `power_required_kw` | float | Shore power requirement in kW. 0 = no power needed. Large yachts can need 50 kW+ |
| `boat_type` | str | `"sailboat"`, `"motorboat"`, `"yacht"` |
| `contract_berth_id` | int or None | For VIP boats: the berth they are guaranteed |
| `arrival_day` | int | s_j — first day of stay (0-indexed) |
| `departure_day` | int | e_j — day after last day of stay |
| `relocation_cost` | float | c_j — cost charged when boat changes berth |
| `mooring_type` | str | `"stern_to"` (default) or `"alongside"` (parallel / πλαγιοδέτηση) |

### `MarinaInstance`
Bundles everything the solver needs.

| Field | Meaning |
|---|---|
| `berths` | List of Berth objects |
| `boats` | List of Boat objects |
| `compat_matrix` | numpy array shape (n, m): 1 if boat j allowed in berth i |
| `n_days` | T — length of the season in days (1 for static models) |

### `SolveResult`
Returned by every solve function.

| Field | Meaning |
|---|---|
| `status` | CVXPY solver status: `"optimal"`, `"infeasible"`, `"unbounded"` |
| `objective_value` | The objective function value (net revenue after penalties) |
| `assignment` | numpy int array, shape (n,m) or (n,m,T). Entry = 1 if assigned |
| `solve_time` | Wall-clock seconds taken to solve |
| `model_name` | String label like `"basic"` or `"final[side-by-side]"` |
| `penalty_value` | Total penalty subtracted from gross revenue (for temporal/final models) |

---

## `src/core/revenue.py`

Canonical revenue definition shared by the model, verifier, and heuristics. All methods must use `realized_revenue()` (or the `gross_revenue` alias in baselines) for fair comparison — the MILP `objective_value` is net of penalties.

### Constants

| Constant | Value | Meaning |
|---|---|---|
| `ALONGSIDE_PREMIUM` | 0.60 | +60% for alongside mooring |
| `MULTI_BERTH_PREMIUM` | 0.25 | +25% for spanning two adjacent berths |

### Key functions

- **`single_revenue_matrix(inst)`** — `R[i,j] = price_i × length_j`, with alongside premium folded in per boat.
- **`span_revenue_matrix(inst)`** — `Rspan[k,j]` for boat j spanning pair (k, k+1); average price of the two berths × length × multi-berth premium.
- **`consumed_width(inst)`** — width budget per boat: `length` if alongside, else `beam`. Used in side-by-side capacity constraints.
- **`realized_revenue(inst, assignment)`** — gross revenue of a 2D or 3D assignment; counts each boat-day once (span charge, not per-berth).

---

## `src/core/data_generator.py`

Generates synthetic marina instances for testing.

### `generate_instance(n_berths, n_boats, seed, vip_fraction, n_days, alongside_fraction=0.0)`

General-purpose generator. Strategy:
- Berth dimensions sampled from realistic ranges (width 3–12 m, length 8–40 m, depth 1.5–5 m).
- About 70 % of boats are sized to fit at least one berth (scaled to 0.85× max berth dimensions). The remaining 30 % are deliberately oversized — they represent boats that cannot fit anywhere, making the optimisation non-trivial.
- `compat_matrix` is built from an `ALLOWED_PAIRS` dict that maps boat types to berth types they can occupy.
- VIP boats are assigned `contract_berth_id` only from berths they physically fit AND are compatible with — otherwise the ILP would be infeasible.
- For temporal instances (`n_days > 1`), arrival and departure days are sampled uniformly.
- `alongside_fraction` sets the fraction of boats with `mooring_type="alongside"`.

### `generate_gapfill_instance(...)`

Creates an instance with two distinct boat populations (long-stay and short-stay boats). Used by `run_full_demo.py`.

### `make_hand_crafted_instance()`

Fixed 2-berth / 3-boat instance with known optimal (revenue = 3050). Used in `run_basic.py`.

### `make_multiberth_demo_instance(n_days=4)` (Phase 3)

Four 4 m berths, one 7 m-beam boat too wide for any single berth. Used in `final_features.py` demo 1.

### `make_alongside_demo_instance(n_days=3)` (Phase 3)

Two 12 m berths, eight 8 m boats, two requesting alongside mooring. Used in `final_features.py` demo 2.

---

## `src/models/model_basic.py`

Implements the basic static ILP (Extension 0 from the thesis).

### `build_feasibility_mask(inst) -> np.ndarray`

Precomputes the binary matrix `F[i][j]` = 1 if boat j physically fits in berth i (all three dimension checks pass). This avoids adding 3 * n * m individual constraints and instead encodes all dimension infeasibilities as a single matrix inequality `x <= F`.

### `build_basic_model(inst) -> (cp.Problem, cp.Variable)`

Constructs the CVXPY problem with variable `x[i,j]`, revenue matrix, and one-berth-per-boat / one-boat-per-berth constraints.

### `solve_basic(inst, solver, verbose) -> SolveResult`

Builds, solves, rounds the result, and returns a `SolveResult`.

---

## `src/models/model_extensions.py`

Adds business-rule constraints on top of the basic model (Extensions 2.1 and 2.2).

### Extension functions

- **`add_compatibility`** — enforces `compat_matrix`
- **`add_utility_services`** — shore power capacity per berth
- **`add_vip_contracts`** — pins VIP boats to contract berths

### `build_extended_model(inst, use_compat, use_utility, use_vip, side_by_side, soft_depth, penalty_M)`

The main builder. Flags control which extensions are active. Side-by-side replaces single occupancy with a width-sum constraint. Soft depth introduces slack variables.

### `solve_extended(inst, ...) -> SolveResult`

Convenience wrapper returning a `SolveResult` with a descriptive `model_name`.

---

## `src/models/model_temporal.py`

Implements the temporal model (Extensions 2.3, 2.4, 2.5).

### Key functions

- **`build_window_mask(inst)`** — 3D stay-window mask
- **`build_feasibility_mask_3d(inst)`** — combines physical fit with stay window
- **`build_temporal_model(inst, allow_relocation, ...)`** — 3D variable `x[i,j,t]`, relocation variables, gap/short-stay pricing
- **`solve_temporal(inst, ...) -> SolveResult`**

**Important:** The stability constraint is only applied within `[arrival_day, departure_day - 2]` for each boat. Applying it outside the stay window would incorrectly force days within the window to zero.

---

## `src/models/model_final.py` (Phase 3)

Unified model combining every extension from Phases 1–2 plus smallest-berth packing, multi-berth spanning, and alongside mooring premiums.

### Variables

- **`x[i,j,t]`** — boat j in berth i on day t
- **`z[k,j,t]`** — boat j spans adjacent pair (k, k+1) on day t (when `allow_multi_berth=True`)
- **`r_var[j,t]`** — relocation indicator (when `allow_relocation=True`)
- **`gap[j,t]`**, **`slack[i,j,t]`** — gap and soft-depth slacks

### Key functions

- **`build_waste_length_matrix(inst)`** — `W[i,j] = L[i] - l[j]` for smallest-berth penalty
- **`build_final_feasibility_mask(inst, ...)`** — 3D feasibility including compat, power, VIP, soft depth
- **`build_span_mask(inst, ...)`** — which boats may span which adjacent berth pairs
- **`build_final_model(inst, ...)`** — constructs the full CVXPY problem
- **`solve_final(inst, use_compat, use_utility, use_vip, side_by_side, soft_depth, allow_relocation, allow_multi_berth, space_weight, ...) -> SolveResult`**

Alongside mooring needs no flag — set `boat.mooring_type = "alongside"` per boat. Premiums come from `src/core/revenue.py`.

When `n_days == 1` the model degenerates to the static extended model; with `n_days > 1` it is the full temporal model.

---

## `src/core/solver.py`

Thin unified entry point. Calls the right model builder based on the `mode` argument.

```python
solve(inst, mode="basic")
solve(inst, mode="extended", extensions=["compat","utility","vip"])
solve(inst, mode="temporal", allow_relocation=True)
solve(inst, mode="final", side_by_side=True, space_weight=0.3)
```

Useful when iterating over model variants without importing multiple modules.

---

## `src/heuristics/baselines.py`

Three offline greedy heuristics for comparison against the MILP. Each respects physical fit, compatibility, power, VIP, and per-day capacity, but places boats one-at-a-time with no lookahead. **Cannot** do split-berth or multi-berth spanning.

### Key functions

- **`gross_revenue(inst, assignment)`** — alias for `realized_revenue()` from `revenue.py`
- **`boat_fits_berth(inst, i, j)`** — single-berth physical and business feasibility
- **`first_fit(inst, ...)`** — lowest-index berth free for the whole stay
- **`best_fit(inst, ...)`** — smallest fitting free berth (pure smallest-berth rule)
- **`revenue_priority(inst, ...)`** — sort by max achievable revenue, then best-fit placement

---

## `src/heuristics/online_simulator.py`

Models sequential arrival: requests arrive one-by-one, each placed immediately and irrevocably with no knowledge of future requests.

### Key functions

- **`arrival_order(inst, seed)`** — sort boats by arrival day (random tie-break)
- **`simulate_online(inst, policy, seed, ...)`** — run an online policy; returns `SolveResult` and `OnlineMetrics`

The competitive ratio (online revenue / offline optimum) measures the cost of not knowing future requests.

---

## `src/core/verifier.py`

Post-solve verification. After every solve, `verify_solution` checks that the returned assignment satisfies all enforced constraints.

### Checks performed (static model)

1. Width, length, depth fit for every assigned (berth, boat) pair
2. No boat assigned to more than one berth
3. No berth over its capacity (`max_boats`)
4. VIP boats in their designated berths
5. No assignment where `compat_matrix[i][j] == 0`
6. Gross revenue minus penalty matches the reported objective within 0.1% tolerance

### Checks performed (temporal / final model)

Same as above, plus:
- No boat present outside its `[arrival_day, departure_day)` window
- No berth occupied by more than one boat on the same day (or width budget exceeded in side-by-side mode)
- Multi-berth span assignments validated when `multiberth` appears in `model_name`
- Soft-depth shortfalls treated as intentional (paid for in objective), not hard violations

### `VerificationReport`

```python
@dataclass
class VerificationReport:
    passed: bool
    violations: list[str]
    computed_revenue: float   # gross revenue recomputed from assignment
    reported_revenue: float   # objective_value from solver
```

---

## `src/core/visualizer.py`

Plotting and console output functions. All matplotlib plots are saved to a file if `save_path` is given.

### Functions

| Function | Purpose |
|---|---|
| `print_assignment_table(inst, result)` | Console table: berth, boat, day, revenue, dimensions |
| `plot_marina_layout(inst, result, save_path)` | Static 2D assignment diagram |
| `plot_temporal_gantt(inst, result, save_path)` | Gantt chart: days × berths |
| `plot_revenue_comparison(results_dict, save_path)` | Bar chart across multiple `SolveResult` objects |
| `plot_grouped_metric(...)` | Grouped bars with error bars (used in `final_comparison.py`) |
| `plot_pareto(...)` | Trade-off frontier plot (revenue vs wasted length) |
