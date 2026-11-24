# Manufacturing review: does the winner depend on our cost assumptions?

**Answer: no.** The winner is **2 mm trim + S1 (0.9 Nm motor) + S3 (M8 × 110) + S4 (M5 × 65)** in all eight variants.
The same two options are ACCEPT every time (1 mm and 2 mm, each with S1 + S3 + S4). The cost model only sets prices;
F4, F7 and G10 decide what is ACCEPT. What changes is the size of the saving. At realistic removal rates the made-part
saving shrinks to 10–45 cents, and the bought-part delta (−8.976121 €: S1 −10.398131, S3 +0.981129, S4 +0.440881) is
95–98% of the total.

Method: `optimize.py --set cost_model:<key>=<value>` (in-memory overrides, recorded in `options.csv`); one variant at a
time against the then default (removal rate 1000 mm³/min). 80 options per variant. Since phase 3b the default is
50000 mm³/min (row "a. 50000"), chosen from this review.

| Variant | Winner | Δ made | Δ bought | Δ total | ACCEPT | Original made-part total | Top 3 parts (original, €/assembly) |
|---|---|---|---|---|---|---|---|
| Default: 1000 mm³/min | 2 mm + S1 + S3 + S4 | −3.686397 | −8.976121 | **−12.662517** | 2 | 671.18 | MotorHalter2 188.97, MotorHalter1 168.78, ZXVerbinder 84.98 |
| a. 10000 mm³/min | 2 mm + S1 + S3 + S4 | −0.446397 | −8.976121 | −9.422517 | 2 | 195.37 | MotorHalter2 42.98, MotorHalter1 40.82, ZFuehrungsHalter 24.02 |
| a. 50000 mm³/min | 2 mm + S1 + S3 + S4 | −0.158397 | −8.976121 | −9.134517 | 2 | 153.07 | MotorHalter2 30.00, MotorHalter1 29.44, ZFuehrungsHalter 22.25 |
| a. 100000 mm³/min | 2 mm + S1 + S3 + S4 | −0.122397 | −8.976121 | −9.098517 | 2 | 147.79 | MotorHalter2 28.38, MotorHalter1 28.02, ZFuehrungsHalter 22.03 |
| a. 340000 mm³/min | 2 mm + S1 + S3 + S4 | −0.096985 | −8.976121 | −9.073106 | 2 | 144.05 | MotorHalter2 27.23, MotorHalter1 27.02, ZFuehrungsHalter 21.87 |
| b. facing 1.0 mm (20 → 25 mm plate) | 2 mm + S1 + S3 + S4 | −6.285613 | −8.976121 | −15.261733 | 2 | 1503.07 | ZFuehrungsHalter 323.45, MotorHalter2 273.83, MotorHalter1 248.34 |
| c. +1 setup per part (flip) | 2 mm + S1 + S3 + S4 | −3.686397 | −8.976121 | −12.662517 | 2 | 755.18 | MotorHalter2 200.97, MotorHalter1 180.78, ZXVerbinder 96.98 |
| d. 50000 + facing 1.0 + 1 setup | 2 mm + S1 + S3 + S4 | −0.229213 | −8.976121 | −9.205333 | 2 | 259.74 | MotorHalter2 44.31, MotorHalter1 43.61, ZFuehrungsHalter 35.87 |

**The removal rate matters most for the total.** Raising it from 1 to 50 cm³/min cuts the original made-part cost by
77% (671 → 153 €), and the made-part saving falls from 3.69 to 0.16 €. Facing more than doubles the total at
1 cm³/min (more chips from thicker plate). In the realistic case d it adds 22.67 €, and the extra setups add 84.00 €
(14 occurrences × 6 €) to the 153.07 € of 50000 alone. The extra setup does not change Δ: the trim removes no setup, so
the extra setup appears in both designs.

**Hand check, one ZXVerbinder after the 2 mm trim, at 50000 mm³/min:** stock 133 × 43 × 20 mm = 114,380 mm³ →
0.304251 kg × 5.00 €/kg = 1.521254 €. Chips 114,380 − 92,265.603 = 22,114.397 mm³ ÷ 50,000 = 0.442288 min ×
(60 + 30) €/h ÷ 60 = 0.663432 €. Setup 1 × 40 min × 90 €/h ÷ 60 ÷ lot 10 = 6.000000 €. Chip credit 22,114.397 ×
2.66e-6 kg × 0.80 €/kg = 0.047059 €. **Total 8.137626 €** (original piece 8.216825 €; × 2 pieces = −0.158397 €, the
"a. 50000" made-part Δ).

## Assumptions

- **Removal rate 1000 mm³/min:** our assumption (a conservative placeholder). Sandvik Coromant gives
  Q = ap × ae × vf / 1000 cm³/min with vf = fz × n × zc
  ([formulas for milling, metric, p. H 79](https://cdn.sandvik.coromant.com/files/sitecollectiondocuments/services/metal-cutting-e-learning/formulas-and-definitions/formulas-and-deinitions-for-milling-metric-enu.pdf)).
  - Kyocera 3AFK, Ø10 mm, 3 flutes, A5052 ([brochure p. 3](https://kyocera-componentes.com.br/pdf/3afk_EN.pdf)):
    - slotting ap × ae = 10 × 10 mm at vf = 3,400 mm/min → Q = 340 cm³/min;
    - shouldering 15 × 3 mm at 4,600 mm/min → 207 cm³/min;
    - the brochure's user case study states 130 cm³/min.
  - Hoffmann GARANT Master Alu SlotMachine Ø5 mm, Z = 3
    ([datasheet](https://cdn.hoffmann-group.com/dsh/en-GB/dsh_en-gb_3365659.pdf)): vc 450 m/min, fz 0.06 mm,
    full slot 1 × D. That gives n = 28,648 rpm, vf = 5,157 mm/min and Q = 129 cm³/min, and needs a 28,600 rpm spindle.
  - These are rates while cutting. Air moves, finishing passes and tool changes lower the average, so the variants span
    10 to 340 cm³/min.
  - The Cutwel aluminium end-mill page was fetched, but its text gave no cutting data.
- **Blank = bounding box on the next approved plate ≥ part thickness:** our assumption (plates from subassembly.yaml NP3).
  The default (facing 0) needs 20 mm plate usable as delivered, i.e. precision-milled cast 5083 plate. Rolled plate
  needs facing: variant b.
- **Setups = one per cylindrical axis direction of the part:** our assumption; variant c adds a flip to every part.
- **Lot size 10:** subassembly.yaml (task_rule). **Rates, material and chip prices:** rates.yaml (task placeholders).
- **Bought parts** (excl. VAT, per piece computed from the quoted pack price, 2026-11-24):
  - S1: StepperOnline USD 28.70 → 17.13 at ECB 1.1127 USD/EUR (prices as given in the brief; the shop pages refused
    automated fetches).
  - S3 and S4: Egger, Reyher DIN 912 8.8 galvanised. M8 × 80 0.3006 → M8 × 110 0.5459 €; M5 × 50 0.0696 →
    M5 × 65 0.1798 € (incl.-VAT prices ÷ 1.19).

## Limitations

Not modelled: nesting several parts on one plate (saw cuts, plate offcuts), setup planning (shared fixtures, tool
changes, setups shared across part types), finishing passes, deburring, and any minimum charge per machine hour. One
average removal rate stands for all operations.
