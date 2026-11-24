# EVALS

Graders for one design change (`src/function_eval.py`, `src/fit_eval.py`, `src/cost_eval.py`). Each check is a record with formula, inputs with units, result, threshold and status (`results/<case>.json`). This page is written by `tools/write_evals.py` from `results/best.json` (winner `best`).

**Status rules.** PASS/FAIL compare a computed value with its threshold; a computed failing value is always FAIL. UNCHANGED only for a check that is not computed, with a proof naming checks that must PASS (and computed conditions); a proof that does not hold counts as FAIL. A grader PASSes with 0 failed checks; ACCEPT = all three graders PASS; the original is REFERENCE.

## Function
| ID | Metric | Threshold | Source | Winner |
|---|---|---|---|---|
| F1 | Tear-out stress at the outer bolt hole, full LC1 force on one bolt | <= 62.5 MPa | LC1 force; yield / safety_factor_yield_LC1 | 0.4341 MPa PASS |
| F2 | Bearing stress of the M6 bolt in the ZXVerbinder | <= 62.5 MPa | as F1 | 1.19 MPa PASS |
| F3 | Net-section stress beside the outer hole | <= 62.5 MPa | as F1 | 0.5714 MPa PASS |
| F4 | Upper bound of the LC1 tool-tip deflection ratio, case / original (contact + arm) | <= 1.1 | limits.tool_tip_deflection_LC1 (110%) | 1.099 PASS |
| F5 | Whole-assembly yield safety factor, LC1 (not modelled) | >= 2 | safety_factor_yield_LC1; proof G0, G3 | – UNCHANGED |
| F6 | Whole-assembly yield safety factor, LC2 (not modelled) | >= 1.2 | safety_factor_yield_LC2; proof G0 + F_new <= F_orig | – UNCHANGED |
| F7 | Z ball nut: static rating (rules/bought_parts.yaml) / LC2 force | >= 1.2 | safety_factor_yield_LC2 (our interpretation, Appendix) | 1.471 PASS |

## Fit
| ID | Metric | Threshold | Source | Winner |
|---|---|---|---|---|
| G0 | Changes outside the declared ones, rule-1 conformance, substitution geometry | <= 0 | ours: basis of every proof | 0 PASS |
| G1 | Placed copies of the changed part differ | <= 0.01 mm³ | task: STEP in the original coordinates | 1.455e-11 mm³ PASS |
| G2 | Material added to the changed part (removal only) | <= 0.01 mm³ | ours: machinable from the original stock | 1.455e-11 mm³ PASS |
| G3 | Change of the protected core (holes, bolt seats, ball-nut face) | <= 0.01 mm³ | IF4/IF5 bolt pattern | 4.671e-09 mm³ PASS |
| G4 | Clamp bore deviation from 80 mm | <= 1e-05 mm | IF1_spindle_clamp | 0 mm PASS |
| G5 | Moved or missing spindle occurrences | <= 0 | IF2_spindle_axis | 0 PASS |
| G6 | Z travel of the moving set (original sweep, carried while the proof holds) | >= 80 mm | IF3_z_travel | 134.1 mm UNCHANGED |
| G7 | Moved or missing X carriages | <= 0 | IF4_x_axis_carriages | 0 PASS |
| G8 | Ball-nut pad area change, nut parts unmoved | <= 0.01 mm² | IF5_x_axis_ball_nut | 2.274e-13 mm² PASS |
| G9 | Smallest margin to the envelope box in the YAML frame (tool excluded) | >= 0 mm | envelope | 0.05 mm PASS |
| G10 | Thread engagement of the rear-clamp M8 and motor M5 joints | >= 1.5 d | limits.thread_engagement | 2 d PASS |
| G11 | Lead bound of the made-part alloy (EN 573-3) | <= 0.1 % mass | NP1_lead_content | 0.05 % mass PASS |
| G12 | Fastener labels without an ISO metric designation | <= 0 | NP2_metric_threads | 0 UNCHANGED |
| G13 | Made parts without an approved plate thickness | <= 0 | NP3_stock_thickness | 0 PASS |
| G14 | Padded envelope minus parcel limit | <= 0 mm | NP4_parcel_size | -252 mm PASS |
| G15 | Made-part mass change | <= 0 kg | NP5_mass | -0.01192 kg PASS |
| G16 | Deviation of made-part quantities | <= 0 | made_parts | 0 PASS |
| G17 | Changed bought parts without reason, both prices and a source | <= 0 | bought_parts | 0 PASS |

## Cost
| ID | Metric | Threshold | Source | Winner |
|---|---|---|---|---|
| C1 | Cost of the changed part (all occurrences) | <= 16.43 EUR/assembly | task: cost from the geometry | 16.28 EUR/assembly PASS |
| C2 | Manufacturing cost of all made parts | <= 153.1 EUR/assembly | rates.yaml + rules/cost_model.yaml | 152.9 EUR/assembly PASS |
| C3 | Cost change of the subassembly incl. bought parts | < 0 EUR/assembly | task: the change is less expensive | -9.135 EUR/assembly PASS |

## Hand check
- **F7 (winner):** F = F_YAML · s · T/T_YAML = 6800 · 1 · 0.9/3 = 2040.00 N (s = 1: 2·π·3·0.9/(2.5/1000) = 6785.84 N matches the YAML's 6786 N within its rounding; an edited pitch or efficiency sets s); 3000 / 2040.00 = 1.471 ≥ 1.2.
- **One ZXVerbinder at 50000 mm³/min:** stock 133 × 43 × 20 mm → 0.304251 kg × 5.00 €/kg = 1.521254 €; chips 22114.397 mm³ ÷ 50000 = 0.442288 min × 90 €/h ÷ 60 = 0.663432 €; setup 1 × 40 min × 90 €/h ÷ 60 ÷ 10 = 6.000000 €; chip credit 22114.397 × 2.66e-6 kg × 0.80 €/kg = 0.047059 €; **total 8.137626 €**.

## Appendix
**Assumptions and interpretations.** No value in `requirements/*.yaml` is changed. What we interpret or add:

| Item | Interpretation | Why |
|---|---|---|
| F7 | The nut's static rating is its yield: rating / LC2 force ≥ safety_factor_yield_LC2 | The rating is the onset of permanent deformation, which LC2 forbids |
| LC2 torque | Follows the bought-part change S1 (0.9 Nm, datasheet) | The YAML's 3 Nm describes the replaced motor; the scenario is unchanged |
| G9 | Box checked in the YAML frame (rigid fit to the IF4 carriages, `src/datum.py`); tool solid excluded | The box starts at the spindle nose; the tool is below it |
| G6 | Original travel 134.09 mm (old sweep, `evidence/`) carried while the proof holds | Not recomputed here |
| Prices | Excluding VAT; per piece = amount / VAT divisor / quantity | Comparable prices |
| Cost model | Removal rate 50000 mm³/min; blank = box on the next NP3 plate; one setup per hole-axis family; facing 0 mm | Ours: see `rules/cost_model.yaml`, `results/manufacturing_review.md` |

**Changed bought parts** (YAML `bought_parts`; prices excl. VAT, quoted 2026-11-24):

| ID | From → to | Reason | Price from → to (per piece) | Δ €/assy | Source |
|---|---|---|---|---|---|
| S1 | StepperOnline 23HS45-4204S, NEMA 23 → StepperOnline 23HS20-2004S, NEMA 23 | F7: with the 3 Nm motor the nut factor is 0.44 < 1.2; with 0.9 Nm it is 1.471. Driver current 2.0 A | 28.7 → 17.13 USD | -10.398131 | [from](https://www.omc-stepperonline.com/nema-23-bipolar-3nm-425oz-in-4-2a-57x57x114mm-4-wires-stepper-motor-cnc.html), [to](https://www.omc-stepperonline.com/nema-23-bipolar-1-8deg-0-9-nm-127-5oz-in-2a-3-6v-57x57x52mm-4-wires.html) |
| S3 | 4 x DIN 912 M8 x 80 8.8 galvanised → 4 x DIN 912 M8 x 110 8.8 galvanised | G10: head seat to thread 92.0 mm; the original screws engage 0 mm, 110 mm engage 18.0 mm ≥ 1.5 d | 0.3006 → 0.5459 EUR | +0.981129 | [from](https://www.egger-online.de) (art. 8000165544), [to](https://www.egger-online.de/Zylinderschraube-DIN-912-m-Innensechskant-M-8-x-110-8-8-galvanisch-verzinkt-100-Stueck-2951901) (art. 8000165550) |
| S4 | 4 x DIN 912 M5 x 50 8.8 galvanised → 4 x DIN 912 M5 x 65 8.8 galvanised | G10: head seat to thread 55.0 mm; the original screws engage 0 mm, 65 mm engage 10.0 mm ≥ 1.5 d | 0.06958 → 0.1798 EUR | +0.440881 | [from](https://www.egger-online.de) (art. 8000165459), [to](https://www.egger-online.de) (art. 8000165462) |
