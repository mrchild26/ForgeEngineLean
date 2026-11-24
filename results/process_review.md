# Process review: which manufacturing route fits each made part?

Analysis, not a grader (`tools/process_review.py`; geometry from the made-part BREPs in `cache/`). Rates from rates.yaml (lot 10); 3-axis at the default 50000 mm³/min. Routes: **A** 3-axis from a plate box (today's model); **B** 5-axis, same chips, one setup; **C** laser profile from plate + 3-axis for side features, steps, blind/tapped/small holes and tight bores; **D** laser only + hand tapping (2D profile, no side or tight features). Turning: not applicable (no rotational part). Press brake: not applicable (no bent sheet part; DFM idea below). All parts are below 300 mm, so no bed size (laser 3000 × 1500 mm) limits a route.

**New assumptions:** 0.3 min machine time per drilled or tapped hole on the mill, every route (today's model has none); hand tapping 0.5 min/hole; 1.0 min to finish a tight bore after the laser; nesting allowance 10% on the profile area; laser hole only if d ≥ plate thickness; deburring 3 min labour per part (same in every route, reported separately). Facing 0 mm stays: EN AW-5083 is stocked as rolled plate milled on both sides ([Mastel stock list](https://cdn.techpilot.com/public/94697/documents/f0d84aa3-e832-446b-8e0f-69633a1d6f8c/mastel_ll_10_08.pdf)); blanks cut to size at the plate price ([Bucher catalogue](https://www.bucher-stahl.de/fileadmin/user_upload/produkte/pdf/aluminium.pdf): formats 1000 × 2000 to 1500 × 3000 mm and "Fixzuschnitte").

**Laser limits:** TruLaser 3030 fiber, aluminium max 20 / 30 / 40 mm by laser option ([TRUMPF](https://www.trumpf.com/en_GB/products/machines-systems/2d-laser-cutting-machines/trulaser-3030-fiber-3040-fiber-3060-fiber/)); 3 kW TruLaser 1030 fiber max 15 mm ([datasheet](https://pdf.directindustry.com/pdf/trumpf-machines-systems/trulaser-1030-fiber/5691-854741.html)). A maximum is not production quality: ASSUMPTION 12 mm ([equipment guide](https://www.durmapress.com/laser-cutting-machine-aluminum-parameters-equipment-and-best-practices/): 3–6 kW covers 1–12 mm production), sensitivity 20 mm. Speeds (nitrogen, same guide, vendor guide values, not maker data): ≤ 3 mm 2,000–4,000 mm/min; ≤ 6 mm 800–2,000 mm/min; ≤ 10 mm 400–1,000 mm/min; ≤ 16 mm 200–600 mm/min; ≤ 25 mm 100–300 mm/min; base = low end, sensitivity = high end. Laser edges are not accepted for the IF1 Ø80 bore or bearing seats (finishing cut).

| Part | Qty | 2D profile | Side features | Tapped holes | Tight bores | A € | B € | C € | D € | Best | Saving vs A € | Limiting reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MotorHalterPlatteIsel | 1 | no | – | 8 | 0 | 24.03 | 35.72 | – | – | A 24.03 | 0.00 | 20 mm > 12 mm laser limit; at 20 mm and high speed C = 29.60; B: one 5-axis setup costs 12.50 € vs 6.00 € per 3-axis setup |
| MotorHalter1 | 2 | no | Y axis | 0 | 1 | 31.24 | 34.05 | – | – | A 31.24 | 0.00 | 20 mm > 12 mm laser limit; at 20 mm and high speed C = 39.00; B: one 5-axis setup costs 12.50 € vs 6.00 € per 3-axis setup |
| MotorHalter2 | 2 | no | Y axis | 0 | 1 | 31.80 | 34.76 | – | – | A 31.80 | 0.00 | 20 mm > 12 mm laser limit; at 20 mm and high speed C = 39.31; B: one 5-axis setup costs 12.50 € vs 6.00 € per 3-axis setup |
| ZFuehrungsHalter | 1 | no | Z axis | 17 | 0 | 37.10 | 43.55 | – | – | A 37.10 | 0.00 | 20 mm > 12 mm laser limit; at 20 mm and high speed C = 44.89; B: one 5-axis setup costs 12.50 € vs 6.00 € per 3-axis setup |
| FestLagerHalterIsel | 1 | no | – | 8 | 0 | 13.56 | 22.12 | – | – | A 13.56 | 0.00 | 20 mm > 12 mm laser limit; at 20 mm and high speed C = 18.19; B: one 5-axis setup costs 12.50 € vs 6.00 € per 3-axis setup |
| LosLagerHalterIsel | 1 | no | – | 0 | 1 | 12.58 | 20.92 | – | – | A 12.58 | 0.00 | 20 mm > 12 mm laser limit; at 20 mm and high speed C = 18.34; B: one 5-axis setup costs 12.50 € vs 6.00 € per 3-axis setup |
| FestLagerBlock | 1 | yes | – | 4 | 1 | 11.08 | 19.25 | – | – | A 11.08 | 0.00 | 20 mm > 12 mm laser limit; at 20 mm and high speed C = 15.96; B: one 5-axis setup costs 12.50 € vs 6.00 € per 3-axis setup |
| SensorPlatteZ | 1 | yes | – | 0 | 0 | 7.95 | 15.17 | 2.26 | 2.26 | D 2.26 | 5.69 | 2D profile on 3 mm plate: laser only; B: one 5-axis setup costs 12.50 € vs 6.00 € per 3-axis setup |
| Nema23HalterFuss | 2 | no | Z axis | 2 | 0 | 14.54 | 28.29 | 32.20 | – | A 14.54 | 0.00 | C keeps 2 mill setup(s) for side features/holes; B: one 5-axis setup costs 12.50 € vs 6.00 € per 3-axis setup |
| ZXVerbinder | 2 | no | Y axis | 0 | 0 | 20.03 | 34.98 | – | – | A 20.03 | 0.00 | 20 mm > 12 mm laser limit; at 20 mm and high speed C = 38.88; B: one 5-axis setup costs 12.50 € vs 6.00 € per 3-axis setup |

Costs are EUR per assembly (× quantity), without deburring. **Totals:** today's model **153.07**; route A with the new hole time 203.92; best route per part **198.24** (5.69 saved); with deburring (21.00) **219.24 EUR/assembly** (the realistic made-part cost under these assumptions). Sensitivities (best-route total, parts off route A): laser ≤ 12 mm, high speeds 198.08 (SensorPlatteZ); laser ≤ 20 mm, low speeds 198.24 (SensorPlatteZ); laser ≤ 20 mm, high speeds 198.08 (SensorPlatteZ).

**Winner check** (ZXVerbinder held on its cheapest route; the other parts do not change between options, so only its delta moves; re-selection over the 80 graded options in `results/options.csv`, Function/Fit verdicts unchanged, C3 re-evaluated; today's model reproduces every option's made delta to 1e-6): laser ≤ 12 mm, low speeds: ZXVerbinder on route A → winner `zxverbinder_trim_02mm+S1+S3+S4`, delta -9.134517 EUR (made -0.158397); laser ≤ 20 mm, high speeds: ZXVerbinder on route A → winner `zxverbinder_trim_02mm+S1+S3+S4`, delta -9.134517 EUR (made -0.158397). The hole time is the same before and after the trim, so the winner and its delta equal today's.

**Hand check, SensorPlatteZ route D:** profile area 2665.0 mm² × 3 mm × 1.1 × 2.66e-6 kg/mm³ × 5.00 €/kg = 0.1170 €; laser setup 10 min × 110 €/h ÷ 60 ÷ 10 = 1.8333 €; cut length outline 229.6 + holes 113.1 = 342.7 mm ÷ 2000 mm/min = 0.1714 min × 110 €/h ÷ 60 = 0.3142 €; tapping 0 holes; **total 2.2645 €** vs today 6.1503 € (of which 6.0000 € is the 3-axis setup) and route A 7.9503 € (4 holes × 0.3 min × 90 €/h ÷ 60 added).

## Material selection

Only MotorHalterPlatteIsel, MotorHalter1, MotorHalter2, ZXVerbinder have material_source: assumption; the other six are published EN AW-5083 and stay. Candidates = rates.yaml materials. Notes in the last column are judgment.

| Material | EUR/kg | g/cm³ | EUR/dm³ | E, MPa | Yield, MPa | Allowable (÷ 2.0) | Property source | Lead | Corrosion / stability |
|---|---|---|---|---|---|---|---|---|---|
| EN AW-5083 plate | 5.00 | 2.66 | 13.30 | 70000 | 125 | 62.5 | subassembly.yaml (assumption) | others each 0.05% ([G11 source](https://my.bikar.com/en_US/products/304_021-304-021-2)) | very good in a workshop; cast/milled plate is stress-relieved and stays flat |
| EN AW-6061 bar | 4.00 | 2.7 | 10.80 | 70000 | 240 | 120 | T6 Rp0.2 ≥ 240 MPa, EN 755-2 ([Aalco datasheet](https://www.aalco.co.uk/datasheets/Aalco-Metals-Ltd_Aluminium-Alloy-6061-T6-Extrusions_145.pdf.ashx), as listed; PDF not machine-readable here); E 70000 MPa EN 1999-1-1 3.2.5 ([Matmatch](https://matmatch.com/materials/alky1736-en-573-3-grade-aw-6061-f): 69–70 GPa) | unsourced here (EN 573-3 not read); not in G11's table | good; T6 bar may move when heavily machined |
| S235 steel plate | 2.00 | 7.85 | 15.70 | 210000 | 225 | 112.5 | ReH 235 MPa ≤ 16 mm, 225 MPa 16–40 mm ([Metinvest, EN 10025-2](https://metinvestholding.com/en/products/steel-grades/s235jr)); E 210000 MPa EN 1993-1-1 3.2.6 | not specified (no Pb addition); G11 has no steel entry | rusts with chips and lubricant unless coated |

| Part | Qty | A, 5083 plate € | F, 6061 flat bar (assumed section) € | S235 plate € | Δ mass 6061 / S235, kg |
|---|---|---|---|---|---|
| MotorHalterPlatteIsel | 1 | 24.03 | 26.63 (20 x 150) | 24.90 | +0.0133 / +1.7193 |
| MotorHalter1 | 2 | 31.24 | 34.37 (20 x 50) | 31.80 | +0.0046 / +0.6011 |
| MotorHalter2 | 2 | 31.80 | 34.35 (20 x 50) | 32.40 | +0.0047 / +0.6046 |
| ZXVerbinder | 2 | 20.03 | 23.68 (20 x 50) | 20.63 | +0.0076 / +0.9810 |

**Gates** (calculated where possible):
- **G15 (made-part mass must not rise):** S235 adds +3.906 kg → **S235 is out**. 6061 on all four adds +0.0301 kg; with the winner's trim (-0.0119 kg) the net is +0.0182 kg → fails. Subsets that pass with the trim: MotorHalter1; MotorHalter2; ZXVerbinder; MotorHalter1 + MotorHalter2.
- **F4 (≤ 1.1):** each changed part's compliance scales with 70000/E. 6061 at E 70000 (EN 1999-1-1): bound unchanged 1.0986. At 69000 (Matmatch low value): 1.1145 → the 2 mm trim would fail and the 1 mm trim (1.0629) would win. S235 (210000): ≤ 1.0000.
- **F1–F3:** the winner's largest connector stress is 1.19 MPa against 120 (6061) and 112.5 (S235, t > 16 mm) → pass.
- **G11 (lead):** the grader's table has a sourced bound for EN AW-5083 only; 6061 needs a sourced EN 573-3 entry first, otherwise G11 is not computable (FAIL). **G13 (NP3 plate thickness):** does not apply to bar; the flat-bar sections above are ASSUMPTIONS (the Bucher catalogue lists aluminium flat bar, e.g. EN AW-6060 40 × 20, but its PDF was not machine-readable here, so the section list is unverified).
- **Cost:** 6061 is 19% cheaper per volume (10.80 vs 13.30 EUR/dm³): on the same blanks, cut to size like today's plate, all four parts would save 2.57 EUR/assembly. Route F as specified loses instead (-11.91 EUR/assembly for all four): the 1 min saw cut costs 0.92 EUR per piece, and the assumed sections are wider than the parts.
- **Best feasible combination** (G15 with the trim; G11 once sourced): MotorHalter1 + MotorHalter2 on cut-to-size 6061 blanks, 1.09 EUR/assembly (route F: -5.67). Material is the same in all 80 options, so the winner does not change (at E = 70000).
- **Judgment (not graded):** keep 5083 plate for MotorHalterPlatteIsel (carries the Z carriages, needs flatness; 137 × 130 mm needs a 150 mm wide flat bar) and for the clamps (IF1 bore, roundness after heavy machining); 6061 bar is a fit for the ZXVerbinder (20 × 50 section, little machining).

**Rates context:** rates.yaml's 3-axis 60 + 30 = 90 EUR/h and 5-axis 95 + 30 = 125 EUR/h are task placeholders; a German price guide gives CNC milling (3-axis) 70–120 EUR/h and 5-axis 100–160 EUR/h ([clean-invoice](https://www.clean-invoice.com/feinwerkmechanik/kosten-und-kalkulation-feinwerkmechanik)), so both are in range.

**DFM ideas** (estimates from the formulas above; each needs a design change):
- SensorPlatteZ on laser only (route D): saves 5.69 EUR/assembly vs route A; no design change if the Ø4 holes may stay laser-cut (no fit).
- Setups dominate: 19 setups × 6.00 EUR = 114.00 of the 153.07 EUR today. Each removed setup saves 6.00 EUR per piece, e.g. the Z-axis end holes of ZFuehrungsHalter or the Y holes of the clamps: only if the joint can move to the main face.
- Nema23HalterFuss: the two 50 mm long Ø5 bores along an 8 mm wall force a second setup (14.54 EUR per pair). A bent sheet bracket (press brake: setup 15 min, 80 EUR/h) or a bought spacer sleeve could replace it; not priced: rates.yaml has no aluminium sheet and S235 sheet raises the mass (G15).
- Thinner plate for LosLagerHalterIsel (results/thickness_screen.md): 0.63–1.01 EUR/assembly; needs a 12 or 15 mm design check of the bearing seat depth.
- 6061 flat bar for the ZXVerbinder (route F, Material selection): needs a sourced lead entry (G11) and keeps the F4 margin only if E = 70000 MPa holds.
