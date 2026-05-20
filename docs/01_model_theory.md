# Model Theory — Marina Berth Allocation ILP

This document explains the mathematical models implemented in this project, starting from the basic assignment problem and building up through all extensions.

---

## 1. The Problem

A marina has **n berths** (parking slots for boats). Each berth has a physical size (width, length, water depth) and charges a price per meter of boat length.

**m boats** want to park. Each boat has dimensions (width, length, draft) and may have additional requirements (electricity, specific berth type).

**Goal:** Assign boats to berths to maximise total revenue, respecting all physical and business constraints.

This is a **combinatorial optimisation** problem. We model it as an Integer Linear Program (ILP): a set of binary yes/no decisions with a linear objective and linear constraints.

---

## 2. Basic Model

### Decision Variable

```
x[i][j] in {0, 1}
  = 1  if boat j is assigned to berth i
  = 0  otherwise
```

There are n * m binary variables in total — one for every possible (berth, boat) pair.

### Objective Function

```
Maximise  sum over all i,j of:  x[i][j] * p[i] * l[j]
```

Where:
- `p[i]` = price per meter of berth i
- `l[j]` = length of boat j

**Why length?** Revenue is proportional to how much of the berth a boat occupies. A 20-metre yacht in a berth priced at 150 EUR/m earns 3,000 EUR per day.

### Constraints

| Constraint | Formula | Why it exists |
|---|---|---|
| Width fit | `x[i][j] * w[j] <= W[i]` for all i,j | The boat must be narrower than the berth |
| Length fit | `x[i][j] * l[j] <= L[i]` for all i,j | The boat must be shorter than the berth |
| Depth fit | `x[i][j] * d[j] <= D[i]` for all i,j | The boat's draft must not exceed the water depth |
| One berth per boat | `sum_i x[i][j] <= 1` for all j | A boat cannot be in two places at once |
| One boat per berth | `sum_j x[i][j] <= 1` for all i | A berth holds at most one boat |

**Implementation note:** The three dimension constraints are precomputed into a binary feasibility mask `F[i][j]`. If the boat cannot physically fit, `F[i][j] = 0` and the constraint `x[i][j] <= F[i][j]` forces that variable to zero. This is more efficient than adding three separate constraints per pair.

---

## 3. Extension 2.1 — Realistic Business Constraints

### 3.1 Boat-Type Compatibility

Some berths cannot accept certain boat types. For example, a berth under a low bridge cannot accept sailing boats with tall masts. We define a binary parameter:

```
compat[i][j] = 1  if boat j is allowed in berth i
             = 0  otherwise
```

Constraint:
```
x[i][j] <= compat[i][j]  for all i,j
```

In practice this is added as a single matrix inequality: `x <= compat_matrix`.

### 3.2 Utility Services (Shore Power Capacity)

Some boats require shore power (3-phase electricity). The constraint is not just a yes/no check — it enforces **kW capacity**. A berth with 7.4 kW cannot serve a boat that needs 50 kW, even though both "have" 3-phase.

Parameters:
- `power_capacity_kw[i]` — how many kW berth i can supply (0 = no shore power)
- `power_required_kw[j]` — how many kW boat j needs (0 = no power needed)

Constraint:
```
if power_required_kw[j] > power_capacity_kw[i]:
    x[i][j] = 0
```

Typical marina values: 3.7 kW (16A single-phase), 7.4 kW (32A), 14.5 kW (63A), 32 kW (large berths). Large motor yachts can require 50 kW or more for air conditioning and systems.

### 3.3 VIP / Contract Pre-Assignments

Some boats have pre-negotiated contracts guaranteeing a specific berth. These are handled before optimisation as **hard pre-assignments**:

```
x[contract_berth][vip_boat] = 1   (forced)
x[i][vip_boat] = 0  for all i != contract_berth
```

The VIP boat is not part of the competition — it is fixed first, and the remaining boats are optimised around it.

---

## 4. Extension 2.2 — Side-by-Side Berthing

In Mediterranean-style mooring, two narrow boats can park side by side in one wide berth. This changes the "one boat per berth" rule.

**Width now sums** (boats share the berth width):
```
sum_j (x[i][j] * w[j]) <= W[i]  for all i
```

**Length and depth stay per-boat** (boats are parallel, not end-to-end):
```
x[i][j] * l[j] <= L[i]  for all i,j
x[i][j] * d[j] <= D[i]  for all i,j
```

**Capacity limit** (at most k boats per berth):
```
sum_j x[i][j] <= k[i]  for all i   (default k = 2)
```

**When does this help?** Only when demand exceeds supply — more boats than berths. If berths are plentiful, there is no need to share.

---

## 5. Extension 2.3 — Temporal Dimension (Multi-Day)

The marina manages reservations across a season of T days. Each boat j has a stay window: it arrives on day `s[j]` and leaves on day `e[j]`.

### New Decision Variable

```
x[i][j][t] in {0, 1}
  = 1  if boat j is in berth i on day t
  = 0  otherwise
```

This is a 3-dimensional binary array of size n * m * T.

### Temporal Constraints

**Stay window enforcement** — boat j can only be present during its reservation window:
```
x[i][j][t] = 0  for all t outside [s[j], e[j])
```
Implemented as `x <= window_mask` where `window_mask` is a precomputed 3D binary array.

**One berth per boat per day:**
```
sum_i x[i][j][t] <= 1  for all j, t
```

**One boat per berth per day:**
```
sum_j x[i][j][t] <= 1  for all i, t
```

**Stability (no-relocation case):** If a boat is assigned, it stays in the same berth for its entire stay:
```
x[i][j][t] == x[i][j][t+1]  for all i, t in [s[j], e[j]-2]
```

### New Objective

```
Maximise  sum over all i, j, t of:  x[i][j][t] * p[i] * l[j]
```

**Why is revenue much higher in the temporal model?** The same berth can serve multiple boats sequentially. A berth occupied days 0-5 by Boat A, then days 6-13 by Boat B, earns revenue from both. The static model would be forced to pick only one.

---

## 6. Extension 2.4 — Boat Relocation

In the stable temporal model, a boat stays in the same berth for its entire visit. The relocation extension allows a boat to switch berths mid-stay, at a cost.

### New Variable

```
r[j][t] in {0, 1}
  = 1  if boat j changes berth between day t and day t+1
  = 0  otherwise
```

### Relocation Detection Constraints

```
x[i][j][t] - x[i][j][t+1] <= r[j][t]   for all i, j, t
x[i][j][t+1] - x[i][j][t] <= r[j][t]   for all i, j, t
```

These constraints force `r[j][t] = 1` whenever the assignment changes for boat j between day t and t+1.

### Maximum Relocations per Boat

```
sum_t r[j][t] <= R_max  for all j   (default R_max = 1)
```

### Modified Objective

```
Maximise  sum(revenue) - sum over j,t of: c[j] * r[j][t]
```

Where `c[j]` is the relocation cost for boat j. Without this penalty, the solver would relocate boats constantly for tiny revenue gains — which is impractical in a real marina.

---

## 7. Extension 2.5 — Short-Stay Gap-Filling Discount

After long-stay boats fill most of the schedule, short gaps remain between bookings (e.g. 3 days free between two 7-day stays). These empty days earn zero revenue.

**Strategy:** The marina offers a discount for short stays (fewer than `min_stay_days` days) to attract boats that fill these gaps.

In the model, this is implemented as a modified revenue matrix. For each boat j with stay length `(e[j] - s[j]) < min_stay_days`:

```
revenue_per_slot[i][j][t] = p[i] * l[j] * (1 - discount_rate)
```

For all other boats, no discount applies.

**Trade-off:** The marina earns less per slot for short stays, but earns something instead of nothing. Any positive discount rate less than 1 makes short-stay bookings profitable compared to empty berth-days.

---

## 8. Hard vs Soft Constraints

| Type | Example | Can be relaxed? | How modelled |
|---|---|---|---|
| Physical (Hard) | Depth fit, width fit | Never | Strict constraint |
| Business rule (Soft) | Boat-type compatibility | Yes, with penalty | Slack variable + penalty M |
| Pricing (Commercial) | Short-stay discount | Negotiable | Parameter in objective |

### Soft Constraint Formulation

Replace:
```
d[j] * x[i][j] <= D[i]
```

With:
```
d[j] * x[i][j] <= D[i] + slack[i][j]
slack[i][j] >= 0
Objective: Maximise(revenue) - M * sum(slack)
```

If penalty M is very large, the solver never violates the constraint (too expensive). If M = 0, the constraint is ignored entirely. The correct M depends on how much revenue the marina would gain by allowing the violation.
