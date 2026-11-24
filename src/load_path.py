"""Assignment 1a/1b: path of the LC1 cutting load from the tool tip to the X axis, and the parts that limit stiffness.

Analysis output (results/load_path.json), not a grader. Statics with an ideal axial X drive (the X nut takes only the
X force; the X carriages take the rest and the couple), and nominal beam models of the moving plate, the fixed guide
plate and the ZXVerbinder pair. Ported from the old repo (function_model, structural_model, load_path).
"""

import sys
import warnings
from math import sqrt

from src.cache import CARRIAGE, CONNECTOR, Z_FRAME
from src.config import material_properties
from src.geometry import connector_arm_geometry
from src.records import calculation, measured, value_record, write_json

AXES = "xyz"
PLATES = (("moving_plate", "MotorHalterPlatteIsel"), ("fixed_guide_plate", "ZFuehrungsHalter"))


def add(*vectors):
    return tuple(sum(c) for c in zip(*vectors))


def negate(v):
    return tuple(-c for c in v)


def centroid(points):
    return tuple(sum(c) / len(points) for c in zip(*points))


def moment_at(origin, point, force):
    rx, ry, rz = add(point, negate(origin))
    fx, fy, fz = force
    return (ry * fz - rz * fy, rz * fx - rx * fz, rx * fy - ry * fx)


def norm(v):
    return sqrt(sum(c * c for c in v))


def vector(name, v, unit):
    return {f"{name}_{a}": measured(c, unit) for a, c in zip(AXES, v)}


def center(box):
    return tuple((box[i] + box[i + 3]) / 2 for i in range(3))


def tool_tip(requirements):
    """Tool tip (x, y from the YAML tool_tip; z = spindle_nose_z_mm - tool_stick_out_mm) and the derivation record."""
    points = requirements["reference_points"]
    nose, stick_out = points["spindle_nose_z_mm"]["value"], points["tool_stick_out_mm"]["value"]
    z, yaml_z = nose - stick_out, points["tool_tip"]["z_mm"]["value"]
    if abs(z - yaml_z) > 0.01:
        warnings.warn(f"YAML tool_tip.z_mm {yaml_z} differs from spindle_nose_z_mm - tool_stick_out_mm = {z}; using {z}",
                      stacklevel=2)
    record = value_record("tool_tip_z = spindle_nose_z - tool_stick_out", {"spindle_nose_z": measured(nose, "mm"),
                          "tool_stick_out": measured(stick_out, "mm"), "yaml_tool_tip_z": measured(yaml_z, "mm")}, z, "mm")
    return (points["tool_tip"]["x_mm"]["value"], points["tool_tip"]["y_mm"]["value"], z), record


def task_points(requirements):
    """Tool tip, X carriage centre and X nut in the YAML task frame (mm)."""
    interfaces = {item["id"]: item for item in requirements["interfaces_that_must_not_change"]}
    carriages = interfaces["IF4_x_axis_carriages"]["carriage_centres_mm"]
    return {"tool_tip": tool_tip(requirements)[0],
            "x_carriage_center": centroid([tuple(c[a] for a in AXES) for c in carriages]),
            "x_nut": tuple(interfaces["IF5_x_axis_ball_nut"]["nut_centre_mm"][a] for a in AXES)}


def stations(facts, points):
    """Native STEP stations mapped to the task frame relative to the X carriage centre (task = (x, -y, -z) native)."""
    parts = facts["parts"]
    x_guides = [center(p["bounds"]) for p in parts if p["name"] == CARRIAGE and Z_FRAME in p["parents"]]
    z_guides = [center(p["bounds"]) for p in parts if p["name"] == CARRIAGE and Z_FRAME not in p["parents"]]
    root = centroid(x_guides)

    def station(native):
        d = add(native, negate(root))
        return add(points["x_carriage_center"], (d[0], -d[1], -d[2]))

    clamps = [center(p["bounds"]) for p in parts if p["name"] == "MotorHalter1"]
    connectors = [center(p["bounds"]) for p in parts if p["name"] == CONNECTOR]
    return {"z_guides": station(centroid(z_guides)), "tool_side_clamp": station(max(clamps, key=lambda c: c[2])),
            "zx_support": station(centroid(connectors))}


def connector_body_response(force, arm, modulus):
    """Four nominal elastic arms in parallel (two per connector, two connectors): tip displacement and inputs."""
    length, offset, width, depth = arm
    area, inertia = width * depth, width * depth ** 3 / 12
    inputs = {"drive_force": measured(force, "N"), "arm_span": measured(length, "mm"), "eccentricity": measured(offset, "mm"),
              "gross_area": measured(area, "mm^2"), "I_z": measured(inertia, "mm^4"), "E": measured(modulus, "MPa"),
              "parallel_arms": measured(4, "count")}
    return force * length / (4 * modulus) * (1 / area + offset ** 2 / inertia), inputs


def direction_analysis(direction, magnitude, points, st, sections, material, factor, arm):
    sign = 1 if direction[0] == "+" else -1
    force = tuple(sign * magnitude if a == direction[1].lower() else 0.0 for a in AXES)
    tool, nut, root = points["tool_tip"], points["x_nut"], points["x_carriage_center"]
    drive = (-force[0], 0.0, 0.0)
    guides = negate(add(force, drive))
    couple = negate(add(moment_at(root, tool, force), moment_at(root, nut, drive)))
    forces_in = {**vector("tool_force", force, "N"), **vector("x_nut_force", drive, "N")}
    reactions = {"x_nut.force_x": value_record("x_nut_force_x = -tool_force_x (ideal axial X drive)",
                                               vector("tool_force", force, "N"), drive[0], "N")}
    for a, value in zip(AXES, guides):
        reactions[f"x_carriages.force_{a}"] = value_record("x_carriage_force = -(tool_force + x_nut_force)", forces_in, value, "N")
    moment_in = {**forces_in, **vector("tool_tip", tool, "mm"), **vector("x_nut", nut, "mm"), **vector("x_carriage_center", root, "mm")}
    for a, value in zip(AXES, couple):
        reactions[f"x_carriages.couple_{a}"] = value_record(
            "couple = -((tool_tip - x_carriage_center) x tool_force + (x_nut - x_carriage_center) x x_nut_force)",
            moment_in, value, "N mm")
    loads = ((tool, force), (nut, drive), (root, guides))
    equilibrium = {
        "force_residual": calculation("norm(tool_force + x_nut_force + x_carriage_force)",
                                      {**forces_in, **vector("x_carriage_force", guides, "N")},
                                      norm(add(force, drive, guides)), 1e-7, "N"),
        "moment_residual": calculation("norm(sum((point - x_carriage_center) x force) + couple)",
                                       {**moment_in, **vector("couple", couple, "N mm")},
                                       norm(add(*(moment_at(root, p, f) for p, f in loads), couple)), 1e-6, "N mm")}
    modulus, allowable = material["elastic_modulus_MPa"]["value"], material["yield_strength_MPa"]["value"] / factor
    x_direction = direction.endswith("X")
    fixed_root_z = (st["zx_support"] if x_direction else root)[2]
    spans = {"moving_plate": (st["z_guides"][2], st["tool_side_clamp"][2]), "fixed_guide_plate": (fixed_root_z, st["z_guides"][2])}
    parts = {}
    for label, name in PLATES:
        x_width, y_depth = sections[name]
        width, depth = (y_depth, x_width) if x_direction else (x_width, y_depth)  # Y load bends through the thickness
        span, offset = spans[label][1] - spans[label][0], tool[2] - spans[label][0]
        inertia = width * depth ** 3 / 12
        inputs = {"force": measured(magnitude, "N"), "signed_span": measured(span, "mm"), "tip_offset": measured(offset, "mm"),
                  "width": measured(width, "mm"), "bending_depth": measured(depth, "mm"), "E": measured(modulus, "MPa"),
                  "I": measured(inertia, "mm^4")}
        deflection = magnitude * abs(span) * (offset ** 2 - offset * span + span ** 2 / 3) / (modulus * inertia)
        stress = magnitude * max(abs(offset), abs(offset - span)) * depth / (2 * inertia)
        parts[label] = {
            "deflection": value_record("F * abs(span) * (tip_offset^2 - tip_offset*span + span^2/3) / (E*I)", inputs, deflection, "mm"),
            "bending_stress": calculation("F * max(abs(tip_offset), abs(tip_offset - span)) * bending_depth / (2*I)",
                                          {**inputs, "yield_strength": measured(material["yield_strength_MPa"]["value"], "MPa"),
                                           "safety_factor": measured(factor, "1")}, stress, allowable, "MPa")}
    if x_direction and arm is not None:
        deflection, inputs = connector_body_response(magnitude, arm, modulus)
        parts["zxverbinder_pair"] = {"deflection": value_record(
            "F * arm_span / (parallel_arms * E) * (1/gross_area + eccentricity^2/I_z)", inputs, deflection, "mm")}
    ranking = sorted(parts, key=lambda label: -parts[label]["deflection"]["result"]["value"])
    return {"reactions": reactions, "equilibrium": equilibrium, "parts": parts, "stiffness_ranking": ranking}


def analyze(cache, config):
    req = config.requirements
    points = task_points(req)
    st = stations(cache.facts, points)
    sections = {}
    for _, name in PLATES:
        (box,) = [p["bounds"] for p in cache.parts_named(name)]
        sections[name] = (box[3] - box[0], box[4] - box[1])
    specs = {p["part_id"]: p for p in req["made_parts"]["parts"]}
    material = material_properties(req, specs["MotorHalterPlatteIsel"]["material"])
    factor = req["limits"]["safety_factor_yield_LC1"]["minimum"]
    load = next(lc for lc in req["load_cases"] if lc["id"].startswith("LC1"))
    arm = connector_arm_geometry(cache.connectors[0])
    return {"scope": "LC1 cutting load path, original design. Statics with an ideal axial X drive; nominal beam models. "
                     "Analysis output, not a grader.",
            "points_mm": {k: list(v) for k, v in points.items()}, "tool_tip_z": tool_tip(req)[1],
            "stations_mm": {k: list(v) for k, v in st.items()},
            "load_case": {"id": load["id"], "force_N": load["force_N"]["value"]},
            "directions": {d: direction_analysis(d, load["force_N"]["value"], points, st, sections, material, factor, arm)
                           for d in load["directions"]}}


if __name__ == "__main__":
    from src.cache import load
    from src.config import ROOT, load_config
    out = ROOT / "results" / "load_path.json"
    write_json(out, analyze(load(), load_config(*(sys.argv[1:2] or [None]))))
    print(f"wrote {out}")
