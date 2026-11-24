# Thickness screen: could a made part use a thinner plate?

Bounding-box screen, not a grader (`tools/thickness_screen.py`, cache facts, cost model at 50000 mm³/min). Contact = box faces within 0.15 mm and overlapping > 0.5 mm in-plane. Saving = EUR/assembly if the part were made from the next thinner NP3 plate, removing a slab with the part's fill ratio.

| Part | Qty | Thickness axis, mm | Fill | Min face touches | Max face touches | Screws along axis | Est. saving (plate: EUR/assy) |
|---|---|---|---|---|---|---|---|
| MotorHalterPlatteIsel | 1 | Y 20.0 | 93% | ARC15FN_block | Cam, MotorHalter1 | M5 x 20, M5 x 35 | 12 mm: 2.17; 15 mm: 1.36 |
| MotorHalter1 | 2 | Z 20.0 | 55% | **free** | **free** | – | 12 mm: 2.18; 15 mm: 1.36 |
| MotorHalter2 | 2 | Z 20.0 | 52% | **free** | **free** | – | 12 mm: 2.40; 15 mm: 1.50 |
| ZFuehrungsHalter | 1 | Y 20.0 | 98% | ARC15FN_block, ZXVerbinder | AR15-rail 270 | M4 x 30, M5 x 25, M6 x 40 | 12 mm: 4.10; 15 mm: 2.56 |
| FestLagerHalterIsel | 1 | Z 20.0 | 93% | FestLagerBlock, SensorPlatte | AR15-rail 270, ZFuehrungsHalter | M4 x 10, M4 x 40, M6 x 30 | 12 mm: 1.04; 15 mm: 0.65 |
| LosLagerHalterIsel | 1 | Z 20.0 | 85% | AR15-rail 270, ZFuehrungsHalter | **free** | M4 x 16, M6 x 30 | 12 mm: 1.01; 15 mm: 0.63 |
| FestLagerBlock | 1 | Z 19.5 | 65% | Nema23HalterFuss | FestLagerHalterIsel | M4 x 40 | 12 mm: 0.61; 15 mm: 0.39 |
| SensorPlatteZ | 1 | Z 3.0 | 83% | **free** | FestLagerHalterIsel | M4 x 10 | none thinner |
| Nema23HalterFuss | 2 | Y 8.0 | 89% | **free** | flanschlager_-_216504_0030_01 | – | 5 mm: 0.28; 6 mm: 0.18 |
| ZXVerbinder | 2 | Z 20.0 | 80% | **free** | **free** | – | 12 mm: 1.77; 15 mm: 1.11 |

**Conclusion.**
- Sandwiched (both thickness faces in contact): MotorHalterPlatteIsel, ZFuehrungsHalter, FestLagerHalterIsel, FestLagerBlock. A thinner plate moves an interface or a mating part.
- Free faces in the LC1 path: ZXVerbinder (EUR 1.11-1.77) and the spindle clamps MotorHalter1/2 (EUR 1.36-2.40 per pair). Thinner clamps shorten the grip on the Ø80 spindle and lose stiffness in a part our F4 model does not contain, so such a rule could not be graded.
- Clean candidate off the load path: LosLagerHalterIsel (EUR 0.63-1.01 per assembly); the 8 mm standoffs Nema23HalterFuss save only EUR 0.18-0.28 per pair and set the S4 screw length; SensorPlatteZ is already on the thinnest plate.
