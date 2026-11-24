"""Thickness screen (evidence, not a grader): could a made part move to a thinner NP3 plate?

For each made part: the thickness axis (smallest span), what touches each thickness face (bounding-box contact), the
screws along that axis, and the estimated saving on the next thinner approved plates (the removed slab keeps the
part's fill ratio). Costs use the cost model (src/cost_eval.plate_cost). Run: python tools/thickness_screen.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import cache as cache_module  # noqa: E402
from src.cache import STEP_NAME_ALIASES  # noqa: E402
from src.config import ROOT, load_config  # noqa: E402
from src.cost_eval import plate_cost  # noqa: E402

TOUCH_MM, OVERLAP_MM = 0.15, 0.5


def overlap(a0, a1, b0, b1):
    return min(a1, b1) - max(a0, b0)


def face_contacts(part, parts, axis, side):
    """Names of parts whose box touches the part's min/max thickness face and overlaps it in-plane."""
    lo, hi = part["bounds"][:3], part["bounds"][3:]
    plane, others = (lo if side == "min" else hi)[axis], [i for i in range(3) if i != axis]
    found = set()
    for q in parts:
        ql, qh = q["bounds"][:3], q["bounds"][3:]
        if q is not part and abs((qh if side == "min" else ql)[axis] - plane) < TOUCH_MM and all(
                overlap(lo[i], hi[i], ql[i], qh[i]) > OVERLAP_MM for i in others):
            found.add(q["name"].split(" --- ")[0].replace("socket head cap screw_din_", ""))
    return sorted(found)


def screws_along(part, parts, axis):
    lo, hi = part["bounds"][:3], part["bounds"][3:]
    found = set()
    for q in parts:
        if "screw" in q["name"].lower() and all(overlap(lo[i], hi[i], q["bounds"][i], q["bounds"][i + 3]) > 0.3 for i in range(3)):
            spans = [q["bounds"][i + 3] - q["bounds"][i] for i in range(3)]
            if max(range(3), key=lambda i: spans[i]) == axis:
                found.add(q["name"].split("DIN 912 ")[-1].split(" ---")[0])
    return sorted(found)


def saving_bound(base, width, length, thinner):
    """Upper bound of a thinner-plate saving: the removed stock slab L x W x (stock - thinner) bought as material plus
    the whole slab milled away. Equals (t - thinner)/t x material when the part fills its plate thickness."""
    slab = width * length * (base["stock_thickness"] - thinner)
    stock = width * length * base["stock_thickness"]
    milling_per_mm3 = base["milling"] / base["chip_volume"] if base["chip_volume"] > 0 else 0.0
    return slab * (base["material"] / stock + milling_per_mm3)


def thinner_savings(part, quantity, material, config, plates):
    """[(thinner plate, EUR/assembly saving)] for the next two thinner NP3 plates. Uses the cost model's spans
    (spans_sorted_mm, rounded to 1e-6), so a box thickness of 20.0000002 mm still means a 20 mm plate."""
    t, w, length = part["spans_sorted_mm"]
    base = plate_cost([t, w, length], part["volume_mm3"], part["setups"], material, config)
    fill = part["volume_mm3"] / (t * w * length)
    result = []
    for thinner in [p for p in plates if p < t - 1e-6][-2:]:
        removed = fill * w * length * (t - thinner)
        new = plate_cost([thinner, w, length], part["volume_mm3"] - removed, part["setups"], material, config)
        saving = base["total"] - new["total"]
        assert saving <= saving_bound(base, w, length, thinner) + 0.01, (part["name"], thinner, saving)
        result.append((thinner, quantity * saving))
    return result


def main():
    cache, config = cache_module.load(), load_config()
    parts = cache.facts["parts"]
    plates = next(r for r in config.requirements["non_physical_requirements"]["supply"]["rules"]
                  if r["id"] == "NP3_stock_thickness")["plate_thickness_mm"]["value"]
    rows = []
    for spec in config.requirements["made_parts"]["parts"]:
        occ = [p for p in parts if p["name"] == STEP_NAME_ALIASES.get(spec["part_id"], spec["part_id"])]
        part = occ[0]
        spans = [part["bounds"][i + 3] - part["bounds"][i] for i in range(3)]
        axis = min(range(3), key=lambda i: spans[i])  # thickness axis (for the face contacts only)
        t, w, length = part["spans_sorted_mm"]
        fill = part["volume_mm3"] / (t * w * length)
        savings = [f"{thinner:g} mm: {saving:.2f}"
                   for thinner, saving in thinner_savings(part, len(occ), spec["material"], config, plates)]
        faces = [face_contacts(part, parts, axis, side) for side in ("min", "max")]
        free = sum(not f for f in faces)
        rows.append((spec["part_id"], len(occ), f"{'XYZ'[axis]} {t:.1f}", fill, faces, free,
                     screws_along(part, parts, axis), "; ".join(savings) or "none thinner"))
    lines = ["# Thickness screen: could a made part use a thinner plate?", "",
             "Bounding-box screen, not a grader (`tools/thickness_screen.py`, cache facts, cost model at "
             f"{config.cost_model['removal_rate_mm3_min']} mm³/min). Contact = box faces within {TOUCH_MM} mm and "
             f"overlapping > {OVERLAP_MM} mm in-plane. Saving = EUR/assembly if the part were made from the next thinner "
             "NP3 plate, removing a slab with the part's fill ratio.", "",
             "| Part | Qty | Thickness axis, mm | Fill | Min face touches | Max face touches | Screws along axis | Est. saving (plate: EUR/assy) |",
             "|---|---|---|---|---|---|---|---|"]
    for pid, qty, thick, fill, faces, _, screws, savings in rows:
        lines.append(f"| {pid} | {qty} | {thick} | {fill:.0%} | {', '.join(faces[0]) or '**free**'} | "
                     f"{', '.join(faces[1]) or '**free**'} | {', '.join(screws) or '–'} | {savings} |")
    sandwiched = [r[0] for r in rows if r[5] == 0]
    saving = {r[0]: [float(s.split(": ")[1]) for s in r[7].split("; ") if ": " in s] for r in rows}
    span = lambda ids: f"EUR {min(v for i in ids for v in saving[i]):.2f}-{max(v for i in ids for v in saving[i]):.2f}"  # noqa: E731
    lines += ["", "**Conclusion.**",
              f"- Sandwiched (both thickness faces in contact): {', '.join(sandwiched)}. A thinner plate moves an "
              "interface or a mating part.",
              f"- Free faces in the LC1 path: ZXVerbinder ({span(['ZXVerbinder'])}) and the spindle clamps MotorHalter1/2 "
              f"({span(['MotorHalter1', 'MotorHalter2'])} per pair). Thinner clamps shorten the grip on the Ø80 spindle "
              "and lose stiffness in a part our F4 model does not contain, so such a rule could not be graded.",
              f"- Clean candidate off the load path: LosLagerHalterIsel ({span(['LosLagerHalterIsel'])} per assembly); the "
              f"8 mm standoffs Nema23HalterFuss save only {span(['Nema23HalterFuss'])} per pair and set the S4 screw length; "
              "SensorPlatteZ is already on the thinnest plate.", ""]
    out = ROOT / "results" / "thickness_screen.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
