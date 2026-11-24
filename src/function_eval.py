"""Function grader F1-F7: the changed design obeys the load cases and limits of subassembly.yaml."""

from math import pi, sqrt

import numpy as np
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.GProp import GProp_GProps

from src.cache import Z_NUT
from src.geometry import bounds, common_shape, connector_arm_geometry, faces_at_y, outer_hole_section
from src.load_path import center, connector_body_response
from src.config import material_properties
from src.records import calculation, change_proof, measured

TORQUE_PATH = "load_cases.LC2_crash.derivation.motor_torque_Nm"  # the one affected input the graders implement
BOLT_DIAMETER_MM = 6.0  # connector-to-guide-plate screws: STEP label "DIN 912 M6 x 40"


def load_case(requirements, prefix):
    return next(lc for lc in requirements["load_cases"] if lc["id"].startswith(prefix))


def guide_contact_matrix(connector, guide, origin):
    """Integral of [1, x, z] outer [1, x, z] over the coplanar connector/guide-plate contact (old function_geometry)."""
    box = bounds(connector)
    x0, _, z0 = origin
    guide_faces = tuple(faces_at_y(guide, box[4]))
    matrix = np.zeros((3, 3))
    for face in faces_at_y(connector, box[4]):
        for guide_face in guide_faces:
            props = GProp_GProps()
            brepgprop.SurfaceProperties(common_shape(face, guide_face), props)
            area = props.Mass()
            if area <= 0:
                continue
            c, inertia = props.CentreOfMass(), props.MatrixOfInertia()
            x, z = c.X() - x0, c.Z() - z0
            xz = -inertia.Value(1, 3) + area * x * z
            matrix += ((area, area * x, area * z), (area * x, inertia.Value(3, 3) + area * x ** 2, xz),
                       (area * z, xz, inertia.Value(1, 1) + area * z ** 2))
    return matrix


def contact_compliance(originals, cases, guide):
    """max(1, max over occurrences of 1/lambda_min(G_case, G_original)), or None when a contact is missing."""
    inputs, ratios = {}, []
    for occurrence, (before, after) in enumerate(zip(originals, cases), 1):
        origin = center(bounds(before))
        matrices = (guide_contact_matrix(before, guide, origin), guide_contact_matrix(after, guide, origin))
        if min(m[0, 0] for m in matrices) <= 0:
            return None, inputs
        for name, m in zip(("original", "case"), matrices):
            for i, j, term in ((0, 0, "area"), (0, 1, "x"), (0, 2, "z"), (1, 1, "xx"), (1, 2, "xz"), (2, 2, "zz")):
                inputs[f"occurrence_{occurrence}.{name}.{term}"] = measured(float(m[i, j]), f"mm^{2 + (i > 0) + (j > 0)}")
        root = np.linalg.cholesky(matrices[0])
        weakest = float(np.linalg.eigvalsh(np.linalg.solve(root, np.linalg.solve(root, matrices[1]).T).T)[0])
        if weakest <= 0:
            return None, inputs
        ratios.append(1 / weakest)
    return max(1.0, *ratios), inputs


def connector_material(req):
    return material_properties(req, next(p["material"] for p in req["made_parts"]["parts"] if p["part_id"] == "ZXVerbinder"))


LC2_FORMULA = ("yaml_force * drive_scale * motor_torque / yaml_motor_torque; drive_scale = derived_force / "
               "yaml_derived_force (1 within the YAML's 0.5 N rounding); derived_force = 2*pi*yaml_motor_torque*"
               "screw_efficiency/(screw_pitch/1000)")


def lc2_drive(config, substitutions):
    """LC2 crash force: the YAML force_N, scaled by an edit of screw_pitch_mm or screw_efficiency (derived force against
    the YAML's own derived 6786 N) and by the torque ratio of a motor substitution. So editing force_N, pitch or
    efficiency moves the original and every case alike; the original is force_N exactly while the derivation is unedited.

    Returns (force_N, inputs, changed_by): changed_by is the substitution id, or None for the YAML motor.
    """
    lc2 = load_case(config.requirements, "LC2")
    derivation = lc2["derivation"]
    changed = [(s["id"], item) for s in substitutions for item in s["affected_inputs"] if item["path"] == TORQUE_PATH]
    unknown = [item["path"] for s in substitutions for item in s["affected_inputs"] if item["path"] != TORQUE_PATH]
    if unknown or len(changed) > 1:
        raise ValueError(f"Unsupported or conflicting affected inputs: {unknown or [c[0] for c in changed]}")
    sub_id, item = changed[0] if changed else (None, None)
    yaml_torque, eta, pitch = (derivation[k]["value"] for k in ("motor_torque_Nm", "screw_efficiency", "screw_pitch_mm"))
    torque = (item["to"], item["unit"]) if item else (yaml_torque, "Nm")
    derived, reference = 2 * pi * yaml_torque * eta / (pitch / 1000), derivation["force_N"]["value"]
    scale = 1.0 if abs(derived - reference) <= 0.5 else derived / reference
    inputs = {"motor_torque": measured(*torque), "yaml_motor_torque": measured(yaml_torque, "Nm"),
              "screw_efficiency": measured(eta, "1"), "screw_pitch": measured(pitch, "mm"),
              "yaml_force": measured(lc2["force_N"]["value"], "N"), "derived_force": measured(derived, "N"),
              "yaml_derived_force": measured(reference, "N"), "drive_scale": measured(scale, "1")}
    return lc2["force_N"]["value"] * scale * torque[0] / yaml_torque, inputs, sub_id


def f7_torque_limit(config):
    """(largest LC2 force, largest motor torque in Nm) that pass F7: rating / SF_LC2, then T = T_yaml * F / F_orig."""
    original, inputs, _ = lc2_drive(config, ())
    force = config.z_ball_nut["static_axial_rating_N"]["value"] / config.requirements["limits"]["safety_factor_yield_LC2"]["minimum"]
    return force, inputs["yaml_motor_torque"]["value"] * force / original


def connector_function_checks(originals, cases, cache, config):
    """F1-F4: depend only on the ZXVerbinder solids (computed once per design option)."""
    req = config.requirements
    lc1 = load_case(req, "LC1")
    material = connector_material(req)
    yield_mpa, factor1 = material["yield_strength_MPa"]["value"], req["limits"]["safety_factor_yield_LC1"]["minimum"]
    force, allowable = lc1["force_N"]["value"], yield_mpa / factor1
    checks = {}

    # F1-F3: the full LC1 X-drive reaction on one connector bolt (one bolt of four: conservative local screen).
    section = outer_hole_section(cases[0], bounds(cases[0]))
    inputs = {"applied_load": measured(force, "N"), "yield_strength": measured(yield_mpa, "MPa"),
              "minimum_yield_safety_factor": measured(factor1, "1"), "bolt_shank_diameter": measured(BOLT_DIAMETER_MM, "mm")}
    stresses = (None, None, None)
    if section is not None:
        edge, hole, depth, width = section
        inputs.update(clear_end_ligament=measured(edge, "mm"), hole_diameter=measured(hole, "mm"),
                      bearing_depth=measured(depth, "mm"), section_width=measured(width, "mm"))
        stresses = (sqrt(3) * force / (2 * edge * depth) if edge > 0 and depth > 0 else None,
                    force / (BOLT_DIAMETER_MM * depth) if depth > 0 else None,
                    force / ((width - hole) * depth) if width > hole and depth > 0 else None)
    note = "LC1 X drive reaction on one connector bolt; allowable = yield / SF_LC1. Not computable (e.g. a bore breaks out) = FAIL."
    for key, formula, stress in (("F1_connector_tear_out", "sqrt(3) * applied_load / (2 * clear_end_ligament * bearing_depth)", stresses[0]),
                                 ("F2_connector_bearing", "applied_load / (bolt_shank_diameter * bearing_depth)", stresses[1]),
                                 ("F3_connector_net_section", "applied_load / ((section_width - hole_diameter) * bearing_depth)", stresses[2])):
        checks[key] = calculation(formula, inputs, stress, allowable, "MPa", reason=note)

    # F4: tool-tip deflection ratio bound for every LC1 direction.
    contact, inputs = contact_compliance(originals, cases, cache.guide_plate)
    arms = [connector_arm_geometry(shape) for shape in (originals[0], cases[0])]
    modulus = material["elastic_modulus_MPa"]["value"]
    body = None
    if None not in arms:
        (original, original_in), (case, case_in) = (connector_body_response(force, arm, modulus) for arm in arms)
        body = case / original
        inputs.update({f"original_{k}": v for k, v in original_in.items()} | {f"case_{k}": v for k, v in case_in.items()})
        inputs["body_ratio"] = measured(body, "1")
    bounds_by_direction = {}
    for direction in lc1["directions"]:
        terms = (contact, body) if direction.endswith("X") else (contact,)  # the Y load path has no connector body
        bounds_by_direction[direction] = None if None in terms else max(1.0, *terms)
    inputs.update({f"bound_{d}": measured(v, "1") for d, v in bounds_by_direction.items() if v is not None})
    value = None if None in bounds_by_direction.values() else max(bounds_by_direction.values())
    checks["F4_deflection_ratio_bound"] = calculation(
        "bound = max over directions of max(1, body_ratio [X only], max_contacts 1/lambda_min(G_case, G_original)); "
        "G = integral([1,x,z] outer [1,x,z] dA) over the connector/guide-plate contact; body_ratio = case/original "
        "connector-arm compliance", inputs, value, config.deflection_limit, "1",
        reason="Upper bound on the LC1 tool-tip deflection ratio for any linear-elastic model in which unchanged parts and "
               "joints keep their stiffness (closed, sticking, uniform contact). Threshold from the YAML rule text. A "
               "substitution must state why it is outside this model (UNCHANGED reasons of F5).")
    return checks


def function_checks(originals, cases, cache, config, changes, substitutions, connector_checks=None):
    """F1-F7. changes: (id, unchanged_proofs) of every declared change; substitutions: the applied entries."""
    req = config.requirements
    lc1 = load_case(req, "LC1")
    yield_mpa = connector_material(req)["yield_strength_MPa"]["value"]
    factor1, factor2 = req["limits"]["safety_factor_yield_LC1"]["minimum"], req["limits"]["safety_factor_yield_LC2"]["minimum"]
    checks = dict(connector_checks or connector_function_checks(originals, cases, cache, config))
    checks["F5_LC1_assembly_yield"] = calculation(
        "SF = yield_strength / peak_equivalent_stress over the whole assembly", {"applied_load": measured(lc1["force_N"]["value"], "N"),
        "yield_strength": measured(yield_mpa, "MPa")}, None, factor1, "1", operator=">=",
        reason="Whole-assembly peak stress is not modelled (baseline finding). The changed part is graded by F1-F3.",
        proof=change_proof("F5", changes, ["G0", "G3"]))

    original_force = lc2_drive(config, ())[0]
    force, drive_inputs, changed_by = lc2_drive(config, substitutions)
    conditions = []
    if changed_by:
        conditions.append(calculation(
            f"F_new = {LC2_FORMULA} <= F_orig (the same formula with the YAML motor torque)",
            {**drive_inputs, "F_orig": measured(original_force, "N")}, force, original_force, "N",
            reason=f"{changed_by} changes the motor torque; linear statics: every LC2 stress scales with the force."))
    checks["F6_LC2_assembly_yield"] = calculation(
        "SF = yield_strength / peak_equivalent_stress over the whole assembly", {"applied_load": measured(force, "N"),
        "original_load": measured(original_force, "N"), "yield_strength": measured(yield_mpa, "MPa")}, None, factor2, "1",
        operator=">=", reason="LC2 peak stress is not modelled (baseline finding).",
        proof=change_proof("F6", changes, ["G0"], conditions))

    nut, nuts = config.z_ball_nut, cache.parts_named(Z_NUT)
    spans = nuts[0]["spans_sorted_mm"] if len(nuts) == 1 else None
    rating = nut["static_axial_rating_N"]["value"] if spans == nut["envelope_mm"] else None
    nut_inputs = {**drive_inputs, **({"nut_body_diameter": measured(spans[0], "mm"), "nut_body_length": measured(spans[2], "mm")}
                                     if spans else {})}
    source_note = f"Rating: {nut['static_axial_rating_N']['source']} (rules/bought_parts.yaml). {nut['note']}"
    # Always computed: PASS or FAIL on its value, for the original and every option.
    demand = f"axial_demand = {LC2_FORMULA}"
    nut_inputs.update(axial_demand=measured(force, "N"), **({"catalog_static_axial_rating": measured(rating, "N")} if rating else {}))
    checks["F7_z_ball_nut_capacity"] = calculation(
        f"safety_factor = catalog_static_axial_rating / axial_demand >= safety_factor_yield_LC2; {demand}", nut_inputs,
        rating / force if rating else None, factor2, "1", operator=">=",
        reason="The static rating is the onset of permanent deformation of the nut, which LC2 forbids ('A permanent "
               "deformation is not permitted'), so it is treated as the nut's yield: rating / force >= "
               f"safety_factor_yield_LC2. {f'Motor torque from {changed_by} (published datasheet). ' if changed_by else 'YAML motor torque. '}"
               + source_note)
    checks["F7_z_ball_nut_capacity"]["sources"] = list(nut["sources"])
    return checks
