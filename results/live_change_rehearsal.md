# Live requirement changes: rehearsal (2026-11-24)

Each row is one `optimize.py` run with one in-memory override against the default (removal rate 50000 mm³/min,
80 options = 10 trims × 8 substitution subsets). No YAML file is edited; the override is printed at the start of the
run and recorded in `options.csv` and the case JSON. Wall time includes Python start-up (machine with other load).

**Default:** winner 2 mm + S1 + S3 + S4, Δ −9.134517 €/assembly (made −0.158397, bought −8.976121); 2 ACCEPT
(1 mm and 2 mm, each with S1 + S3 + S4).

| # | Change | Winner | Δ total € (made) | ACCEPT | What decides it | Wall s |
|---|---|---|---|---|---|---|
| R1 | Deflection limit 110% → 105% | **1 mm** + S1 + S3 + S4 | −9.055319 (−0.079198) | 1 | F4: 2 mm has 1.0986 > 1.05; 1 mm 1.0477 | 35.7 |
| R2 | Deflection limit 110% → 120% | **3 mm** + S1 + S3 + S4 | −9.213716 (−0.237595) | 3 | F4: 3 mm 1.1529 ≤ 1.20, 4 mm 1.2110 > 1.20 | 34.9 |
| R3 | LC1 force 200 → 400 N | 2 mm + S1 + S3 + S4 | −9.134517 (−0.158397) | 2 | Unchanged. Winner F1 0.868, F2 2.381, F3 1.143 MPa ≤ 62.5; F4 is a ratio (unchanged) | 30.0 |
| R4 | safety_factor_yield_LC1 2.0 → 4.0 | 2 mm + S1 + S3 + S4 | −9.134517 (−0.158397) | 2 | Unchanged. Allowable 31.25 MPa; winner F1 0.434, F2 1.190, F3 0.571 MPa | 26.2 |
| R5 | safety_factor_yield_LC2 1.2 → 1.5 | **none** | — | **0** | **F7 fails in all 80 options**: 3000 / 2040 N = 1.471 < 1.5. The run prints: "F7 needs an LC2 force <= 2000 N, i.e. a motor holding torque <= 0.882 Nm (available: S1 0.9 Nm)". `cases/best` is not changed. (Rerun after the LC2 hardening; before it: 2036 N, 1.474, 0.884 Nm) | 26.6 |
| R6 | Lot size 10 → 50 | 2 mm + S1 + S3 + S4 | −9.134517 (−0.158397) | 2 | Δ unchanged (the trim changes no setup); made-part total 153.07 → 61.87 € | 33.9 |
| R7 | Labour rate 30 → 60 €/h | 2 mm + S1 + S3 + S4 | −9.158517 (−0.182397) | 2 | Same winner; made-part total 194.60 € | 33.2 |
| R8 | Removal rate 50000 → 1000 mm³/min (old default) | 2 mm + S1 + S3 + S4 | −12.662517 (−3.686397) | 2 | Same winner; the old made-part Δ is reproduced exactly | 36.7 |
| R9 | IF3 travel 80 → 150 mm | **none** | — | **0** | **G6 fails in all 80 options**: carried original travel 134.09 mm < 150 mm | 28.3 |
| R10 | Envelope max z 598 → 578 mm | 2 mm + S1 + S3 + S4 | −9.134517 (−0.158397) | 2 | G9 now fails in the 40 options without S1 (original motor rear at YAML z 581.5 > 578); with S1 the motor ends at 557.5 (margin 20.5 mm) | 32.0 |

In every row the cheaper options that lose fail F4 (longer trims) or G10 (S1 without both screw substitutions); options
without S1 fail F7. All ten changes moved the result in the expected direction; none needed forcing.

**Hardening rows** (values that were ignored or fragile before; same scratch-folder method, after the fixes). The LC2
force is now the YAML force_N scaled by a pitch/efficiency edit and by the motor torque ratio, so S1 gives
6800 × 0.9/3 = 2040 N (F7 1.471; before: 2035.75 N, 1.474, the 6786 → 6800 rounding).

| # | Change | Winner | Δ total € (made) | ACCEPT | What decides it | Wall s |
|---|---|---|---|---|---|---|
| R11 | tool_stick_out_mm 30 → 50 | 2 mm + S1 + S3 + S4 | −9.134517 (−0.158397) | 2 | **Surprise: F4 does not move.** F4 is a ratio bound (case/original compliance of the connector contact and arms), independent of the lever arm; the tool tip (now z = 98 − 50 = 48, warning that the YAML says 68.0) only changes `load_path.json` (±Y moving-plate deflection 0.0695 → 0.0839 mm) | 13.6 |
| R12 | LC2 force_N 6800 → 8000 | 2 mm + S1 + S3 + S4 | −9.134517 (−0.158397) | 2 | Original F7 3000/8000 = 0.375 FAIL; S1 8000 × 0.9/3 = 2400 N, factor 1.250 ≥ 1.2 PASS (as expected) | 19.2 |
| R13 | screw_pitch_mm 2.5 → 5 | 2 mm + S1 + S3 + S4 | −9.134517 (−0.158397) | 2 | All LC2 forces halve (original 3399.9 N, S1 1020 N). Options without S1 still fail F7: 0.882 < 1.2; S1 2.941 (published value: prints a warning) | 15.5 |
| R14 | Z ball nut rating 3000 → 4000 N | 2 mm + S1 + S3 + S4 | −9.134517 (−0.158397) | 2 | Original 4000/6800 = 0.588 still FAIL; S1 1.961 (as expected) | 13.7 |
| R15 | ZXVerbinder EN AW-5083 → EN AW-6061, properties set with --set (E 70000 EN 1999-1-1, yield 240 MPa typical value (datasheet listing), density 2.70 rates.yaml) | 2 mm + S1 + S3 + S4 | −9.117241 (−0.141120) | 2 | Runs. Same verdicts: F4 unchanged at E 70000, F1–F3 allowable 120 MPa, G11 PASS (sourced 0.05% bound for 6061), G15 PASS. C1 uses the "EN AW-6061 bar" price for a cut-to-size blank and says so. Note: a material override changes the original too, so Δ is against a 6061 original | 16.0 |
| R16 | EN AW-5083 plate 5 → 6 €/kg | 2 mm + S1 + S3 + S4 | −9.152818 (−0.176698) | 2 | Same winner; the trim saves more as material costs more | 19.1 |
| R17 | Deflection limit as a number (`value: 1.05`) instead of text | **1 mm** + S1 + S3 + S4 | −9.055319 (−0.079198) | 1 | Same as R1 | 17.0 |

## Commands for live changes

Run from the repository root in PowerShell after the PATH line in the README, "How to run" (`$e` = the forge-cad
environment). Every
command writes to `scratch/` (`--results scratch/results --out scratch/best`, gitignored), so the published `results/`
and `cases/best/` stay unchanged. (The rehearsal itself wrote to a scratch folder the same way.)

```powershell
$env:PYTHONIOENCODING="utf-8"
# R1
& "$e\python.exe" optimize.py --results scratch/results --out scratch/best --set "requirements:limits.tool_tip_deflection_LC1.rule=The deflection of the changed design must not be more than 105% of the deflection of the original design."
# R2
& "$e\python.exe" optimize.py --results scratch/results --out scratch/best --set "requirements:limits.tool_tip_deflection_LC1.rule=The deflection of the changed design must not be more than 120% of the deflection of the original design."
# R3
& "$e\python.exe" optimize.py --results scratch/results --out scratch/best --set "requirements:load_cases.LC1_cutting_force.force_N.value=400"
# R4
& "$e\python.exe" optimize.py --results scratch/results --out scratch/best --set "requirements:limits.safety_factor_yield_LC1.minimum=4.0"
# R5
& "$e\python.exe" optimize.py --results scratch/results --out scratch/best --set "requirements:limits.safety_factor_yield_LC2.minimum=1.5"
# R6 (prints a warning: lot_size is a task_rule value and differs from rates.yaml)
& "$e\python.exe" optimize.py --results scratch/results --out scratch/best --set "requirements:production.lot_size.value=50"
# R7
& "$e\python.exe" optimize.py --results scratch/results --out scratch/best --set "rates:labour_rate_eur_h=60"
# R8
& "$e\python.exe" optimize.py --results scratch/results --out scratch/best --set "cost_model:removal_rate_mm3_min=1000"
# R9 (prints a warning: travel_mm is a published value)
& "$e\python.exe" optimize.py --results scratch/results --out scratch/best --set "requirements:interfaces_that_must_not_change.IF3_z_travel.travel_mm.value=150"
# R10
& "$e\python.exe" optimize.py --results scratch/results --out scratch/best --set "requirements:envelope.max_mm.z=578.0"
# R11 (prints a warning: the YAML tool_tip.z_mm 68.0 is replaced by 98.0 - 50)
& "$e\python.exe" optimize.py --results scratch/results --out scratch/best --set "requirements:reference_points.tool_stick_out_mm.value=50"
# R12
& "$e\python.exe" optimize.py --results scratch/results --out scratch/best --set "requirements:load_cases.LC2_crash.force_N.value=8000"
# R13
& "$e\python.exe" optimize.py --results scratch/results --out scratch/best --set "requirements:load_cases.LC2_crash.derivation.screw_pitch_mm.value=5"
# R14 (rules/bought_parts.yaml)
& "$e\python.exe" optimize.py --results scratch/results --out scratch/best --set "bought_parts:z_ball_nut.static_axial_rating_N.value=4000"
# R15 (the three material_properties keys of a new alloy may be created with --set)
& "$e\python.exe" optimize.py --results scratch/results --out scratch/best --set "requirements:made_parts.parts.ZXVerbinder.material=EN AW-6061" --set "requirements:material_properties.EN AW-6061.elastic_modulus_MPa=70000" --set "requirements:material_properties.EN AW-6061.yield_strength_MPa=240" --set "requirements:material_properties.EN AW-6061.density_g_cm3=2.70"
# R16
& "$e\python.exe" optimize.py --results scratch/results --out scratch/best --set "rates:materials.EN AW-5083 plate.price_eur_kg=6"
# R17 (a numeric value wins over the rule text)
& "$e\python.exe" optimize.py --results scratch/results --out scratch/best --set "requirements:limits.tool_tip_deflection_LC1.value=1.05"
# Score the winner with the same change (example: R3)
& "$e\python.exe" bench.py --cases scratch/ --results scratch/results --set "requirements:load_cases.LC1_cutting_force.force_N.value=400"
```
