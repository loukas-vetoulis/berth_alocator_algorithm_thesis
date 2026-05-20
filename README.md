# Marina Berth Allocation — ILP Optimization

This project implements an **Integer Linear Programming (ILP)** model for optimally assigning boats to berths in a marina, maximising total revenue. It was developed as the second thesis assignment and covers the full model progression described in the thesis report: from a basic static assignment to a multi-day temporal model with relocation and gap-filling pricing.

**Solver:** Python + [CVXPY](https://www.cvxpy.org/) with the GLPK_MI mixed-integer backend.

---

## Setup

```bash
pip install -r requirements.txt
```

Requirements: `cvxpy[glpk]`, `numpy`, `matplotlib` (Python 3.11+).

---

## Run the Experiments

All scripts must be run from the project root with UTF-8 encoding:

```bash
python -X utf8 experiments/<script_name>.py
```

| Script | What it answers |
|---|---|
| `experiments/run_basic.py` | Does the basic ILP return the correct optimum? |
| `experiments/run_extensions.py` | How does each extension change revenue and feasibility? |
| `experiments/run_temporal.py` | How does the temporal model handle multi-day stays and relocation? |
| `experiments/run_full_demo.py` | Side-by-side benefit, date handling, gap-filling discount — full showcase |
| `experiments/sensitivity_analysis.py` | How does revenue and solve time scale with number of boats? |
| `experiments/model_comparison.py` | Which model to use when? Revenue progression across all model variants at varied demand ratios |
| `experiments/run_scenarios.py` | How does each model perform across all demand/supply ratios at once? Full matrix view |

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

---

## Project Structure

```
src/
  data_model.py        Dataclasses: Berth, Boat, MarinaInstance, SolveResult
  data_generator.py    Synthetic instance generator
  model_basic.py       Basic ILP (x_ij binary variable)
  model_extensions.py  Extensions 2.1/2.2: compatibility, services, VIP, side-by-side, soft
  model_temporal.py    Extensions 2.3-2.5: temporal x_ijt, relocation r_jt, discount
  solver.py            Unified solve() entry point
  verifier.py          Post-solve feasibility checker
  visualizer.py        Console table + matplotlib plots

experiments/
  run_basic.py
  run_extensions.py
  run_temporal.py
  run_full_demo.py
  sensitivity_analysis.py
  model_comparison.py
  run_scenarios.py

results/               Generated plots (PNG)
docs/                  Detailed documentation
```
