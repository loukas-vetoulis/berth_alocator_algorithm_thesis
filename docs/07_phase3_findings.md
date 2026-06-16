# 07 — Phase 3: Απαντήσεις στα ερευνητικά ερωτήματα και τι μάθαμε από τα τελικά πειράματα

Αυτό το κεφάλαιο συνοψίζει **τι ζητήθηκε**, **τι υλοποιήθηκε**, **τι δείχνουν τα τελευταία αποτελέσματα** (`final_comparison.py`, `final_features.py`) και **ποιο μοντέλο προτείνεται** για κάθε σενάριο. Γράφτηκε μετά το τελευταίο commit της Phase 3 (ενιαίο final model, greedy/online benchmarks, multi-berth / plagiodetisi / split berth, side-by-side χωρίς όριο `max_boats`).

Σχετικά: [06_final_model.md](06_final_model.md) (μαθηματική περιγραφή), [04_results_analysis.md](04_results_analysis.md) (αριθμοί Phases 1–2).

---

## 1. Checklist — έχουμε απαντήσει όλα;

| Ερώτημα / απαίτηση | Κατάσταση | Πού |
|---|---|---|
| Τελικό μοντέλο με παραμέτρους (base, side-by-side, soft depth, relocation, mix) | **Ναι** | `experiments/final_comparison.py` — `FINAL_CONFIGS` |
| Σύγκριση με greedy baselines (first-fit, best-fit, revenue-priority) | **Ναι** | `src/heuristics/baselines.py` + Part A |
| Σύγκριση με τον «έξυπνο» αλγόριθμο (MILP offline optimum) | **Ναι** | `solve_final()` vs greedy |
| Random δεδομένα (πολλά seeds, πολλά demand levels) | **Ναι** | 5 seeds × 4 demand ratios (0.5×–3×) |
| Online — τα requests δεν έρχονται όλα μαζί | **Ναι** | `src/heuristics/online_simulator.py` — Part C |
| Μικρότερη θέση που χωράει το σκάφος | **Ναι (soft + heuristic)** | Ποινή `space_weight` στο MILP· αυστηρά στο `best_fit` (βλ. §2) |
| Αριθμός σκαφών που εξυπηρετούνται | **Ναι** | Στήλη `served` + summary + `final_boats_served.png` |
| Multi-berth (2 θέσεις για φαρδύ σκάφος) | **Ναι** | `final_features.py` demo 1 |
| Πλαγιοδέτηση (alongside) + premium | **Ναι** | `final_features.py` demo 2 |
| Split berth (αλλαγή θέσης mid-stay) | **Ναι** | `final_features.py` demo 3 |
| Side-by-side χωρίς όριο 2 σκαφών | **Ναι** | Μόνο πλάτος (`width`) — χωρίς `max_boats` cap |

**Σημαντική διευκρίνιση:** «Πιο φθηνή θέση» στο μοντέλο σημαίνει **μικρότερη θέση που χωράει φυσικά** (minimum `berth.length`), όχι απαραίτητα τη θέση με το χαμηλότερο `price_per_meter`. Το revenue είναι `price × μήκος_σκάφους`, οπότε η «φθηνότερη τιμή/μέτρο» δεν ταυτίζεται πάντα με τη μικρότερη θέση.

---

## 2. Μικρότερη θέση — πώς το model-άρουμε

### 2.1 Στο MILP (realistic compromise)

Δεν επιβάλλουμε hard rule «πάντα η μικρότερη θέση», γιατί το pure revenue maximisation θα προτιμούσε ακριβότερες μεγάλες θέσεις. Αντί αυτού:

```
ποινή = space_weight × price[i] × (μήκος_θέσης[i] − μήκος_σκάφους[j])
```

- `space_weight = 0` → μόνο revenue (default στο Part A του benchmark).
- `space_weight ≥ 0.3` → έντονη προτίμηση compact packing (Part B).

**Τι μάθαμε (Part B, 16 σκάφη / 8 θέσεις / 14 ημέρες):**

| space_weight | Gross revenue | Wasted length (m) | Boats served |
|---|---|---|---|
| 0.0 – 0.2 | 90,966 | 662 | **7** |
| 0.3 – 1.0 | 77,351 | 335 | **5** |

Όσο αυξάνουμε την ποινή, μειώνεται η «σπατάλη» μήκους θέσης (~50%), αλλά **2 λιγότερα σκάφη** εξυπηρετούνται και ~15% λιγότερα έσοδα. Αυτό είναι realistic trade-off: η μαρίνα θέλει compact packing, αλλά όχι με κάθε κόστος.

### 2.2 Στα greedy baselines (αυστηρός κανόνας)

Το **`best_fit`** βάζει κάθε σκάφος στη **μικρότερη ελεύθερη θέση** (minimum `berth.length` among feasible berths) — όπως συχνά κάνει προσωπικό μαρίνας στην πράξη.

Στο Part B: best-fit σερβίρει **7 σκάφη** vs first-fit **6**, με ~15% περισσότερα έσοδα.

### 2.3 Αριθμός σκαφών που εξυπηρετούνται

Προστέθηκε:
- στήλη **`served`** (mean count) σε κάθε πίνακα demand του Part A,
- **SUMMARY — BOATS SERVED** στο τέλος του script,
- γράφημα **`results/final_boats_served.png`**.

**Προσοχή:** περισσότερα σκάφη ≠ αυτόματα «όλα στη μικρότερη θέση». Δείχνει **πόσα σκάφη χωράνε συνολικά**· η compact τοποθέτηση ελέγχεται ξεχωριστά via `space_weight` / `best_fit` / `wasted_m`.

---

## 3. Τελικό μοντέλο — παραλλαγές παραμέτρων

Όλες οι παρακάτω χρησιμοποιούν το ίδιο `solve_final()` με **compat + shore power + VIP πάντα ενεργά**.

| Config | Τι ενεργοποιεί | Πότε βοηθά |
|---|---|---|
| `final[base]` | Βασικό temporal + business rules | Baseline offline optimum |
| `final[side-by-side]` | Κοινή χρήση πλάτους θέσης (χωρίς `max_boats` cap) | Όταν η ζήτηση > προσφορά |
| `final[soft-penalty]` | Soft depth — ρηχότερη θέση με ποινή | Όταν draft μπλοκάρει αναθέσεις |
| `final[relocation]` | Split berth / αλλαγή θέσης mid-stay | Όταν καμία θέση δεν είναι ελεύθερη όλη τη διαμονή |
| `final[full-mix]` | Side-by-side + soft depth μαζί | Υψηλή ζήτηση — μέγιστα έσοδα + σκάφη |

---

## 4. Greedy baselines και online

| Μέθοδος | Λογική | Ρόλος στη διπλωματική |
|---|---|---|
| **first_fit** | «Αν χωράει, βάλ' το στην πρώτη ελεύθερη θέση» | Απλό baseline |
| **best_fit** | «Βάλ' το στη μικρότερη θέση που χωράει» | Realistic operational rule |
| **revenue_priority** | «Πρώτα τα σκάφη με τα μεγαλύτερα έσοδα» | Greedy με προτεραιότητα αξίας |
| **online[first_fit / best_fit]** | Ίδια πολιτική, αλλά **ένα request τη φορά**, χωρίς lookahead | Real-time κρατήσεις |
| **final[...]** (MILP) | Βλέπει **όλα** τα σκάφη και **όλες** τις ημέρες· global optimum | Άνω bound / offline planner |

**Online vs offline (Part C):** το online best-fit φτάνει **82–93%** του offline optimum — δηλαδή το να μην ξέρεις τα μελλοντικά requests κοστίζει ~7–18% έσοδα.

---

## 5. Τι μας λένε τα αποτελέσματα (τελευταία εκτέλεση)

Πηγή: `final_comparison.py` + `final_features.py` (όλα verify **OK**).

### 5.1 Κύριο benchmark (mean over 5 seeds, 8 θέσεις, 14 ημέρες)

**Σε χαμηλή ζήτηση (0.5×–1×):** όλες οι μέθοδοι παρόμοια — υπάρχουν ήδη κενές θέσεις. Side-by-side δεν αλλάζει σχεδόν τίποτα.

**Σε υψηλή ζήτηση (3× — 24 σκάφη / 8 θέσεις):**

| Method | Gross revenue | Boats served (mean) | Assign % |
|---|---|---|---|
| **final[full-mix]** | **151,697** | **10.4** | **43.3%** |
| final[side-by-side] | 131,743 | 8.8 | 36.7% |
| final[soft-penalty] | 129,471 | 9.4 | 39.2% |
| final[base] | 113,749 | 8.0 | 33.3% |
| greedy[best_fit] | 105,417 | 8.6 | 35.8% |
| online[best_fit] | 106,559 | 8.8 | 36.7% |

**Συμπεράσματα:**

1. **Το MILP (`final[full-mix]`) κερδίζει σε revenue και σε σκάφη** έναντι κάθε greedy — ~44% περισσότερα έσοδα vs best-fit στο 3× demand, +1.8 σκάφη vs base.
2. **Side-by-side (μόνο width, χωρίς max_boats)** αυξάνει έσοδα +16% vs base στο 3× (131,743 vs 113,749) και +0.8 σκάφη — όσο πιο γεμάτη η μαρίνα, τόσο περισσότερο μετράει.
3. **Soft depth** επιτρέπει περισσότερες αναθέσεις (+1.4 σκάφη vs base στο 3×) με draft trade-off.
4. **Greedy είναι γρήγορο (ms) αλλά myopic** — δεν κάνει split berth, multi-berth spanning, ούτε global βελτιστοποίηση across days.
5. **Revenue ≠ utilisation** — μπορείς να έχεις υψηλότερη utilisation με λιγότερα έσοδα (π.χ. πολλά φθηνά/μικρά slots).

### 5.2 Phase 3 feature demos (`final_features.py`)

| Feature | Χωρίς | Με | Μάθημα |
|---|---|---|---|
| Multi-berth | 2/3 σκάφη, €9,120 | 3/3, €17,520 | Φαρδύ σκάφος εξυπηρετείται με span +25% premium |
| Alongside | 8/8 stern-to, €19,200 | 6/8, €15,840 | +60% premium αλλά «τρώει» πλάτος (length αντί beam) |
| Split berth | 2/3, €4,000 | 3/3, €8,000 | Relocation ξεκλειδώνει κρατήσεις που stable απορρίπτει |

---

## 6. Ποιο είναι το «καλύτερο» μοντέλο;

Δεν υπάρχει ένα μοντέλο για όλα — εξαρτάται από το τι μετράς:

| Στόχος | Προτεινόμενη ρύθμιση | Γιατί |
|---|---|---|
| **Μέγιστα έσοδα + περισσότερα σκάφη (offline planning)** | **`final[full-mix]`** | Κορυφαία revenue και served στο 3× demand |
| **Realistic real-time (χωρίς lookahead)** | **online[best_fit]** | 82–93% του optimum, milliseconds |
| **Γρήγορο offline χωρίς solver** | **greedy[best_fit]** | Καλή προσέγγιση + αυστηρή μικρότερη θέση |
| **Compact packing (λιγότερα κενά μέτρα)** | MILP με **`space_weight ≥ 0.3`** | −50% waste, trade-off −15% revenue, −2 σκάφη |
| **Φαρδύ σκάφος / 2 θέσεις** | **`allow_multi_berth=True`** | Demo: wide boat αλλιώς rejected |
| **Πλαγιοδέτηση** | `mooring_type="alongside"` + side-by-side | Premium pricing, λιγότερη χω 용性 |
| **Split κράτηση** | **`allow_relocation=True`** | Demo: +1 σκάφος όταν stable αποτυγχάνει |

**Για production marina system (thesis recommendation):** χρησιμοποίησε **`final[full-mix]`** ως offline planner (βλέπει όλη τη σεζόν), **`online[best_fit]`** για real-time κρατήσεις, και **`space_weight`** ως dial για compactness vs revenue.

---

## 7. Γραφήματα — τι να δείξεις στη διπλωματική

| Αρχείο | Τι δείχνει |
|---|---|
| `final_revenue.png` | Έσοδα ανά method και demand — MILP πάνω από greedy |
| `final_utilization.png` | Πληρότητα θέσεων-ημερών — διαφορετικό metric από revenue |
| `final_boats_served.png` | Μέσος αριθμός σκαφών που εξυπηρετούνται |
| `final_online_vs_offline.png` | Competitive ratio — κόστος μη-προγνωσιμότητας |
| `final_space_tradeoff.png` | Pareto: revenue vs wasted length (`space_weight`) |
| `final_multiberth_gantt.png` | Spanning demo |
| `final_split_gantt.png` | Split berth demo |

---

## 8. Πώς να τρέξεις ξανά

```bash
python -X utf8 experiments/final_comparison.py
python -X utf8 experiments/final_features.py
```

Αν εμφανιστεί OpenBLAS OOM σε Windows:

```powershell
$env:OPENBLAS_NUM_THREADS = "1"
$env:OMP_NUM_THREADS = "1"
python -X utf8 experiments/final_comparison.py
```

---

## 9. Μία παράγραφος για την εργασία (copy-paste ready)

> Στη Phase 3 ενώσαμε όλα τα extensions σε ένα ενιαίο temporal MILP (`model_final`), προσθέσαμε multi-berth spanning (+25%), alongside mooring / πλαγιοδέτηση (+60%), split berth via relocation, και side-by-side χωρίς artificial cap σκαφών (μόνο πλάτος). Η compact τοποθέτηση model-άρεται ως ποινή unused length (`space_weight`) στο MILP και ως αυστηρός κανόνας στο greedy best-fit. Τα πειράματα (`final_comparison.py`, 5 seeds, demand 0.5×–3×) συγκρίνουν πέντε παραμετρικές εκδοχές του final model με τρία greedy και δύο online policies· στο 3× demand το `final[full-mix]` επιτυγχάνει €151,697 (+44% vs greedy best-fit) και 10.4 σκάφη (+30% vs base), ενώ το online best-fit φτάνει 82–93% του offline optimum. Τα targeted demos (`final_features.py`) επιβεβαιώνουν ότι multi-berth, plagiodetisi και split berth λειτουργούν και επαληθεύονται.
