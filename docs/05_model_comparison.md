# Model Comparison — When to Use Which Model

This document explains the results of `experiments/model_comparison.py`, which answers the central design question: **what does each layer of model complexity actually buy you, and when is it worth it?**

---

## Setup

Unlike the other experiments, the model comparison uses **different demand/supply ratios for different rows**. Each model is demonstrated in the scenario where its purpose is clearest:

| Rows | Scenario | Ratio | Why this ratio |
|---|---|---|---|
| 1-2 | Basic + constraints | 1x (8 boats, 8 berths) | Balanced demand shows cost of correctness without competition noise |
| 3 | Side-by-side | 3x (24 boats, 8 berths) | Sharing only matters when berths are actually scarce |
| 4-5 | Temporal | 1x (8 boats, 8 berths, 14 days) | Multi-day gain is independent of competition |
| 6 | Gap discount | 8 long + 16 short boats, 14 days | Gap filling requires the right mix of stay lengths |

Using a fixed ratio for all rows would either exaggerate side-by-side (by always showing it at high demand) or hide it (by using a balanced scenario where there is nothing to gain).

---

## The Six-Row Progression

```
==================================================================================
  MODEL COMPARISON  |  8 berths, varied demand ratios, seed=42
==================================================================================
  Model                            Revenue   vs Basic   Assigned  Status  Scenario
  ------------------------------------------------------------------------------
  1. Basic                          11,977      +0.0%     7/8     FAIL    1x demand, baseline
  2. + Compat + Power                8,242     -31.2%     4/8     OK      1x demand, cost of correctness
  3. + Side-by-side                 22,061     +84.2%    10/24    OK      3x demand, pack more boats
  4. Temporal stable                61,768    +415.7%     5/8     OK      1x demand, 14-day season
  5. Temporal + Compat + Power      61,755    +415.6%     5/8     OK      1x demand, realistic temporal
  6. + Gap-fill discount 20%       219,923   +1736.2%    18/24    OK      long+short stays, fill empty days
==================================================================================
```

### Row 1: Basic (FAIL status — expected)

Revenue = 11,977 EUR. The basic model ignores boat-type compatibility and power capacity. The verifier flags it FAIL because some assignments are physically invalid (a motorboat in a sailing berth, or a boat exceeding the berth's power capacity). The high number is an illusion — this is the upper bound before real-world rules are applied.

### Row 1 → Row 2: Cost of correctness (−31.2%)

Adding compatibility and power constraints drops revenue from 11,977 to 8,242 — a 3,735 EUR reduction. At 1x demand (one boat per berth), the constraints are especially visible: with fewer boats to choose from, eliminating incompatible pairs leaves the solver with much fewer options. This row is verified OK because every assignment now respects the real-world rules.

**When to accept this cost:** Always in a production system. The unconstrained revenue is physically unachievable.

### Row 3: Side-by-side at 3x demand (+84% over basic baseline)

This row uses a different instance (24 boats, 3x demand) to show side-by-side under real scarcity. Revenue = 22,061 with 10 boats assigned out of 24. At 1x demand (rows 1-2), side-by-side would add nothing — every boat already has its own berth. The effect is only visible when boats are turned away.

The ratio sweep section confirms this: side-by-side adds +6% at 0.5x demand and +48% at 4x demand. Showing it at 3x is the honest representation of when it matters.

**Note:** The "vs Basic" percentage (84%) compares to the 1x baseline in Row 1. Row 3 itself uses 3x, so the comparison across rows is intentionally informational rather than directly numeric.

### Row 4: Temporal stable (+416% over basic)

Revenue = 61,768 EUR with 5 boats assigned out of 8 across 14 days. The same 8 berths now serve sequential boats: a berth occupied days 0–6 earns from one boat, then days 7–13 from another. This single lever — moving from a one-time assignment to a multi-day season — multiplies revenue by more than 5x.

**Why only 5/8 boats assigned?** At 1x demand (8 boats for 8 berths), the temporal model can be selective: it picks the combination of bookings across 14 days that maximises total revenue, which may mean skipping a low-value boat rather than filling every berth on every day.

### Row 4 → Row 5: Realistic temporal (−0.0%)

Adding compat + power to the temporal model reduces revenue by only 13 EUR (essentially zero). At 1x demand, most boats are compatible with most berths — the constraints rarely block anything. The recommended production baseline is this model (temporal + compat + power), because:

- It enforces all real-world rules
- At 1x demand it barely costs anything
- At higher demand ratios the cost of correctness grows, but so does the temporal revenue gain

**This is the recommended production baseline.**

### Row 5 → Row 6: Gap-filling discount (+202% over temporal baseline)

Row 6 uses a different instance: 8 long-stay boats (5–10 day stays) and 16 short-stay boats (1–4 day stays), with a 20% discount for stays under 5 days. Revenue = 219,923 with 18/24 boats assigned.

The long-stay boats lock up berths for multi-day stretches. The gaps between their bookings (a berth free on days 3–4, for example) would be left empty without short-stay demand. The 20% discount makes short-stay boats competitive enough to fill those gaps. Every gap-day that was previously empty now earns 80% of full rate instead of 0%.

**Caveat:** Row 6 is not directly comparable to rows 1–5 because it uses a different and larger instance. The relevant conclusion is: when short-stay demand is available, offering a modest discount to attract it is almost always profitable compared to leaving gaps empty.

---

## Demand/Supply Ratio Sweep

The sweep uses the same seed and varies only the number of boats, holding berths at 8 and days at 14.

```
==================================================================================
  DEMAND/SUPPLY RATIO SWEEP  (Basic vs Side-by-side vs Temporal)
  Fixed: 8 berths, seed=42. Boats: 4, 8, 16, 24, 32 (0.5x to 4x)
==================================================================================
   Ratio   Boats       Basic       + SbS   SbS lift    Temporal   Temp lift
  ------------------------------------------------------------------------
    0.5x       4       4,853       5,139        +6%      19,867       +309%
    1.0x       8      11,977      13,397       +12%      61,768       +416%
    2.0x      16      20,187      26,506       +31%      90,285       +347%
    3.0x      24      20,489      29,700       +45%     107,286       +424%
    4.0x      32      20,591      30,418       +48%     118,753       +477%
==================================================================================
```

### Reading the sweep

**Basic revenue plateaus quickly.** From 1x to 4x, static revenue barely increases (11,977 to 20,591) even as boat count grows 4x. Once all 8 berths are full (which happens by about 1.5x demand), adding more boats has no effect.

**Side-by-side lift scales with competition.** At 0.5x there are empty berths anyway — side-by-side adds only +6%. At 4x, with four times as many boats as berths, it adds +48%. This confirms that the model comparison shows it at 3x: that is where the benefit is clearly visible and practically relevant.

**Temporal lift is always large.** At every ratio, temporal is at least +309% above basic. As more boats compete for the same berths across 14 days, the temporal model has even more combinations to choose from — hence the lift grows further at higher ratios.

---

## Decision Guide

| Scenario | Best model | Key reason |
|---|---|---|
| Learning / first run | Basic | Fast, easy to verify, no extra parameters |
| Single-day with business rules | Extended (compat + power + VIP) | Enforces real-world constraints |
| Busy marina, berths scarce (2x+ demand) | Extended + side-by-side | Side-by-side adds +31-48% at 2x-4x demand |
| Multi-day season management | Temporal stable + compat + power | Same berth serves sequential boats; +416% over basic |
| Gaps between bookings | Temporal + gap-fill discount | Short-stay boats at 20% off fill empty days profitably |
| Full production system | Temporal + compat + power + gap-fill | All constraints enforced; gaps monetised |

### The core trade-off in one sentence

Every constraint you add reduces the solver's freedom and lowers revenue — but also makes the solution actually achievable in a real marina. The correct question is never "which model gives the highest number?" but "which model gives the highest number that is also physically and commercially valid?"

---

## How to Run

```bash
python -X utf8 experiments/model_comparison.py
```

Output: comparison table + ratio sweep printed to console, bar chart saved to `results/model_comparison.png`.

To change the scenarios, edit the constants at the top of the script:

```python
N_BERTHS         = 8   # number of berths in all scenarios
N_BOATS_BALANCED = 8   # boats for 1x demand rows (rows 1, 2, 4, 5)
N_BOATS_SCARCE   = 24  # boats for 3x demand row (row 3, side-by-side)
N_DAYS           = 14  # season length for temporal rows
SEED             = 42  # random seed
```
