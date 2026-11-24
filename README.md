# ForgeEngine: design optimizer with evals for the MyCNC V4 Z axis

## Quick start

- pythonOCC is only distributed through conda-forge (not PyPI), so running needs conda (Miniforge, ~5 min install); reviewing the results needs no installation.
- **Read without installing:** this README → [EVALS.md](EVALS.md) → [results/best.json](results/best.json) (all results are committed).
- **Run:** install [Miniforge](https://github.com/conda-forge/miniforge) if you have no conda. Running needs only python, pythonocc-core, numpy and pyyaml; pytest is for the tests.
```
conda env create -f environment.yml   # Miniforge solves with libmamba; mamba env create -f environment.yml is the same
conda activate forge-cad
python bench.py --cases cases/        # expected: the three rows under "Result" (best ACCEPT -9.134517, failing REJECT, original REFERENCE)
python optimize.py --out cases/best   # prints the 2 ACCEPT rows, fails per check, best 2 mm trim + S1 + S3 + S4 (--verbose: all 80)
python -m pytest -q                   # 41 passed, 1 skipped
```
- **Times** (measured on the author's Windows machine, cache shipped): environment about 2–5 min (110–165 MB download), bench 5 s, optimizer 19 s, tests 15 s.
- The Windows PATH note under "How to run" is only needed when the environment is not activated.

## About

Reads the Z-axis subassembly STEP with code, generates design options from rule files, grades each option with
deterministic Function / Fit / Cost graders, picks the best, and writes the changed parts as STEP in the original
coordinates. `bench.py` scores cases; the graders are described in [EVALS.md](EVALS.md).

## Result

Winner: **2 mm symmetric X-end trim of both ZXVerbinder + S1 (Z motor) + S3 (rear-clamp screws) + S4 (motor screws)**,
at the default cost model (removal rate 50000 mm³/min):

| Component | Δ EUR/assembly |
|---|---|
| Made parts (ZXVerbinder trim) | −0.158397 |
| S1 Z motor 23HS45-4204S (3 Nm) → 23HS20-2004S (0.9 Nm) | −10.398131 |
| S3 4 × M8 × 80 → M8 × 110 | +0.981129 |
| S4 4 × M5 × 50 → M5 × 65 | +0.440881 |
| **Total** | **−9.134517** |

```
case       Function Fit   Cost  verdict   expected    delta EUR      F4  F7 SF  G10 d  compliance / failed checks
best       PASS     PASS  PASS  ACCEPT    ACCEPT      -9.134517  1.0986  1.471   2.00  F5/F6; G6
failing    FAIL     FAIL  PASS  REJECT    REJECT      -1.450027    None  0.441   0.00  F1_connector_tear_out; F4_deflection_ratio_bound; F5/F6; F7; G10; G12_NP2_metric_threads; G3_protected_core; G6
original   FAIL     FAIL  FAIL  REFERENCE REFERENCE    0.000000     1.0  0.441   0.00  C3_cost_delta; F5/F6; F7; G10; G6
```

The original design fails F7 (ball nut) and G10 (screws that do not reach their threads); it is the comparison base
(REFERENCE). 2 of 80 options are ACCEPT (1 mm and 2 mm, each with S1 + S3 + S4).

## How to run

```
conda env create -f environment.yml        # python 3.12, pythonocc-core 8.0.1.x novtk, numpy (OpenBLAS), pyyaml, pytest
conda activate forge-cad
python optimize.py --out cases/best        # 80 options -> results/options.csv, results/options/*.step, cases/best/
python bench.py --cases cases/             # one score row per case -> results/<case>.json
python -m pytest -q                        # 41 tests (+1 slow rebuild test with FORGE_SLOW=1)
```

- **Windows without `conda activate`:** put the env's DLL folders first on PATH, or numpy's LAPACK loads the wrong DLL
  and Python dies in `numpy.linalg` (exit code -1066598273):
  `$e="<env>"; $env:PATH="$e;$e\Library\mingw-w64\bin;$e\Library\usr\bin;$e\Library\bin;$e\Scripts;$e\bin;"+$env:PATH`.
  Set `PYTHONIOENCODING=utf-8` for the console output.
- **Runtimes (warm, measured 2026-11-24):** optimizer 19 s, bench 5 s, tests 15 s (wall time incl. start-up; up to
  2× on a loaded machine). The STEP cache (`cache/`, 644 KB) ships with
  the repository, so a fresh clone does not re-import the 67 MB STEP; a rebuild (new STEP or cache version) takes
  1.5–5 min and happens automatically.
- `tools/write_evals.py` regenerates EVALS.md from `results/best.json`; `tools/thickness_screen.py` writes
  [results/thickness_screen.md](results/thickness_screen.md); `tools/process_review.py` writes
  [results/process_review.md](results/process_review.md).

## The physics

**LC1 load path** (200 N at the tool tip, ±X and ±Y; `results/load_path.json`):

```
tool tip -> spindle -> clamps (MotorHalter1/2) -> moving plate (MotorHalterPlatteIsel) -> Z carriages -> Z rails
         -> fixed guide plate (ZFuehrungsHalter) -> X carriages (IF4: Y and Z forces, couple)
                                                 -> ZXVerbinder -> X ball nut (IF5: X force only, ideal axial drive)
```

| Direction | Moving plate | ZXVerbinder pair | Fixed guide plate | Total |
|---|---|---|---|---|
| ±X deflection | 0.00148 mm (55%) | 0.00066 mm (25%) | 0.00056 mm (21%) | 0.00271 mm |
| ±Y deflection | 0.0695 mm (43%) | not in the Y path | 0.0921 mm (57%) | 0.162 mm |

The stiffness-limiting parts are the moving plate for ±X and the fixed guide plate for ±Y; ±Y is about 60× softer than
±X. Nominal bending stresses stay below 5 MPa against 62.5 MPa allowed.

**LC2 crash:** the Z motor pushes with full torque against a blocked spindle: F = 2π·T·η/p = 2π·3·0.9/0.0025 = 6,786 N
(YAML: 6,800 N). The Z ball nut's static rating is 3,000 N (Isel 213412 0003, `rules/bought_parts.yaml`): factor 0.44
against 1.2. S1 lowers the force by the torque ratio to 6,800 × 0.9/3 = 2,040 N (factor 1.471).

## The decision

- **One rule, built:** symmetric X-end trim of the ZXVerbinder (`rules/zxverbinder_trim.yaml`, 1–10 mm) combined with
  every subset of the bought-part fixes S1, S3, S4 (`rules/bought_part_substitutions.yaml`).
- **Why only the ZXVerbinder:** it is the one made part with stock outside its bolt pattern along an axis that F4 can
  grade; the stiffest-limiting plates are 93–98% solid, the clamps carry the Ø80 IF1 bore
  ([results/part_table.md](results/part_table.md)). The trim is limited to 2 mm by F4 (deflection bound 1.0986 ≤ 1.10).
- **Why the motor swap:** F7 fails in the original; only a weaker motor (≤ 1.103 Nm) keeps the crash force under the
  nut's rating with the factor 1.2. The 0.9 Nm motor still moves the Z head (2,040 N capacity against about 337 N).
- **Why the screws:** both screw sets in the CAD end short of their threads (G10). S3 and S4 cost money but fix it.
- **"Best"** means the lowest cost among the options our rules generate that pass Function and Fit; it is not a global
  optimum.

## Other methods examined

- Quiddity (recommended by the task) reads and recognises geometry; we also cut solids and write STEP in the original frame, which our pythonOCC pipeline already did, so we kept pythonOCC.
- A plate-thickness rule: [results/thickness_screen.md](results/thickness_screen.md) — the clean candidate (LosLagerHalterIsel) saves EUR 0.6–1.0 per assembly, the standoffs 0.2–0.3; the clamps (1.4–2.4 per pair) cannot be graded by our F4 model.
- FEA for whole-assembly stress (F5/F6) needs 1–2 days for a trustworthy model; we prove "no worse than the original" instead and state the limitation.

## Findings in the original design

- **Ball nut overload:** 3,000 N static rating / 6,800 N crash force = 0.44 < 1.2 (F7).
- **Rear-clamp M8 × 80:** end 12.0 mm short of the plate threads, so in the CAD the rear clamp is not screwed to the
  moving plate (G10).
- **Motor M5 × 50:** end 5.0 mm short of the FestLagerBlock threads (G10).
- **CAD motor vs BOM:** the CAD motor "Nema 23 76x56" (76 mm body, Ø6.35 shaft) differs from the BOM motor (3 Nm,
  57 × 57 × 114 mm per the shop's product title, Ø10 mm shaft
  ([StepperOnline 23HS45-4204S1 page](https://www.omc-stepperonline.com/nema-23-bipolar-3nm-425oz-in-8mm-diameter-4-2a-57x57x113mm-4-wires-stepper-motor-23hs45-4204s1):
  standard 10 mm)); the YAML's 3 Nm is used.
- **Coupling:** motor-side bore Ø8.0 vs motor shaft Ø6.35 (comment only, no grader). S1's 6.35 mm shaft also needs a
  coupling with a 6.35 mm motor-side bore; the CAD coupling has 8 mm (the same mismatch as the CAD motor). Not priced.
- **Tool stick-out:** 43.8 mm in the CAD vs 30 mm in the YAML. In the YAML frame the tool tips agree (z 68.6 vs 68.0),
  so the LC1 lever arm is unaffected; the CAD spindle body ends 14.4 mm above the YAML nose.

## Manufacturing and material review

From [results/process_review.md](results/process_review.md) (analysis, not graded):

- **Setups dominate:** 114 of 153.07 EUR/assembly at lot size 10. Fewer setups or bigger lots matter more than removing material.
- **Routes:** only SensorPlatteZ is cheaper off the mill (laser only, −5.69 EUR/assembly). The 20 mm parts stay on the 3-axis mill (laser quality limit, side features). 5-axis never wins (12.50 vs 2 × 6.00 EUR).
- **Material:** S235 fails NP5 (+3.9 kg); 6061 on all four assumption-material parts fails NP5 (+0.030 kg). The best passing combination (clamps only) saves 1.09 EUR but cannot be graded by F4; not built.
- **Winner:** unchanged under every route and material variant.
- **F4 margin:** the winner is at 1.0986 vs 1.10. F4 is a conservative upper bound, so the 1 mm vs 2 mm choice rests on a small margin.
- **Hole time** (0.3 min/hole, assumption) is not in the default model. It would add about 51 EUR/assembly and does not change the comparison.
- **Rolling direction:** not relevant here (aluminium stiffness is near isotropic; stresses < 5 MPa vs 62.5 MPa). It matters for bent sheet and machining distortion, one more reason for stress-relieved 5083 plate.

## Live requirement changes

Any value of `requirements/subassembly.yaml`, `requirements/rates.yaml`, `rules/cost_model.yaml` or
`rules/bought_parts.yaml` (Z ball nut rating) can be overridden in memory (printed, recorded in the outputs, never
written back; list items by id or part_id; keys may contain spaces):

```
python optimize.py --set "requirements:load_cases.LC1_cutting_force.force_N.value=400"
python optimize.py --set "requirements:limits.safety_factor_yield_LC2.minimum=1.5"
python optimize.py --set "cost_model:removal_rate_mm3_min=1000"
python optimize.py --set "rates:materials.EN AW-5083 plate.price_eur_kg=6"
python optimize.py --set "bought_parts:z_ball_nut.static_axial_rating_N.value=4000"
```

- **Thresholds written as text** (deflection 110%, thread engagement 1.5 × d, lead 0.1%) are read from the rule
  sentence, or from a numeric `value` key on the same item, which wins: `limits.tool_tip_deflection_LC1.value=1.05`
  (a ratio), `limits.thread_engagement.value=2` (× d), `non_physical_requirements.market.rules.NP1_lead_content.value=0.05`
  (% mass). A reworded sentence that cannot be parsed stops the run and names the key to set.
- **Tool tip:** z = spindle_nose_z_mm − tool_stick_out_mm (a different YAML tool_tip z prints a warning). It feeds the
  load-path analysis; F4 is a ratio bound and does not depend on it.
- **LC2 force:** the YAML force_N, scaled by an edit of screw_pitch_mm or screw_efficiency and by the torque ratio of a
  motor substitution (S1: 6800 × 0.9/3 = 2040 N).
- **Another alloy for a made part:** set `made_parts.parts.<part>.material`, and create its three
  `material_properties.<alloy>.*` values with `--set` (the only place where `--set` may create keys). Without a
  "<alloy> plate" price the "<alloy> bar" price is used for a cut-to-size blank (recorded in C1); G11 FAILs with
  "No sourced lead bound" for an alloy without a sourced bound (sourced: EN AW-5083, 6061, 6082). The original is
  re-priced with the same material.
- **A YAML change is a requirement change and applies to the original too:** e.g. R15 (material) gives Δ against a
  6061 original. F4 is a ratio bound, so a longer tool (R11) changes the absolute deflection but not the decision.
- **For a live requirement change**, add `--results scratch/results --out scratch/best` to every rehearsal command, so the published
  `results/` and `cases/best/` stay unchanged (`scratch/` is gitignored).

Seventeen changes are rehearsed in [results/live_change_rehearsal.md](results/live_change_rehearsal.md). Two give no ACCEPT,
by design: R5 (safety_factor_yield_LC2 1.5: F7 fails in every option; the run states that a motor ≤ 0.882 Nm would pass)
and R9 (IF3 travel 150 mm: the carried original travel 134.09 mm fails G6 in every option).

## Next steps

| Step | Why | Expected effect | Effort (rough) |
|---|---|---|---|
| Nesting and shared setups (scoped with a prototype, not part of the code) | Setups are 75% of the made-part cost at lot 10 | Setup sharing (same thickness and hole directions, 400 × 300 mm fixture) cuts setups per lot from 19 to 6, about −78 EUR/assembly: an optimistic upper bound (side-hole setups need the part on edge). Nesting whole plates raises material cost under today's model (29 → 74 EUR/assembly on 1000 × 2000 plates at lot 10), because cut-to-size blanks carry no premium. Neither changes the winner | About 45–60 min to integrate, with 7 assumptions to decide |
| Process route per part in the cost model (SensorPlatteZ laser only) | Process review | −5.69 EUR/assembly on totals; winner unchanged | < 1 h |
| Clamp stiffness in the F4 model | The clamps are in the LC1 path but not modelled | Allows clamp rules (thickness, material) to be graded | 1–2 h |
| Material selection rule over sourced alloys | 6061 is 19% cheaper per volume | Blocked today by NP5 (density 2.70 vs 2.66) and the clamp model; a few EUR at most | 1–2 h after the clamp model |
| Hand checks of the most loaded original parts (F5/F6) | F5/F6 prove "no worse than the original" only | Absolute safety factors for the original | About 2 h |
| Sourced hole/tapping time | Not in today's model (+51 EUR/assembly at 0.3 min/hole) | Realistic totals | < 1 h |

Smaller follow-ups: a 6.35 mm motor-side coupling bore for S1 (not priced); the S1 flange thickness from the maker's
drawing; a readable source for the 6061 yield (240 MPa); re-measuring Z travel only if a future rule changes the moving
parts.

## Limitations

- F5/F6 (whole-assembly stress) are not computed; they are UNCHANGED with a proof.
- G6 carries the original Z travel from a static sweep (`evidence/z_travel_sweep.yaml`); it is not recomputed.
- Thread engagement is checked only for the two joints we changed (M8 clamp, M5 motor).
- The spindle clamps are in the LC1 load path but not in the F4 stiffness model, so no rule may change their geometry
  or material.
- The cost model is ours ([results/manufacturing_review.md](results/manufacturing_review.md)); the winner is the same in
  all eight variants.
- The S1 flange thickness is not from a drawing (original flange face kept); the drive check uses the maker's pull-out
  curve at 24 V.
- Part-table interfaces come from bounding-box contact; the envelope's x-min margin is 0.05 mm (box rounding).
- S1's 6.35 mm shaft also needs a coupling with a 6.35 mm motor-side bore; the CAD coupling has 8 mm (the same mismatch
  as the CAD motor). Not priced.

## Repository layout

| Folder | Content |
|---|---|
| `requirements/` | Task inputs: subassembly.yaml, rates.yaml (unchanged) |
| `cad/` | Source STEP (unchanged) |
| `rules/` | Rule files, their schema ([rules/SCHEMA.md](rules/SCHEMA.md)), the cost model and bought-part data |
| `src/` | Cache, geometry, graders, datum registration, load path |
| `cache/` | STEP facts and BREP solids (keyed by the STEP hash) |
| `cases/` | Bench cases: original, failing, best (written by optimize.py) |
| `results/` | Reports, options.csv, option STEP files, reviews |
| `evidence/` | Measured Z travel from the earlier sweep |
| `tools/` | Thickness screen, process review, EVALS writer (optional) |
| `tests/` | Unit and grader tests |

**Code map**

| File | What it does / what it owns |
|---|---|
| `optimize.py` | Generates the 80 options (trim values × substitution subsets), grades them, selects the best; writes `results/options.csv`, `results/options/*.step`, `results/load_path.json`, `cases/best/` |
| `bench.py` | Grades every case folder in `--cases`; one score row per case, `results/<case>.json`, verdict vs the manifest |
| `src/cache.py` | One STEP import → `cache/<hash>-v4/` (facts.json, connector and guide-plate BREPs, threaded joints, Z motor) |
| `src/config.py` | Reads the YAML inputs and rule files, schema validation, `--set` overrides, text thresholds, material properties |
| `src/geometry.py` | STEP/BREP I/O, bounds, faces, booleans, the symmetric trim, simplified motor and screw solids |
| `src/datum.py` | Registers the STEP frame to the YAML frame (fit to the IF4 carriages); used by G9 and the tool report |
| `src/load_path.py` | LC1 load path and stiffness ranking (analysis, `results/load_path.json`); connector arm model for F4 |
| `src/function_eval.py` | Function grader F1–F7 (connector stresses, F4 bound, F5/F6 proofs, LC2 drive force, F7 ball nut) |
| `src/fit_eval.py` | Fit grader G0–G17 (change confinement, interfaces, envelope, thread engagement, NP1–NP5, bought parts) |
| `src/cost_eval.py` | Cost grader C1–C3 (plate-blank cost model, bought-part price deltas) |
| `src/grade.py` | Grades one case: runs the three graders, summary, verdict, compliance, baseline findings, drive information |
| `src/records.py` | Calculation records (formula, inputs, result, threshold, status), UNCHANGED proofs, report validation |
| `tools/thickness_screen.py` | Optional: regenerates the evidence report `results/thickness_screen.md` |
| `tools/process_review.py` | Optional: regenerates `results/process_review.md` (routes, materials) |
| `tools/write_evals.py` | Optional: regenerates `EVALS.md` from `results/best.json` |

## Licence

- Hardware files: the STEP files in `cad/` (original), `cases/` and `results/options/` (changed) are design files of
  MyCNC V4 by Martin Allemann (https://github.com/mallemann/mycnc), licensed CERN-OHL-S-2.0; changed files keep that
  licence ([cases/NOTICE.md](cases/NOTICE.md), [results/options/NOTICE.md](results/options/NOTICE.md),
  [cad/NOTICE.md](cad/NOTICE.md)).
- Code: MIT ([LICENSE](LICENSE))
