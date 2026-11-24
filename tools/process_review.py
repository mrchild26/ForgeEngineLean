"""Process review (analysis, not a grader): which manufacturing route fits each made part? Writes results/process_review.md.

Routes: A 3-axis from a plate box (today's cost model), B 5-axis one setup, C laser profile + 3-axis finishing, D laser
only + manual tapping, F (material screen) saw from EN AW-6061 bar. Geometry from the made-part BREPs in the cache
(written once from the source STEP). Every time or price not in rates.yaml is an ASSUMPTION listed in the report.
Run: python tools/process_review.py"""

import csv
import itertools
import json
import sys
from math import pi
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface  # noqa: E402
from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeFace  # noqa: E402
from OCC.Core.BRepGProp import brepgprop  # noqa: E402
from OCC.Core.BRepTools import breptools  # noqa: E402
from OCC.Core.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane  # noqa: E402
from OCC.Core.GProp import GProp_GProps  # noqa: E402
from src import cache as cache_module  # noqa: E402
from src.cache import CONNECTOR, GUIDE_PLATE, SOURCE_STEP, STEP_NAME_ALIASES  # noqa: E402
from src.config import ROOT, load_config  # noqa: E402
from src.cost_eval import plate_cost  # noqa: E402
from src.geometry import (area_mm2, bounds, faces, load_assembly_parts, read_brep, setup_count, trim_symmetric_x,  # noqa: E402
                          volume_mm3, write_brep)

TAP_DRILL = {3.3: "M4", 4.2: "M5", 5.0: "M6", 6.8: "M8"}  # ISO 2306 tap drills
HOLE_MIN = 0.3        # ASSUMPTION (new): machine min per drilled or tapped hole on the mill, every route
TAP_MANUAL = 0.5      # ASSUMPTION: labour min per hand-tapped hole (route D)
FINISH_MIN = 1.0      # ASSUMPTION: machine min to finish one tight bore after a laser cut
DEBURR_MIN = 3.0      # ASSUMPTION: labour min per part, every route (reported separately)
NEST = 1.10           # ASSUMPTION: kerf and skeleton allowance on the nested profile area
SAW_MIN = 1.0         # ASSUMPTION: saw min per cut (route F)
LASER_LIMIT, LASER_SENSITIVITY = 12, 20  # ASSUMPTION: production-quality Al thickness; maker maximum 20 mm
SPEEDS = [(3, 2000, 4000), (6, 800, 2000), (10, 400, 1000), (16, 200, 600), (25, 100, 300)]  # mm, mm/min low/high
FLAT_T = [5, 6, 8, 10, 12, 15, 20, 25, 30]  # ASSUMPTION: common flat-bar thicknesses and widths, mm
FLAT_W = [20, 25, 30, 40, 50, 60, 80, 100, 120, 150, 200]


def made_shapes(cache, config):
    """First placed occurrence of each made part, cached as BREP next to facts.json (one STEP import if missing)."""
    folder, specs = cache.directory / "made_parts", config.requirements["made_parts"]["parts"]
    cached = {GUIDE_PLATE: cache.guide_plate, CONNECTOR: cache.connectors[0]}  # already in the cache: not stored twice
    other = [s["part_id"] for s in specs if s["part_id"] not in cached]
    if not all((folder / f"{pid}.brep").is_file() for pid in other):
        placed = load_assembly_parts(SOURCE_STEP)
        folder.mkdir(exist_ok=True)
        for pid in other:
            name = STEP_NAME_ALIASES.get(pid, pid)
            write_brep(next(p.shape for p in placed if p.name == name), folder / f"{pid}.brep")
    return {pid: read_brep(folder / f"{pid}.brep") for pid in other} | cached


def length(shape):
    props = GProp_GProps()
    brepgprop.LinearProperties(shape, props)
    return props.Mass()


def classify(shape, others=()):
    """Thickness axis, 2D-profile test, side features, holes, tapped holes, tight bores, outline and cut data."""
    box = bounds(shape)
    spans = [box[i + 3] - box[i] for i in range(3)]
    k = min(range(3), key=lambda i: spans[i])
    t = spans[k]
    steps, other_surfaces, side_axes, groups, if1 = 0, 0, set(), {}, set()
    for face in faces(shape):
        s = BRepAdaptor_Surface(face)
        if s.GetType() == GeomAbs_Plane:
            n = s.Plane().Axis().Direction().Coord(k + 1)
            if abs(n) > 0.999999 and min(abs(s.Plane().Location().Coord(k + 1) - box[k + j]) for j in (0, 3)) > 1e-4:
                steps += 1  # counterbore floor, pocket floor or step across the thickness
            elif 1e-6 < abs(n) < 0.999999:
                other_surfaces += 1
        elif s.GetType() == GeomAbs_Cylinder:
            c, fb = s.Cylinder(), bounds(face)
            a = max(range(3), key=lambda i: abs(c.Axis().Direction().Coord(i + 1)))
            d, loc = 2 * c.Radius(), [c.Location().Coord(i + 1) for i in range(3)]
            plane = [i for i in range(3) if i != a]
            interior = all(min(loc[i] - box[i], box[i + 3] - loc[i]) > d / 2 + 0.01 for i in plane)
            if abs(d - 80) < 0.05:  # IF1 spindle bore (subassembly.yaml IF1 diameter), open in a clamp half
                if1.add((a, *(round(loc[i], 1) for i in plane)))
            if a != k:
                side_axes.add(a)
            if interior:
                key = (a, *(round(loc[i], 1) for i in plane))
                through = a == k and fb[k + 3] - fb[k] >= t - 1e-3
                entry = groups.setdefault(key, {"axis": a, "d": [], "through_d": [], "blind": False})
                entry["d"].append(d)
                entry["through_d"] += [d] if through else []
                entry["blind"] |= a == k and not through
        else:
            other_surfaces += 1
    for g in groups.values():
        g["tapped"] = any(abs(d - tap) < 0.01 for d in g["d"] for tap in TAP_DRILL)
        g["through"] = min(g["through_d"]) if g["through_d"] else None
        g["tight"] = min(g["d"]) >= 12 and any(o["axis"] == g["axis"] for o in others)  # bearing seat
    sides = [[f for f in faces(shape) if BRepAdaptor_Surface(f).GetType() == GeomAbs_Plane and abs(
        BRepAdaptor_Surface(f).Plane().Axis().Direction().Coord(k + 1)) > 0.999999 and abs(
        BRepAdaptor_Surface(f).Plane().Location().Coord(k + 1) - box[k + j]) < 1e-4] for j in (0, 3)]
    outline = []
    for side in sides:
        wires = [breptools.OuterWire(f) for f in side]
        outline.append((sum(area_mm2(BRepBuilderAPI_MakeFace(w).Face()) for w in wires), sum(length(w) for w in wires)))
    profile_area, perimeter = max(outline)
    blind = any(g["blind"] for g in groups.values())
    is_profile = not (steps or other_surfaces or side_axes or blind)
    return {"axis": k, "t": t, "profile": is_profile, "side": sorted(side_axes), "steps": steps, "groups": groups,
            "holes": sum(min(g["d"]) < 12 for g in groups.values()), "tapped": sum(g["tapped"] for g in groups.values()),
            "tight": sum(g["tight"] for g in groups.values()) + len(if1), "area": profile_area, "perimeter": perimeter,
            "volume": volume_mm3(shape), "spans": sorted(round(s, 6) for s in spans), "setups": setup_count(shape)}


def bearing_axes(cache, shape, made_names):
    """Bought bearings ('lager' in the name) whose box overlaps the part: their axis index (a bore >= 12 mm along it is a
    bearing seat)."""
    box = bounds(shape)
    found = []
    for p in cache.facts["parts"]:
        b = p["bounds"]
        if "lager" in p["name"].lower() and p["name"] not in made_names:
            spans = [b[i + 3] - b[i] for i in range(3)]
            a = min(range(3), key=lambda i: spans[i])  # a flange bearing is flat along its axis
            if all(min(b[i + 3], box[i + 3]) - max(b[i], box[i]) > 0.5 for i in range(3)):
                found.append({"axis": a})
    return found


def hourly(rates, machine):
    return rates["machines"][machine]["machine_rate_eur_h"] + rates["labour_rate_eur_h"]


def routes(geo, material, config, limit=LASER_LIMIT, fast=False):
    """EUR per piece of each feasible route (None = not feasible), excluding deburring."""
    rates, lot = config.rates, config.lot_size
    price = rates["materials"][f"{material} plate"]
    h3, h5, hl = hourly(rates, "milling_3_axis"), hourly(rates, "milling_5_axis"), hourly(rates, "laser_cutting")
    setup = lambda m, n: n * rates["machines"][m]["setup_time_min"] / 60 * hourly(rates, m) / lot  # noqa: E731
    a = plate_cost(geo["spans"], geo["volume"], geo["setups"], material, config)
    stock, rate, chip = a["stock_thickness"], config.cost_model["removal_rate_mm3_min"], price["chip_value_eur_kg"]
    out = {"A": a["total"] + geo["holes"] * HOLE_MIN / 60 * h3, "B": a["material"] - a["scrap_credit"] + setup(
        "milling_5_axis", 1) + (a["chip_volume"] / rate + geo["holes"] * HOLE_MIN) / 60 * h5, "C": None, "D": None}
    if stock > limit:
        return out, a
    speed = next(s[2 if fast else 1] for s in SPEEDS if stock <= s[0])
    cut = [g for g in geo["groups"].values() if g["through"] and g["through"] >= stock]  # ASSUMPTION: laser hole d >= t
    cut_length = geo["perimeter"] + sum(pi * g["through"] for g in cut)
    material_cost = geo["area"] * stock * NEST * price["density_g_cm3"] * 1e-6 * price["price_eur_kg"]
    laser = setup("laser_cutting", 1) + cut_length / speed / 60 * hl
    milled = max(0.0, geo["area"] * stock - geo["volume"] - sum(pi * g["through"] ** 2 / 4 * stock for g in cut))
    mill_holes = sum(min(g["d"]) < 12 and (g not in cut or g["tapped"]) for g in geo["groups"].values())
    families = set(geo["side"]) | ({geo["axis"]} if geo["steps"] or geo["tight"] or milled > 1 or any(
        g not in cut and g["axis"] == geo["axis"] for g in geo["groups"].values()) else set())
    out["C"] = material_cost + laser + setup("milling_3_axis", len(families)) + (
        milled / rate + mill_holes * HOLE_MIN + geo["tight"] * FINISH_MIN) / 60 * h3 - milled * price["density_g_cm3"] * 1e-6 * chip
    if geo["profile"] and not geo["side"] and not geo["tight"] and len(cut) == len(geo["groups"]):
        out["D"] = material_cost + laser + geo["tapped"] * TAP_MANUAL / 60 * rates["labour_rate_eur_h"]
    out["_detail"] = {"stock": stock, "speed": speed, "cut_length": cut_length, "material": material_cost, "laser": laser,
                      "families": len(families), "milled": milled, "mill_holes": mill_holes}
    return out, a


def best(costs):
    """(route, EUR) of the cheapest feasible route; a tie goes to the route with fewer machines (D before C)."""
    return min(((r, v) for r, v in costs.items() if r in "ABCD" and v is not None), key=lambda rv: (round(rv[1], 6), "DCBA".index(rv[0])))


def bar_route(geo, config):
    """Route F: saw an EN AW-6061 flat bar (smallest assumed section covering t x w) to length, then 3-axis as today."""
    rates, rate = config.rates, config.cost_model["removal_rate_mm3_min"]
    t, w, length_mm = geo["spans"]
    tb, wb = min(x for x in FLAT_T if x >= t), min((x for x in FLAT_W if x >= w), default=None)
    if wb is None:
        return None
    bar, h3, hs = rates["materials"]["EN AW-6061 bar"], hourly(rates, "milling_3_axis"), hourly(rates, "sawing")
    blank = tb * wb * length_mm
    chips = blank - geo["volume"]
    cost = (blank * bar["density_g_cm3"] * 1e-6 * bar["price_eur_kg"] + rates["machines"]["sawing"]["setup_time_min"] / 60 * hs
            / config.lot_size + SAW_MIN / 60 * hs + geo["setups"] * rates["machines"]["milling_3_axis"]["setup_time_min"] / 60 * h3
            / config.lot_size + (chips / rate + geo["holes"] * HOLE_MIN) / 60 * h3 - chips * bar["density_g_cm3"] * 1e-6 * bar["chip_value_eur_kg"])
    return {"section": f"{tb} x {wb}", "cost": cost}


def trim_deltas(cache, config, route, limit, fast):
    """Made-part delta per trim value with the ZXVerbinder held on one route (the other parts are unchanged)."""
    seat, qty = config.rule["protected_features"]["bolt_seat_radius_mm"], len(cache.connectors)
    original = classify(cache.connectors[0])
    base, base_a = routes(original, "EN AW-5083", config, limit, fast)
    deltas = {}
    for value in config.rule["parameter"]["values"]:
        geo = classify(trim_symmetric_x(cache.connectors[0], value, seat))
        costs, a = routes(geo, "EN AW-5083", config, limit, fast)
        deltas[value] = (qty * (costs[route] - base[route]), qty * (a["total"] - base_a["total"]))
    return deltas


def winner_check(cache, config, route, limit, fast):
    """Re-select among the graded options (results/options.csv) with the ZXVerbinder on `route`: Function/Fit verdicts do
    not depend on the route; C3 (delta < 0) is re-evaluated. Checks today's model against the CSV first."""
    deltas = trim_deltas(cache, config, route, limit, fast)
    rows = list(csv.DictReader((ROOT / "results" / "options.csv").open(encoding="utf-8")))
    for r in rows:
        assert abs(deltas[int(r["trim_mm"])][1] - float(r["delta_made_eur"])) < 1e-6, r["option_id"]
    ok = [(deltas[int(r["trim_mm"])][0] + float(r["delta_bought_eur"]), int(r["remaining_findings"]), int(r["trim_mm"]), r)
          for r in rows if r["verdict"] == "ACCEPT"]
    total, _, _, row = min(((round(t, 6), f, v, r) for t, f, v, r in ok if t < 0), key=lambda x: x[:3])
    return row["option_id"], total, deltas[int(row["trim_mm"])][0]


def money(v):
    return "–" if v is None else f"{v:.2f}"


SRC = {"trumpf": "https://www.trumpf.com/en_GB/products/machines-systems/2d-laser-cutting-machines/trulaser-3030-fiber-3040-fiber-3060-fiber/",
       "trumpf1030": "https://pdf.directindustry.com/pdf/trumpf-machines-systems/trulaser-1030-fiber/5691-854741.html",
       "durma": "https://www.durmapress.com/laser-cutting-machine-aluminum-parameters-equipment-and-best-practices/",
       "bucher": "https://www.bucher-stahl.de/fileadmin/user_upload/produkte/pdf/aluminium.pdf",
       "mastel": "https://cdn.techpilot.com/public/94697/documents/f0d84aa3-e832-446b-8e0f-69633a1d6f8c/mastel_ll_10_08.pdf",
       "guide": "https://www.clean-invoice.com/feinwerkmechanik/kosten-und-kalkulation-feinwerkmechanik",
       "aalco": "https://www.aalco.co.uk/datasheets/Aalco-Metals-Ltd_Aluminium-Alloy-6061-T6-Extrusions_145.pdf.ashx",
       "matmatch": "https://matmatch.com/materials/alky1736-en-573-3-grade-aw-6061-f",
       "metinvest": "https://metinvestholding.com/en/products/steel-grades/s235jr",
       "bikar": "https://my.bikar.com/en_US/products/304_021-304-021-2"}
# material key: (E MPa, yield MPa, property source, lead, corrosion and stability [judgment])
MATERIALS = {
    "EN AW-5083 plate": (70000, 125, "subassembly.yaml (assumption)", f"others each 0.05% ([G11 source]({SRC['bikar']}))",
                         "very good in a workshop; cast/milled plate is stress-relieved and stays flat"),
    "EN AW-6061 bar": (70000, 240, f"T6 Rp0.2 ≥ 240 MPa, EN 755-2 ([Aalco datasheet]({SRC['aalco']}), as listed; PDF not "
                       f"machine-readable here); E 70000 MPa EN 1999-1-1 3.2.5 ([Matmatch]({SRC['matmatch']}): 69–70 GPa)",
                       "unsourced here (EN 573-3 not read); not in G11's table", "good; T6 bar may move when heavily machined"),
    "S235 steel plate": (210000, 225, f"ReH 235 MPa ≤ 16 mm, 225 MPa 16–40 mm ([Metinvest, EN 10025-2]({SRC['metinvest']})); "
                         "E 210000 MPa EN 1993-1-1 3.2.6", "not specified (no Pb addition); G11 has no steel entry",
                         "rusts with chips and lubricant unless coated")}


def material_section(rows, config, checks, q):
    """Material screen for the four parts with material_source: assumption, gated by G15, F4, F1-F3, G11, G13."""
    rates, h3 = config.rates["materials"], hourly(config.rates, "milling_3_axis")
    free = [r for r in rows if r["spec"]["material_source"] == "assumption"]
    rho0 = rates["EN AW-5083 plate"]["density_g_cm3"]
    trim_mass, f4 = checks["G15_NP5_mass"]["result"]["value"], checks["F4_deflection_ratio_bound"]["result"]["value"]
    stress = max(checks[k]["result"]["value"] for k in checks if k[:2] in ("F1", "F2", "F3"))
    one_mm = next(float(r["f4_bound"]) for r in csv.DictReader((ROOT / "results" / "options.csv").open(encoding="utf-8"))
                  if r["trim_mm"] == "1")
    mass = {m: {r["pid"]: r["qty"] * r["geo"]["volume"] * (rates[m]["density_g_cm3"] - rho0) * 1e-6 for r in free} for m in MATERIALS}
    lines = ["", "## Material selection", "", f"Only {', '.join(r['pid'] for r in free)} have material_source: assumption; the "
             "other six are published EN AW-5083 and stay. Candidates = rates.yaml materials. Notes in the last column are judgment.", "",
             "| Material | EUR/kg | g/cm³ | EUR/dm³ | E, MPa | Yield, MPa | Allowable (÷ 2.0) | Property source | Lead | Corrosion / stability |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for m, (e, y, src, lead, note) in MATERIALS.items():
        p = rates[m]
        lines.append(f"| {m} | {p['price_eur_kg']:.2f} | {p['density_g_cm3']} | {p['price_eur_kg'] * p['density_g_cm3']:.2f} | {e} | {y} | "
                     f"{y / 2:g} | {src} | {lead} | {note} |")
    cost = {r["pid"]: (r["costs"]["A"], bar_route(r["geo"], config), plate_cost(r["geo"]["spans"], r["geo"]["volume"], r["geo"]["setups"],
                       "S235 steel", config)["total"] + r["geo"]["holes"] * HOLE_MIN / 60 * h3) for r in free}
    lines += ["", "| Part | Qty | A, 5083 plate € | F, 6061 flat bar (assumed section) € | S235 plate € | Δ mass 6061 / S235, kg |", "|---|---|---|---|---|---|"]
    for r in free:
        a, f, s = cost[r["pid"]]
        lines.append(f"| {r['pid']} | {r['qty']} | {q(r, a):.2f} | {money(q(r, f['cost']) if f else None)} ({f['section'] if f else 'no section'}) | "
                     f"{q(r, s):.2f} | {mass['EN AW-6061 bar'][r['pid']]:+.4f} / {mass['S235 steel plate'][r['pid']]:+.4f} |")
    subsets = [c for n in range(1, len(free) + 1) for c in itertools.combinations(free, n)]
    gain = lambda c: sum(q(r, cost[r["pid"]][0] - cost[r["pid"]][1]["cost"]) for r in c if cost[r["pid"]][1])  # noqa: E731
    per_volume = {m: rates[m]["price_eur_kg"] * rates[m]["density_g_cm3"] for m in ("EN AW-5083 plate", "EN AW-6061 bar")}
    blank = {r["pid"]: r["stock"] * r["geo"]["spans"][1] * r["geo"]["spans"][2] for r in free}
    material_only = lambda c: sum(q(r, blank[r["pid"]] * 1e-6 * (per_volume["EN AW-5083 plate"] - per_volume["EN AW-6061 bar"])) for r in c)  # noqa: E731
    ok = [c for c in subsets if trim_mass + sum(mass["EN AW-6061 bar"][r["pid"]] for r in c) <= 0 and all(cost[r["pid"]][1] for r in c)]
    top = max(ok, key=material_only) if ok else ()
    all6061 = sum(mass["EN AW-6061 bar"].values())
    lines += ["", "**Gates** (calculated where possible):",
              f"- **G15 (made-part mass must not rise):** S235 adds {sum(mass['S235 steel plate'].values()):+.3f} kg → **S235 is out**. 6061 on "
              f"all four adds {all6061:+.4f} kg; with the winner's trim ({trim_mass:+.4f} kg) the net is {all6061 + trim_mass:+.4f} kg → fails. "
              f"Subsets that pass with the trim: {'; '.join(' + '.join(r['pid'] for r in c) for c in ok) or 'none'}.",
              f"- **F4 (≤ {checks['F4_deflection_ratio_bound']['threshold']['value']}):** each changed part's compliance scales with "
              f"70000/E. 6061 at E 70000 (EN 1999-1-1): bound unchanged {f4:.4f}. At 69000 (Matmatch low value): {f4 * 70000 / 69000:.4f} → "
              f"the 2 mm trim would fail and the 1 mm trim ({one_mm * 70000 / 69000:.4f}) would win. S235 (210000): ≤ {max(1.0, f4 / 3):.4f}.",
              f"- **F1–F3:** the winner's largest connector stress is {stress:.2f} MPa against 120 (6061) and 112.5 (S235, t > 16 mm) → pass.",
              "- **G11 (lead):** the grader's table has a sourced bound for EN AW-5083 only; 6061 needs a sourced EN 573-3 entry first, "
              "otherwise G11 is not computable (FAIL). **G13 (NP3 plate thickness):** does not apply to bar; the flat-bar "
              "sections above are ASSUMPTIONS (the Bucher catalogue lists aluminium flat bar, e.g. EN AW-6060 40 × 20, but its "
              "PDF was not machine-readable here, so the section list is unverified).",
              f"- **Cost:** 6061 is {1 - per_volume['EN AW-6061 bar'] / per_volume['EN AW-5083 plate']:.0%} cheaper per volume "
              f"({per_volume['EN AW-6061 bar']:.2f} vs {per_volume['EN AW-5083 plate']:.2f} EUR/dm³): on the same blanks, cut to size "
              f"like today's plate, all four parts would save {material_only(free):.2f} EUR/assembly. Route F as specified loses "
              f"instead ({gain(free):+.2f} EUR/assembly for all four): the {SAW_MIN:g} min saw cut costs "
              f"{SAW_MIN / 60 * hourly(config.rates, 'sawing'):.2f} EUR per piece, and the assumed sections are wider than the parts.",
              f"- **Best feasible combination** (G15 with the trim; G11 once sourced): {' + '.join(r['pid'] for r in top) or 'none'} on "
              f"cut-to-size 6061 blanks, {material_only(top):.2f} EUR/assembly (route F: {gain(top):+.2f}). Material is the same in all "
              "80 options, so the winner does not change (at E = 70000).",
              "- **Judgment (not graded):** keep 5083 plate for MotorHalterPlatteIsel (carries the Z carriages, needs flatness; 137 "
              "× 130 mm needs a 150 mm wide flat bar) and for the clamps (IF1 bore, roundness after heavy machining); 6061 bar "
              "is a fit for the ZXVerbinder (20 × 50 section, little machining)."]
    return lines


def dfm(rows, q):
    by = {r["pid"]: r for r in rows}
    setups = sum(r["qty"] * r["geo"]["setups"] for r in rows)
    sp, nf = by["SensorPlatteZ"], by["Nema23HalterFuss"]
    return [f"- SensorPlatteZ on laser only (route D): saves {sp['costs']['A'] - sp['costs']['D']:.2f} EUR/assembly vs route A; "
            "no design change if the Ø4 holes may stay laser-cut (no fit).",
            f"- Setups dominate: {setups} setups × 6.00 EUR = {setups * 6:.2f} of the {sum(q(r, r['today']) for r in rows):.2f} EUR "
            "today. Each removed setup saves 6.00 EUR per piece, e.g. the Z-axis end holes of ZFuehrungsHalter or the Y holes "
            "of the clamps: only if the joint can move to the main face.",
            f"- Nema23HalterFuss: the two 50 mm long Ø5 bores along an 8 mm wall force a second setup ({q(nf, nf['costs']['A']):.2f} "
            "EUR per pair). A bent sheet bracket (press brake: setup 15 min, 80 EUR/h) or a bought spacer sleeve could replace it; "
            "not priced: rates.yaml has no aluminium sheet and S235 sheet raises the mass (G15).",
            "- Thinner plate for LosLagerHalterIsel (results/thickness_screen.md): 0.63–1.01 EUR/assembly; needs a 12 or 15 mm "
            "design check of the bearing seat depth.",
            "- 6061 flat bar for the ZXVerbinder (route F, Material selection): needs a sourced lead entry (G11) and keeps the "
            "F4 margin only if E = 70000 MPa holds."]


def main():
    cache, config = cache_module.load(), load_config()
    shapes, specs, rates = made_shapes(cache, config), config.requirements["made_parts"]["parts"], config.rates
    names = {STEP_NAME_ALIASES.get(s["part_id"], s["part_id"]) for s in specs}
    report = json.loads((ROOT / "results" / "best.json").read_text(encoding="utf-8"))
    checks = {k: r for g in ("function", "fit") for k, r in report[g]["checks"].items()}
    rows = []
    for s in specs:
        pid, occ = s["part_id"], cache.occurrences(s["part_id"])
        geo = classify(shapes[pid], bearing_axes(cache, shapes[pid], names))
        assert geo["spans"] == occ[0]["spans_sorted_mm"] and abs(geo["volume"] - occ[0]["volume_mm3"]) < 0.01 and geo["setups"] == occ[0]["setups"], pid
        base, a = routes(geo, s["material"], config)
        scen = {k: best(routes(geo, s["material"], config, *k)[0]) for k in ((LASER_LIMIT, False), (LASER_LIMIT, True), (LASER_SENSITIVITY, False), (LASER_SENSITIVITY, True))}
        rows.append({"pid": pid, "qty": len(occ), "geo": geo, "today": a["total"], "stock": a["stock_thickness"], "costs": base, "best": best(base), "scen": scen, "spec": s,
                     "sens_c": routes(geo, s["material"], config, LASER_SENSITIVITY, True)[0]["C"]})
    q = lambda r, v: None if v is None else r["qty"] * v  # noqa: E731
    lines = ["# Process review: which manufacturing route fits each made part?", "",
             "Analysis, not a grader (`tools/process_review.py`; geometry from the made-part BREPs in `cache/`). Rates from "
             f"rates.yaml (lot {config.lot_size}); 3-axis at the default {config.cost_model['removal_rate_mm3_min']} mm³/min. Routes: "
             "**A** 3-axis from a plate box (today's model); **B** 5-axis, same chips, one setup; **C** laser profile from plate "
             "+ 3-axis for side features, steps, blind/tapped/small holes and tight bores; **D** laser only + hand tapping (2D "
             "profile, no side or tight features). Turning: not applicable (no rotational part). Press brake: not applicable "
             "(no bent sheet part; DFM idea below). All parts are below 300 mm, so no bed size (laser 3000 × 1500 mm) limits a route.", "",
             f"**New assumptions:** {HOLE_MIN} min machine time per drilled or tapped hole on the mill, every route (today's "
             f"model has none); hand tapping {TAP_MANUAL} min/hole; {FINISH_MIN} min to finish a tight bore after the laser; "
             f"nesting allowance {NEST - 1:.0%} on the profile area; laser hole only if d ≥ plate thickness; deburring "
             f"{DEBURR_MIN:g} min labour per part (same in every route, reported separately). Facing 0 mm stays: EN AW-5083 is "
             f"stocked as rolled plate milled on both sides ([Mastel stock list]({SRC['mastel']})); blanks cut to size at the "
             f"plate price ([Bucher catalogue]({SRC['bucher']}): formats 1000 × 2000 to 1500 × 3000 mm and \"Fixzuschnitte\").", "",
             f"**Laser limits:** TruLaser 3030 fiber, aluminium max 20 / 30 / 40 mm by laser option ([TRUMPF]({SRC['trumpf']})); "
             f"3 kW TruLaser 1030 fiber max 15 mm ([datasheet]({SRC['trumpf1030']})). A maximum is not production quality: "
             f"ASSUMPTION {LASER_LIMIT} mm ([equipment guide]({SRC['durma']}): 3–6 kW covers 1–12 mm production), sensitivity "
             f"{LASER_SENSITIVITY} mm. Speeds (nitrogen, same guide, vendor guide values, not maker data): " + "; ".join(
                 f"≤ {t} mm {lo:,}–{hi:,} mm/min" for t, lo, hi in SPEEDS) + "; base = low end, sensitivity = high end. "
             "Laser edges are not accepted for the IF1 Ø80 bore or bearing seats (finishing cut).", "",
             "| Part | Qty | 2D profile | Side features | Tapped holes | Tight bores | A € | B € | C € | D € | Best | Saving vs A € | Limiting reason |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        g, c, (route, cost) = r["geo"], r["costs"], r["best"]
        stock = r["stock"]
        reason = ("2D profile on 3 mm plate: laser only" if route == "D" else
                  f"{stock:g} mm > {LASER_LIMIT} mm laser limit; at {LASER_SENSITIVITY} mm and high speed C = {money(q(r, r['sens_c']))}"
                  if c["C"] is None else f"C keeps {c['_detail']['families']} mill setup(s) for side features/holes") + (
                  "; B: one 5-axis setup costs 12.50 € vs 6.00 € per 3-axis setup" if route != "B" else "")
        lines.append(f"| {r['pid']} | {r['qty']} | {'yes' if g['profile'] else 'no'} | {'XYZ'[g['side'][0]] + ' axis' if g['side'] else '–'} | "
                     f"{g['tapped']} | {g['tight']} | " + " | ".join(money(q(r, c[k])) for k in "ABCD") +
                     f" | {route} {money(q(r, cost))} | {money(q(r, c['A'] - cost))} | {reason} |")
    total = lambda key: sum(q(r, key(r)) for r in rows)  # noqa: E731
    today, route_a, best_total, deburr = total(lambda r: r["today"]), total(lambda r: r["costs"]["A"]), total(lambda r: r["best"][1]), \
        total(lambda r: DEBURR_MIN / 60 * rates["labour_rate_eur_h"])
    scen = {k: total(lambda r: r["scen"][k][1]) for k in rows[0]["scen"]}
    changed = {k: sorted({r["pid"] for r in rows if r["scen"][k][0] != "A"}) for k in scen}
    lines += ["", f"Costs are EUR per assembly (× quantity), without deburring. **Totals:** today's model **{today:.2f}**; route A with "
              f"the new hole time {route_a:.2f}; best route per part **{best_total:.2f}** ({route_a - best_total:.2f} saved); with "
              f"deburring ({deburr:.2f}) **{best_total + deburr:.2f} EUR/assembly** (the realistic made-part cost under these "
              "assumptions). Sensitivities (best-route total, parts off route A): " + "; ".join(
                  f"laser ≤ {lim} mm, {'high' if fast else 'low'} speeds {v:.2f} ({', '.join(changed[(lim, fast)]) or 'none'})"
                  for (lim, fast), v in scen.items() if (lim, fast) != (LASER_LIMIT, False)) + "."]
    zx = next(r for r in rows if r["pid"] == "ZXVerbinder")
    checks_w = [(f"laser ≤ {lim} mm, {'high' if fast else 'low'} speeds", zx["scen"][(lim, fast)][0], winner_check(cache, config, zx["scen"][(lim, fast)][0], lim, fast))
                for lim, fast in [(LASER_LIMIT, False), (LASER_SENSITIVITY, True)]]
    lines += ["", "**Winner check** (ZXVerbinder held on its cheapest route; the other parts do not change between options, "
              "so only its delta moves; re-selection over the 80 graded options in `results/options.csv`, Function/Fit verdicts "
              "unchanged, C3 re-evaluated; today's model reproduces every option's made delta to 1e-6): " + "; ".join(
                  f"{label}: ZXVerbinder on route {route} → winner `{w}`, delta {t:.6f} EUR (made {m:.6f})" for label, route, (w, t, m) in checks_w)
              + ". The hole time is the same before and after the trim, so the winner and its delta equal today's."]
    sp = next(r for r in rows if r["pid"] == "SensorPlatteZ")
    d, g, mat = sp["costs"]["_detail"], sp["geo"], rates["materials"]["EN AW-5083 plate"]
    hl, lab = hourly(rates, "laser_cutting"), rates["labour_rate_eur_h"]
    lines += ["", f"**Hand check, SensorPlatteZ route D:** profile area {g['area']:.1f} mm² × {d['stock']:g} mm × {NEST} × "
              f"{mat['density_g_cm3']}e-6 kg/mm³ × {mat['price_eur_kg']:.2f} €/kg = {d['material']:.4f} €; laser setup "
              f"{rates['machines']['laser_cutting']['setup_time_min']} min × {hl} €/h ÷ 60 ÷ {config.lot_size} = "
              f"{rates['machines']['laser_cutting']['setup_time_min'] * hl / 60 / config.lot_size:.4f} €; cut length outline "
              f"{g['perimeter']:.1f} + holes {d['cut_length'] - g['perimeter']:.1f} = {d['cut_length']:.1f} mm ÷ {d['speed']} mm/min = "
              f"{d['cut_length'] / d['speed']:.4f} min × {hl} €/h ÷ 60 = {d['cut_length'] / d['speed'] * hl / 60:.4f} €; tapping "
              f"{g['tapped']} holes; **total {sp['costs']['D']:.4f} €** vs today {sp['today']:.4f} € (of which 6.0000 € is the 3-axis "
              f"setup) and route A {sp['costs']['A']:.4f} € ({g['holes']} holes × {HOLE_MIN} min × 90 €/h ÷ 60 added)."]
    lines += material_section(rows, config, checks, q)
    lines += ["", f"**Rates context:** rates.yaml's 3-axis 60 + 30 = 90 EUR/h and 5-axis 95 + 30 = 125 EUR/h are task placeholders; "
              f"a German price guide gives CNC milling (3-axis) 70–120 EUR/h and 5-axis 100–160 EUR/h ([clean-invoice]({SRC['guide']})), "
              "so both are in range.", "", "**DFM ideas** (estimates from the formulas above; each needs a design change):"]
    lines += dfm(rows, q)
    (ROOT / "results" / "process_review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
