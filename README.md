# Marina Berth Allocation — ILP Optimization

This project implements an **Integer Linear Programming (ILP)** model for optimally assigning boats to berths in a marina, maximising total revenue. It was developed as the second thesis assignment and covers the full model progression described in the thesis report: from a basic static assignment to a multi-day temporal model with relocation and gap-filling pricing, culminating in a **unified final model** (Phase 3) that also packs each boat into the smallest available berth, supports multi-berth spanning and alongside mooring, and is compared against greedy baselines and an online (sequential arrival) scenario.

**Solver:** Python + [CVXPY](https://www.cvxpy.org/) with the GLPK_MI mixed-integer backend.

---

## Setup

```bash
pip install -r requirements.txt
```

Requirements: `cvxpy[glpk]`, `numpy`, `matplotlib` (Python 3.11+).

---

## Phase Map

The project is organised in three phases. Each phase adds model features and matching experiment scripts.

| Phase | Focus | Scripts | Documentation |
|---|---|---|---|
| **1 — Basic ILP** | Static assignment, sanity check, scaling | `run_basic.py`, `sensitivity_analysis.py` | [docs/01](docs/01_model_theory.md), [docs/03](docs/03_experiments_guide.md) |
| **2 — Extensions & temporal** | Compat, VIP, side-by-side, multi-day stays, relocation, gap-fill | `run_extensions.py`, `run_temporal.py`, `run_full_demo.py`, `model_comparison.py`, `run_scenarios.py` | [docs/03](docs/03_experiments_guide.md)–[05](docs/05_model_comparison.md), [docs/04](docs/04_results_analysis.md) |
| **3 — Final unified model** | All features in one MILP + smallest-berth + baselines + online + multi-berth / alongside / split-berth demos | `final_features.py`, `final_comparison.py` | [docs/06_final_model.md](docs/06_final_model.md), [docs/07_phase3_findings.md](docs/07_phase3_findings.md) |

---

## Run the Experiments

All scripts must be run from the project root with UTF-8 encoding:

```bash
python -X utf8 experiments/<script_name>.py
```

| Script | Phase | What it answers |
|---|---|---|
| `experiments/run_basic.py` | 1 | Does the basic ILP return the correct optimum? |
| `experiments/sensitivity_analysis.py` | 1 | How does revenue and solve time scale with number of boats? |
| `experiments/run_extensions.py` | 2 | How does each extension change revenue and feasibility? |
| `experiments/run_temporal.py` | 2 | How does the temporal model handle multi-day stays and relocation? |
| `experiments/run_full_demo.py` | 2 | Side-by-side benefit, date handling, gap-filling discount — full showcase |
| `experiments/model_comparison.py` | 2 | Which model to use when? Revenue progression across all model variants at varied demand ratios |
| `experiments/run_scenarios.py` | 2 | How does each model perform across all demand/supply ratios at once? Full matrix view |
| `experiments/final_features.py` | 3 | Targeted demos: multi-berth spanning, alongside mooring (πλαγιοδέτηση), split berth via relocation |
| `experiments/final_comparison.py` | 3 | Final model (all parameter variants) vs greedy baselines vs online arrivals, over multiple seeds: revenue, utilisation, smallest-berth packing, online competitive ratio |

Plots are saved to `results/`.

---

## Documentation

| File | Contents |
|---|---|
| [docs/01_model_theory.md](docs/01_model_theory.md) | The ILP math: variables, objective, all constraints and extensions |
| [docs/02_code_guide.md](docs/02_code_guide.md) | Every source file explained: purpose, key functions, design decisions |
| [docs/03_experiments_guide.md](docs/03_experiments_guide.md) | Every experiment script: what it tests, expected output, how to read the results |
| [docs/04_results_analysis.md](docs/04_results_analysis.md) | Actual numbers from all runs, interpretation, and which model to use when |
| [docs/05_model_comparison.md](docs/05_model_comparison.md) | Model comparison at varied demand/supply ratios: what each complexity layer adds and why |
| [docs/06_final_model.md](docs/06_final_model.md) | Phase 3 final model: unified temporal + all extensions, smallest-berth packing, multi-berth/alongside/split-berth, greedy baselines and online arrivals, with results |
| [docs/07_phase3_findings.md](docs/07_phase3_findings.md) | Phase 3 Q&A: requirement checklist, result interpretation, best model per scenario, thesis summary paragraph |

---

## Project Structure

```
src/
  core/
    data_model.py        Dataclasses: Berth, Boat, MarinaInstance, SolveResult
    data_generator.py    Synthetic instance generator + Phase 3 demo builders
    revenue.py           Revenue matrices, alongside/multi-berth premiums
    solver.py            Unified solve() entry point (basic/extended/temporal/final)
    verifier.py          Post-solve feasibility checker
    visualizer.py        Console table + matplotlib plots

  models/
    model_basic.py       Basic ILP (x_ij binary variable)
    model_extensions.py  Extensions 2.1/2.2: compatibility, services, VIP, side-by-side, soft
    model_temporal.py    Extensions 2.3-2.5: temporal x_ijt, relocation r_jt, discount
    model_final.py       Phase 3 unified model: temporal + all extensions + smallest-berth + multi-berth

  heuristics/
    baselines.py         Greedy heuristics: first-fit, best-fit, revenue-priority
    online_simulator.py  Online (sequential arrival) allocation + OnlineMetrics

experiments/
  run_basic.py           Phase 1
  sensitivity_analysis.py
  run_extensions.py      Phase 2
  run_temporal.py
  run_full_demo.py
  model_comparison.py
  run_scenarios.py
  final_features.py      Phase 3
  final_comparison.py

results/                 Generated plots (PNG)
docs/                    Detailed documentation
```

Note: legacy duplicate files may still exist at the flat `src/` root from before the refactor; the active code lives under `src/core/`, `src/models/`, and `src/heuristics/`.
