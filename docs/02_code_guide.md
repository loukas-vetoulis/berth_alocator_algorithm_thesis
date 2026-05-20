# Code Guide — Source Files

This document explains every file in `src/`, its purpose, key functions, and any non-obvious design decisions.

---

## `src/data_model.py`

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
| `model_name` | String label like `"basic"` or `"temporal[stable]"` |
| `penalty_value` | Total penalty subtracted from gross revenue (for temporal models) |

---

## `src/data_generator.py`

Generates synthetic marina instances for testing. Three functions:

### `generate_instance(n_berths, n_boats, seed, vip_fraction, n_days)`

General-purpose generator. Strategy:
- Berth dimensions sampled from realistic ranges (width 3–12 m, length 8–40 m, depth 1.5–5 m).
- About 70 % of boats are sized to fit at least one berth (scaled to 0.85× max berth dimensions). The remaining 30 % are deliberately oversized — they represent boats that cannot fit anywhere, making the optimisation non-trivial.
- `compat_matrix` is built from an `ALLOWED_PAIRS` dict that maps boat types to berth types they can occupy.
- VIP boats are assigned `contract_berth_id` only from berths they physically fit AND are compatible with — otherwise the ILP would be infeasible.
- For temporal instances (`n_days > 1`), arrival and departure days are sampled uniformly.

### `generate_gapfill_instance(n_berths, n_long_boats, n_short_boats, n_days, ...)`

Creates an instance with two distinct boat populations:
- **Long-stay boats** (default 5–10 days): fill berths for long stretches and leave short gaps.
- **Short-stay boats** (default 1–4 days): represent discount-attracted demand that fills those gaps.

Used by `run_full_demo.py` to demonstrate the gap-filling pricing strategy.

### `make_hand_crafted_instance()`

Returns a fixed 2-berth / 3-boat instance with a known optimal solution (revenue = 3050). Used in `run_basic.py` to verify the solver is working correctly before running on random instances.

---

## `src/model_basic.py`

Implements the basic static ILP (Extension 0 from the thesis).

### `build_feasibility_mask(inst) -> np.ndarray`

Precomputes the binary matrix `F[i][j]` = 1 if boat j physically fits in berth i (all three dimension checks pass). This avoids adding 3 * n * m individual constraints and instead encodes all dimension infeasibilities as a single matrix inequality `x <= F`.

### `build_basic_model(inst) -> (cp.Problem, cp.Variable)`

Constructs the CVXPY problem:
1. Variable: `x = cp.Variable((n, m), boolean=True)`
2. Revenue matrix: `R = np.outer(price_array, length_array)` — precomputed so CVXPY only sees a linear objective
3. Constraints: feasibility mask + one-berth-per-boat + one-boat-per-berth
4. Returns the problem and the variable (so the caller can read `x.value` after solving)

### `solve_basic(inst, solver, verbose) -> SolveResult`

Calls `build_basic_model`, solves, rounds the result (CVXPY can return 0.9999 instead of 1.0 due to floating-point), and returns a `SolveResult`.

---

## `src/model_extensions.py`

Adds business-rule constraints on top of the basic model (Extensions 2.1 and 2.2).

### Extension functions (each takes `constraints, x, inst` and returns updated `constraints`)

**`add_compatibility(constraints, x, inst)`**
Enforces the compat_matrix: `x <= inst.compat_matrix`. One matrix inequality covers all n * m pairs.

**`add_utility_services(constraints, x, inst)`**
For each boat with `power_required_kw > 0`, iterates over berths and adds `x[i][j] == 0` wherever `berth.power_capacity_kw < boat.power_required_kw`. This enforces both the presence of shore power and its capacity — a berth with 7.4 kW cannot serve a boat that needs 50 kW.

**`add_vip_contracts(constraints, x, inst)`**
For each boat with a contract: forces `x[contract_berth][j] == 1` and zeros out all other berths for that boat.

### `build_extended_model(inst, use_compat, use_utility, use_vip, side_by_side, soft_depth, penalty_M)`

The main builder. Flags control which extensions are active. The side-by-side flag replaces the "one boat per berth" constraint with the width-sum constraint. The soft_depth flag introduces slack variables.

**Design decision:** Each extension is a flag rather than a separate function because they all share the same variable `x` and constraint list. Separating them into independent builders would require rebuilding the variable each time.

### `solve_extended(inst, ...) -> SolveResult`

Convenience wrapper. Builds the extended model and solves it. Returns a `SolveResult` with a `model_name` that lists which extensions were active (e.g. `"extended[compat+utility+vip]"`).

---

## `src/model_temporal.py`

Implements the temporal model (Extensions 2.3, 2.4, 2.5).

### `build_window_mask(inst) -> np.ndarray`

Precomputes a 3D binary array of shape (n, m, T). Entry `[i][j][t] = 1` if boat j's stay window includes day t. Used to enforce `x[i][j][t] = 0` outside the stay window via `x <= window_mask`.

### `build_feasibility_mask_3d(inst) -> np.ndarray`

Combines the dimension feasibility check with the stay window: `F3[i][j][t] = 1` only if the boat fits physically AND day t is within the boat's window. This single mask replaces both `x <= F` and `x <= window_mask`.

### `build_temporal_model(inst, allow_relocation, max_relocations, gap_discount_rate, short_stay_discount, min_stay_days)`

Constructs the 3D CVXPY problem:

1. `x = cp.Variable((n, m, T), boolean=True)` — 3D binary variable
2. Feasibility + window mask applied as `x <= F3`
3. Per-day one-berth-per-boat and one-boat-per-berth constraints
4. If `allow_relocation=False`: stability constraints within each boat's stay window
5. If `allow_relocation=True`: relocation variable `r[j][t]` with big-M detection constraints and a max-relocation limit
6. If `short_stay_discount > 0`: adjusts the revenue matrix for boats with stay < `min_stay_days`
7. If `gap_discount_rate > 0`: adds gap-detection auxiliary variables

**Important:** The stability constraint is only applied within `[arrival_day, departure_day - 2]` for each boat. Applying it outside the stay window would incorrectly force days within the window to zero (because the window mask forces the next day to 0, which propagates backwards).

### `solve_temporal(inst, ...) -> SolveResult`

Solves the temporal model and computes `penalty_value` as the difference between gross revenue (at full prices, ignoring relocation costs) and the reported objective. This allows the verifier to correctly compare gross vs net revenue.

---

## `src/solver.py`

A thin unified entry point. Calls the right model builder based on the `mode` argument.

```python
solve(inst, mode="basic")                          # basic ILP
solve(inst, mode="extended", extensions=["compat","utility","vip"])
solve(inst, mode="temporal", allow_relocation=True)
```

This is useful when you want to iterate over model variants without importing multiple modules.

---

## `src/verifier.py`

Post-solve verification. After every solve, `verify_solution` checks that the returned assignment actually satisfies all the constraints that were enforced.

### Checks performed (static model)

1. Width, length, depth fit for every assigned (berth, boat) pair
2. No boat assigned to more than one berth
3. No berth over its capacity (`max_boats`)
4. VIP boats in their designated berths
5. No assignment where `compat_matrix[i][j] == 0`
6. Gross revenue minus penalty matches the reported objective within 0.1% tolerance

### Checks performed (temporal model)

Same as above, but also:
- No boat present outside its `[arrival_day, departure_day)` window
- No berth occupied by more than one boat on the same day

### `VerificationReport`

```python
@dataclass
class VerificationReport:
    passed: bool
    violations: list[str]   # human-readable description of each violation
    computed_revenue: float  # gross revenue recomputed from the assignment
    reported_revenue: float  # objective_value from the solver
```

**Why verify at all?** Modelling bugs (e.g. a wrong constraint direction, missing constraint) can produce solutions that look valid to the solver but violate real-world rules. The verifier catches these independently of the solver.

---

## `src/visualizer.py`

Four plotting/printing functions. All matplotlib plots are saved to a file if `save_path` is given, or shown interactively otherwise.

### `print_assignment_table(inst, result)`

Console output table. Columns: berth, boat, day (-- for static), revenue contribution, boat dimensions.

### `plot_marina_layout(inst, result, save_path)`

Static 2D assignment only. Draws each berth as a tall rectangle (height = berth length). Assigned boats are drawn as coloured filled rectangles inside their berth, labelled with the boat index.

### `plot_temporal_gantt(inst, result, save_path)`

Temporal assignment only. Gantt chart: x-axis = days, y-axis = berths. Each coloured bar is one boat's stay in one berth.

### `plot_revenue_comparison(results_dict, save_path)`

Bar chart comparing objective values across multiple `SolveResult` objects. Keys of the dict become the bar labels.
