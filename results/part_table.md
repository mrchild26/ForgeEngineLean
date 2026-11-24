# Made parts: why only the ZXVerbinder is changed

The design rule changes one made part, the ZXVerbinder (symmetric X-end trim, 2 mm in the winner). The other changes
are bought parts (S1 motor, S3 and S4 screws). This table is the evidence for that choice.

Columns:
- **LC1 path / stiffness share:** share of the modelled LC1 tool-tip deflection (`results/load_path.json`, nominal
  beam models of the moving plate, the fixed guide plate and the ZXVerbinder pair; the clamps are in the path but not
  modelled). **LC2 path:** carries the Z crash force (motor → screw → nut → moving set; reaction through the fixed
  bearing into the guide plate).
- **Interfaces:** bounding-box contact (≤ 0.05 mm) with the interface parts: IF1/IF2 spindle, IF3 Z rails and Z
  carriages, IF4 X carriages, IF5 X ball nut. Box contact is an approximation of real contact.
- **Setups:** measured per occurrence (cost model). **Fill:** finished volume / stock volume (bounding box on the next
  approved plate). **Cost:** EUR/assembly at the default removal rate 50000 mm³/min.

| Part | Qty | Material (source) | LC1 path | Stiffness share (±X, ±Y) | LC2 path | Interfaces | Setups | Fill | Cost € | Changed? |
|---|---|---|---|---|---|---|---|---|---|---|
| MotorHalterPlatteIsel | 1 | EN AW-5083 (assumption) | yes (moving plate, modelled) | X 55%, Y 43% | yes | IF3 | 1 | 93% | 11.43 | Not changed: 93% fill leaves little stock, and it is the most compliant modelled part for ±X (55%), so any cut costs stiffness directly; carries the Z carriages and the clamps. |
| MotorHalter1 | 2 | EN AW-5083 (assumption) | yes (clamp, not modelled) | – | yes | IF1/IF2 | 2 + 2 | 55% | 29.44 | Not changed: the low fill comes from the Ø80 IF1 bore, which must not change; in the LC1 and LC2 paths. Its M8 clamp joint is fixed by S3. |
| MotorHalter2 | 2 | EN AW-5083 (assumption) | yes (clamp, not modelled) | – | yes | IF1/IF2 | 2 + 2 | 52% | 30.00 | Not changed: as MotorHalter1 (IF1 bore); it holds the M8 head seats that S3 keeps. |
| ZFuehrungsHalter | 1 | EN AW-5083 (published) | yes (fixed guide plate, modelled) | X 21%, Y 57% | yes | IF3, IF4 | 2 | 98% | 22.25 | Not changed: 98% fill; the most compliant modelled part for ±Y (57%); carries IF3 rails and IF4 carriages. |
| FestLagerHalterIsel | 1 | EN AW-5083 (published) | no | – | yes | IF3 | 1 | 93% | 8.61 | Not changed: 93% fill; fixed-bearing holder in the LC2 thrust path. |
| LosLagerHalterIsel | 1 | EN AW-5083 (published) | no | – | no (floating bearing) | IF3, IF4 | 1 | 85% | 8.53 | Not changed: 85% fill; locates the screw end; 8.53 EUR, little to gain. |
| FestLagerBlock | 1 | EN AW-5083 (published) | no | – | yes | – | 1 | 63% | 7.48 | Not changed: the 63% fill is the bearing bore; in the LC2 thrust path; holds the M5 motor threads (S4 engages them 10 mm). |
| SensorPlatteZ | 1 | EN AW-5083 (published) | no | – | no | – | 1 | 83% | 6.15 | Not changed: 6.15 EUR of which 6.00 EUR is the setup share; nothing to gain. |
| Nema23HalterFuss | 2 | EN AW-5083 (published) | no | – | no (motor torque only) | – | 1 + 1 | 89% | 12.74 | Not changed: 89% fill; the 50 mm standoffs set the motor-screw stack (S4 length depends on them). |
| ZXVerbinder | 2 | EN AW-5083 (assumption) | yes, X only (modelled) | X 25%, Y – | no (ideal axial X drive) | IF5 | 1 + 1 | 80% | 16.43 | Changed (rule 1): 80% fill with stock at both X ends outside the bolt pattern; loaded only in ±X (25% of the modelled X deflection), so F4 limits the trim to 2 mm; bolt pattern and IF5 pad protected (G3, G8). |

Made-part total: **153.07 EUR/assembly** (original design, default cost model). Sources: `cache/` facts,
`results/load_path.json`, `rules/cost_model.yaml`; generated 2026-11-24.
