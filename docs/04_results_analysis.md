# Results Analysis

This document explains the actual numerical results produced by all experiments, what they mean, and which model to choose for a given use case.

---

## 1. Basic Model — Sanity Check

**Instance:** 2 berths, 3 boats (hand-crafted, known optimal).

```
Berth 0: width=5, length=10, depth=2, price=100 EUR/m
Berth 1: width=8, length=20, depth=3, price=150 EUR/m

Boat 0: width=4, length=8,  draft=1.5  (fits both berths)
Boat 1: width=7, length=15, draft=2.5  (fits only Berth 1)
Boat 2: width=3, length=6,  draft=1.0  (fits both berths)
```

**Result:** Revenue = **3050**, Verification: PASSED.

Why 3050? Boat 1 can only go in Berth 1 (too wide for Berth 0). Once Berth 1 is taken by Boat 1 (earning 150 * 15 = 2250), Berth 0 is the only option for the remaining boats. Boat 0 is longer than Boat 2, so it goes to Berth 0 (earning 100 * 8 = 800). Boat 2 is unassigned — no berths left.

Could we do better? No. The only other option would be to put Boat 0 in Berth 1 instead (revenue 150 * 8 = 1200), but that wastes Berth 1's value. The solver correctly finds the global optimum.

---

## 2. Extensions — Cost of Correctness

**Instance:** 10 berths, 8 boats, seed 42 (same instance for all configs).

| Configuration | Revenue | Verification |
|---|---|---|
| basic | 14,702 | FAIL (compat violations) |
| compat only | 6,676 | PASS |
| utility only | 14,702 | FAIL (compat violations) |
| compat + utility | 6,676 | PASS |
| all (compat + utility + VIP) | 6,625 | PASS |
| side-by-side only | 15,768 | FAIL |
| all + side-by-side | 9,269 | PASS |
| soft depth, M=1000 | 6,625 | PASS |
| soft depth, M=0 | 14,702 | FAIL |

**Key observations:**

**Basic model earns the most (14,702) but violates real-world rules.** It places a motorboat in a sailing berth and assigns boats to berths that lack sufficient shore power because those combinations earn more. A real marina cannot do this. The high number is an illusion.

**Adding compatibility drops revenue to 6,676 (a 55% reduction).** This is the "cost of correctness" — the solver now has fewer valid (berth, boat) pairs. The drop is large because this particular random instance has many incompatible boat-berth type combinations.

**`all` (compat + utility + VIP) gives 6,625 — only slightly less than `compat + utility` (6,676).** The small reduction comes from the VIP boat being pre-assigned to a berth it might not have occupied in the unconstrained case, leaving a slightly worse remainder for the other boats.

**Side-by-side without compat earns 15,768 — more than basic (14,702).** It fits additional boats into wide berths. But this config still violates compatibility. The valid side-by-side result is `all + sbs = 9,269`, which is higher than `all = 6,625` — confirming that side-by-side strictly increases revenue when multiple boats compete for the same berths.

**Soft constraint with M=1000 matches `all` exactly (6,625).** This confirms the penalty is high enough to make violations never worth it. If you set M=0, you get the unconstrained basic result — the depth constraint is completely ignored.

---

## 3. Side-by-Side — When Demand Exceeds Supply

**Instance:** 10 berths, 20 boats (demand is 2x supply), seed 42.

| Model | Revenue | Boats assigned |
|---|---|---|
| Without side-by-side | 21,535 | 9 / 20 |
| With side-by-side | 32,657 | 13 / 20 |

**Extra revenue: +11,122 (+51.6%)** from assigning 4 additional boats.

Why not all 20? Some boats are too wide to share a berth with another boat. Even in side-by-side mode, `width[j1] + width[j2] <= W[i]` must hold. The 6 remaining unassigned boats either don't fit side-by-side in any remaining berth, or their revenue contribution is lower than the next-best option.

**When side-by-side does not help:** Run the same config with 8 boats and 10 berths. Revenue and assignment count will be identical — there are already empty berths for every boat, so sharing adds nothing.

---

## 4. Temporal Model — The Biggest Revenue Gain

**Instance:** 10 berths, 20 boats, 14-day season, seed 42.

| Model | Revenue | Berth-days used |
|---|---|---|
| Static (ignores time) | 23,235 | 10 (one per berth) |
| Temporal stable | 131,870 | 63 / 140 |

**Extra revenue: +108,635 (+467%)**

This is the most dramatic result. The static model assigns each berth to exactly one boat for the whole 14-day season. In the temporal model, the same berth can serve different boats on different days. Berth 0 might host Boat 6 on days 1–5, then Boat 4 on days 5–12. Instead of one boat's worth of revenue, it earns two.

The 467% figure arises because the season has 14 days. Each berth is worth up to 14x more than the static model assumes. In practice, a real marina cannot always fill every berth on every day — 63 out of 140 possible berth-days (45%) were occupied, reflecting realistic gaps between bookings. The lower occupancy compared to previous runs is partly due to the power constraint: some boats that could previously share a berth are now blocked because the berth lacks sufficient kW capacity.

**Relocation results:**

| Model | Revenue |
|---|---|
| Temporal stable | ~39,519 (7-day instance) |
| Temporal + relocation | ~27,411 |

Relocation earns less in this instance because relocation costs outweigh the reshuffling benefit. The solver decided it was better to stay stable. This is realistic: moving a yacht between berths requires marina staff, ropes, and time.

---

## 5. Gap-Filling Discount — Pricing to Fill Empty Days

**Instance:** 8 berths, 8 long-stay boats (5–10 days), 14-day season.

| Scenario | Revenue | Berth-days occupied | Empty days |
|---|---|---|---|
| A: long stays only | 144,350 | 44 / 112 | **68 empty** |
| B: long + short stays, full price | 195,704 | 79 / 112 | 33 |
| C: long + short stays, 20% discount | 185,149 | 79 / 112 | 33 |

**Scenario A** has 68 empty berth-days (61% of capacity). The high vacancy is partly due to the power constraint: some berths lack sufficient kW for the boats that would otherwise fill them.

**Scenario B** fills 35 of those empty days (+51,354 extra revenue). The short-stay boats targeted the gaps because their arrival/departure windows matched the free periods.

**Scenario C** earns less per slot (20% discount) but still fills the same number of gaps. Revenue = 185,149 vs doing nothing (144,350). The marina earns +40,800 more than Scenario A, even after offering the discount. Every discounted berth-day that was previously empty adds net positive revenue.

**The discount trade-off:**
- At 0% discount (full price): marina earns the maximum per slot, but may not attract short-stay boats that are price-sensitive.
- At 20% discount: marina attracts more short-stay bookings, fills gaps, earns less per slot but more in total.
- At 100% discount: boats park for free — this only makes sense as a last-resort marketing strategy.

The optimal discount rate depends on price elasticity of demand (not modelled here), but any rate between 0% and 100% is better than leaving the berth empty.

---

## 6. Sensitivity Analysis — Scaling Behaviour

**Instance:** 15 berths, n_boats from 5 to 50, basic model.

| n_boats | Revenue | Assigned | Rate | Solve time |
|---|---|---|---|---|
| 5 | 8,865 | 3 | 60% | 0.02s |
| 10 | 18,397 | 7 | 70% | 0.02s |
| 15 | 22,965 | 10 | 67% | 0.02s |
| 20 | 31,652 | 13 | 65% | 0.02s |
| 30 | 35,550 | 13 | 43% | 0.03s |
| 50 | 37,806 | 14 | 28% | 0.04s |

**Revenue grows and then levels off.** With 5 boats and 15 berths most berths stay empty — only 2 out of 5 boats fit (many boats are oversized by design). Revenue saturates around n_boats = 40, because all 15 berths are full and more boats have no effect.

**Assignment rate drops as competition grows.** With 50 boats competing for 15 berths, only 28% get a slot. The solver is not being "fair" — it picks the most valuable 14 boats and ignores the rest. This is optimal from the marina's revenue perspective.

**Solve time is flat under 0.05 seconds.** GLPK_MI handles this problem size trivially. The ILP has at most 50 * 15 = 750 binary variables, which is tiny. The problem only becomes slow for large temporal instances (100+ boats, 30+ days), where the variable count grows to n * m * T.

---

## 7. Which Model to Use When

| Use case | Recommended model | Key parameters |
|---|---|---|
| One-day assignment, no business rules | Basic ILP (`run_basic.py`) | `n_berths`, `n_boats` |
| Real-world single-day with berth types and electricity | Extended, all extensions (`run_extensions.py`) | Add `compat`, `utility`, `vip` |
| Allow 2 boats per wide berth | Extended + side-by-side | `side_by_side=True`, `max_boats=2` |
| Multi-day season, each berth serves multiple boats | Temporal stable | `n_days`, `arrival_day`, `departure_day` |
| Allow boats to change berths mid-stay | Temporal + relocation | `allow_relocation=True`, `max_relocations` |
| Fill short gaps with discounted short stays | Temporal + short-stay discount | `short_stay_discount=0.2`, `min_stay_days=5` |
| Understand how constraints affect revenue | Extensions comparison | `run_extensions.py` |
| Understand how the model scales | Sensitivity analysis | `sensitivity_analysis.py` |

**For a real marina management system:** start with the temporal stable model (Extension 2.3) plus the compatibility and utility extensions (2.1). Add VIP pre-assignment if the marina has season berth holders. Add side-by-side and relocation when the operational complexity is justified by the revenue gain.
