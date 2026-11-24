"""Fit grader G0-G17: the interfaces and the non-physical rules of subassembly.yaml do not change."""

import re

from OCC.Core.BRepCheck import BRepCheck_Analyzer

from src.cache import CARRIAGE, STEP_NAME_ALIASES, Z_FRAME, Z_SCREW
from src.config import material_properties
from src.cost_eval import piece_price
from src.datum import register, tool_solid, yaml_box
from src.geometry import (BOUNDS_TOL_MM, VOLUME_TOL_MM3, area_mm2, bounds, common_shape, faces_at_y, occurrence_offsets,
                          protected_region, protected_volumes, solids, volume_mm3)
from src.records import PASS, calculation, change_proof, measured

METRIC = re.compile(r"\bM\d+(?:[.,]\d+)?\s*x", re.I)
FASTENER = re.compile(r"screw|bolt|fastener", re.I)
# EN 573-3 per-element limit for elements not listed (includes Pb) in the declared alloy, % mass.
ALLOY_LEAD_BOUND = {"EN AW-5083": (0.05, "https://my.bikar.com/en_US/products/304_021-304-021-2"),  # stockist: "Other 0,05"
                    "EN AW-6061": (0.05, "https://my.bikar.com/en_US/products/375_021-375-021-2"),
                    "EN AW-6082": (0.05, "https://my.bikar.com/en_US/products/302_021-302-021-2")}


def envelope(parts):
    boxes = [p["bounds"] for p in parts]
    return [min(b[i] for b in boxes) for i in range(3)] + [max(b[i] for b in boxes) for i in range(3, 6)]


def same_facts(a, b):
    """Same part name, bounds within 1e-5 mm and volume within 0.01 mm^3 (None = part absent)."""
    if a is None or b is None:
        return a is b
    volumes = (a["volume_mm3"], b["volume_mm3"])
    return (a["name"] == b["name"] and all(abs(x - y) <= BOUNDS_TOL_MM for x, y in zip(a["bounds"], b["bounds"]))
            and (volumes == (None, None) or (None not in volumes and abs(volumes[0] - volumes[1]) <= VOLUME_TOL_MM3)))


def placement_changes(original, case, select):
    """Count missing or moved occurrences of the selected parts (bounds differ by more than 1e-5 mm)."""
    before, after = [p for p in original if select(p)], [p for p in case if select(p)]
    moved = sum(any(abs(a - b) > BOUNDS_TOL_MM for a, b in zip(x["bounds"], y["bounds"])) for x, y in zip(before, after))
    return abs(len(before) - len(after)) + moved, {"original_occurrences": measured(len(before), "count"),
                                                   "case_occurrences": measured(len(after), "count")}


def connector_fit_checks(originals, cases, rule):
    """G1-G3 and the ball-nut pad change: depend only on the ZXVerbinder solids (computed once per design option)."""
    checks = {}
    valid = all(BRepCheck_Analyzer(c).IsValid() and len(solids(c)) == 1 for c in cases)
    inputs, mismatch = {"valid_solids": measured(sum(BRepCheck_Analyzer(c).IsValid() for c in cases), "count")}, []
    for i, (case, offset) in enumerate(zip(cases, occurrence_offsets(originals)), 1):
        expected = cases[0].Moved(offset)
        shared = volume_mm3(common_shape(expected, case))
        mismatch.append(max(abs(volume_mm3(expected) - shared), abs(volume_mm3(case) - shared)))
        inputs[f"occurrence_{i}.placed_copy_mismatch"] = measured(mismatch[-1], "mm^3")
    checks["G1_placed_copies"] = calculation(
        "max_i(max(|V(expected_i) - V(shared_i)|, |V(case_i) - V(shared_i)|)); expected_i = case_1 moved by the original "
        "placement of occurrence i", inputs, max(mismatch) if valid else None, VOLUME_TOL_MM3, "mm^3")

    added, core, pad, inputs_added, inputs_core, inputs_pad = [], [], [], {}, {}, {}
    for i, (o, c) in enumerate(zip(originals, cases), 1):
        added.append(abs(volume_mm3(c) - volume_mm3(common_shape(c, o))))
        inputs_added[f"occurrence_{i}.added_volume"] = measured(added[-1], "mm^3")
        a, b, shared = protected_volumes(o, c, protected_region(o, rule["protected_features"]["bolt_seat_radius_mm"]))
        core.append(max(abs(a - shared), abs(b - shared)))
        inputs_core.update({f"occurrence_{i}.original_core": measured(a, "mm^3"), f"occurrence_{i}.case_core": measured(b, "mm^3"),
                            f"occurrence_{i}.shared_core": measured(shared, "mm^3")})
        pads = [list(faces_at_y(s, bounds(s)[1])) for s in (o, c)]
        if all(len(f) == 1 for f in pads):
            pa, pb, ps = area_mm2(pads[0][0]), area_mm2(pads[1][0]), area_mm2(common_shape(pads[0][0], pads[1][0]))
            pad.append(max(abs(pa - ps), abs(pb - ps)))
            inputs_pad[f"occurrence_{i}.pad_area_change"] = measured(pad[-1], "mm^2")
    checks["G2_removal_only"] = calculation("max_i |V(case_i) - V(common(case_i, original_i))|", inputs_added, max(added),
                                            VOLUME_TOL_MM3, "mm^3", reason="Machinable from the original stock: material is only removed.")
    checks["G3_protected_core"] = calculation(
        "max_i max(|core_original - core_shared|, |core_case - core_shared|) inside the box around holes, bolt seats and ball-nut face",
        inputs_core, max(core), VOLUME_TOL_MM3, "mm^3", reason="Protected features of rules/zxverbinder_trim.yaml (IF4/IF5 bolt pattern).")
    return checks, (pad if len(pad) == len(cases) else None, inputs_pad)


def change_confinement(originals, cases, original_parts, case_parts, cache, rule_id, substitutions, expected):
    """G0: the ZXVerbinder change follows rule 1, each substitution matches its declared geometry, nothing else changed."""
    inputs, bad = {}, 0
    for i, (o, c) in enumerate(zip(originals, cases), 1):
        ob, cb = bounds(o), bounds(c)
        left, right = cb[0] - ob[0], ob[3] - cb[3]
        drift = max(abs(cb[k] - ob[k]) for k in (1, 2, 4, 5))
        inputs.update({f"occurrence_{i}.left_inset": measured(left, "mm"), f"occurrence_{i}.right_inset": measured(right, "mm"),
                       f"occurrence_{i}.yz_drift": measured(drift, "mm")})
        bad += not (abs(left - right) <= BOUNDS_TOL_MM and drift <= BOUNDS_TOL_MM and min(left, right) >= -BOUNDS_TOL_MM)
    before, after = {p["index"]: p for p in original_parts}, {p["index"]: p for p in case_parts}
    declared = {rule_id: [before[i]["name"] for i in cache.facts["connector_indices"]]}
    indices = set(cache.facts["connector_indices"])
    for sub in substitutions:
        parts = expected[sub["id"]]
        indices |= parts.keys()
        declared[sub["id"]] = sorted({before[i]["name"] for i in parts})
        occurrences = sum(p["name"] == sub["part"] for p in original_parts)
        mismatch = sum(not same_facts(facts, after.get(i)) for i, facts in parts.items())
        inputs.update({f"{sub['id']}.declared_parts": measured(len(parts), "count"),
                       f"{sub['id']}.quantity_mismatch": measured(abs(occurrences - sub["quantity"]), "count"),
                       f"{sub['id']}.geometry_mismatch": measured(mismatch, "count")})
        bad += mismatch + abs(occurrences - sub["quantity"])
        if sub["geometry"]["type"] == "motor_envelope":  # the longer shaft must stay clear of the ball-screw journal
            tip = cache.facts["z_motor"]["flange_face_z"] + sub["geometry"]["shaft_length_mm"]
            (journal,) = [p["bounds"][2] for p in original_parts if p["name"] == Z_SCREW]
            inputs[f"{sub['id']}.shaft_tip_to_screw_journal_gap"] = measured(journal - tip, "mm")
            bad += journal - tip < 0
    undeclared = sorted(i for i in before.keys() | after.keys() if i not in indices and not same_facts(before.get(i), after.get(i)))
    inputs["undeclared_changed_parts"] = measured(len(undeclared), "count")
    record = calculation(
        "count(ZXVerbinder occurrences with |left_inset - right_inset| > 1e-5, yz_drift > 1e-5 or inset < 0) + per "
        "substitution (geometry mismatch + quantity mismatch + mate clash) + undeclared_changed_parts", inputs,
        bad + len(undeclared), 0, "count",
        reason="Basis of every UNCHANGED proof: only the declared parts differ from the original, each as declared.")
    record["declared_changes"] = declared
    record["undeclared_changed_parts"] = [(before.get(i) or after.get(i))["name"] for i in undeclared]
    return record


def fit_checks(originals, cases, original_parts, case_parts, cache, config, changes, substitutions, expected,
               connector_checks=None):
    """G0-G17. changes: (id, unchanged_proofs) of every declared change; expected: substitution id -> {index: facts}."""
    req, rule = config.requirements, config.rule
    specs = req["made_parts"]["parts"]
    made = {STEP_NAME_ALIASES.get(p["part_id"], p["part_id"]): p for p in specs}
    before, after = {p["index"]: p for p in original_parts}, {p["index"]: p for p in case_parts}
    connector, (pad, inputs_pad) = connector_checks or connector_fit_checks(originals, cases, rule)
    checks = {"G0_change_confined_to_rule": change_confinement(originals, cases, original_parts, case_parts, cache,
                                                               rule["rule_id"], substitutions, expected), **connector}

    bores = [p["z_bore_max_mm"] for p in original_parts if p["name"] in ("MotorHalter1", "MotorHalter2")]
    interfaces = {item["id"]: item for item in req["interfaces_that_must_not_change"]}
    diameter = interfaces["IF1_spindle_clamp"]["diameter_mm"]["value"]
    checks["G4_IF1_clamp_bore"] = calculation(
        "max |clamp_bore - required_diameter| over the clamp halves", {"required_diameter": measured(diameter, "mm"),
        **{f"bore_{i}": measured(b, "mm") for i, b in enumerate(bores, 1) if b is not None}},
        max(abs(b - diameter) for b in bores) if bores and None not in bores else None, BOUNDS_TOL_MM, "mm")
    for key, select, formula in (
            ("G5_IF2_spindle_axis", lambda p: p["name"] == "Spindle GDZ-23", "count of moved or missing spindle occurrences"),
            ("G7_IF4_x_carriages", lambda p: p["name"] == CARRIAGE and Z_FRAME in p["parents"], "count of moved or missing X carriages")):
        value, inputs = placement_changes(original_parts, case_parts, select)
        checks[key] = calculation(formula, inputs, value, 0, "count")
    nut_moved, inputs = placement_changes(original_parts, case_parts, lambda p: p["name"] in ("GewindeMutter16x5", "GewindeSpindelMutter"))
    checks["G8_IF5_x_ball_nut"] = calculation(
        "connector ball-nut pad: max_i max(|A_original - A_shared|, |A_case - A_shared|), if the X nut parts did not move",
        {**inputs, "nut_parts_moved": measured(nut_moved, "count"), **inputs_pad},
        max(pad) if nut_moved == 0 and pad is not None else None, 0.01, "mm^2")

    moving = cache.facts["z_moving_set"]
    gaps = [max(moving["bounds"][0] - cb[3], cb[0] - moving["bounds"][3], moving["bounds"][1] - cb[4], cb[1] - moving["bounds"][4])
            for cb in (bounds(c) for c in cases)]
    members = [after[i] for i in moving["indices"] if i in after]
    case_moving = envelope(members) if members else None
    growth = max(0.0, *(moving["bounds"][i] - case_moving[i] for i in range(3)),
                 *(case_moving[i] - moving["bounds"][i] for i in range(3, 6))) if case_moving else None
    travel = interfaces["IF3_z_travel"]["travel_mm"]["value"]
    coverage = cache.facts["rail_coverage"]["coverage_mm"]
    conditions = [
        calculation("min over the ZXVerbinder solids of the X/Y gap to the Z-moving-set box > 0",
                    {f"occurrence_{i}.xy_gap": measured(g, "mm") for i, g in enumerate(gaps, 1)}, min(gaps), 0, "mm", operator=">"),
        calculation("growth of the Z-moving-set box (case vs original) over native axes",
                    {"z_moving_parts": measured(len(members), "count")}, growth, BOUNDS_TOL_MM, "mm")]
    # The original travel (old repo's static sweep) is carried to the case only while the proof conditions hold.
    sweep = config.z_travel
    proof = change_proof("G6", changes, ["G0"], conditions)
    carried = sweep["travel_mm"] if proof and all(c["status"] == PASS for c in conditions) else None
    checks["G6_IF3_z_travel"] = calculation(
        "travel = original Z travel carried to the case (static collision sweep: up + down) >= IF3 travel_mm",
        {"original_travel_up": measured(sweep["up_mm"], "mm"), "original_travel_down": measured(sweep["down_mm"], "mm"),
         "original_travel": measured(sweep["travel_mm"], "mm"), "rail_coverage": measured(coverage, "mm"),
         "z_moving_parts": measured(len(moving["indices"]), "count")}, carried, travel, "mm", operator=">=",
        reason=f"Carried from the original, measured once by {sweep['source']} ({sweep['source_written']}); not recomputed "
               "here. Carried only while the proof conditions hold, otherwise not demonstrable (FAIL).",
        proof=proof if carried is not None else None)

    original_box, case_box = envelope(original_parts), envelope(case_parts)
    registration = register(cache.facts, req)
    if registration["accepted"]:
        tool = tool_solid(cache.facts)
        box = yaml_box(registration, [b for p in case_parts for k, b in enumerate(p["solid_bounds"] or [p["bounds"]], 1)
                                      if (p["index"], k) != tool])
        lo, hi = ([req["envelope"][key][a] for a in "xyz"] for key in ("min_mm", "max_mm"))
        margins = {**{f"margin_min_{a}": box[i] - lo[i] for i, a in enumerate("xyz")},
                   **{f"margin_max_{a}": hi[i] - box[i + 3] for i, a in enumerate("xyz")}}
        inputs = {**{k: measured(v, "mm") for k, v in margins.items()},
                  **{f"case_{k}_{a}": measured(box[i + 3 * (k == 'max')], "mm") for k in ("min", "max") for i, a in enumerate("xyz")},
                  **{f"translation_{a}": measured(v, "mm") for a, v in zip("xyz", registration["translation_mm"])},
                  "max_carriage_residual": measured(max(registration["carriage_residuals_mm"]), "mm")}
        checks["G9_envelope"] = calculation(
            "min margin = min over axes of (case_min - envelope_min, envelope_max - case_max); case box in the YAML frame "
            "(native -> YAML rigid transform fitted to the IF4 carriage centres), tool solid excluded", inputs,
            min(margins.values()), 0, "mm", operator=">=",
            reason="The envelope starts at the spindle nose (z 98); the tool is below it by definition, so the tool solid "
                   f"is excluded. Rotation {registration['rotation']}.")
    else:
        growth = max(0.0, *(original_box[i] - case_box[i] for i in range(3)), *(case_box[i] - original_box[i] for i in range(3, 6)))
        checks["G9_envelope"] = calculation(
            "growth = max(0, original_min - case_min, case_max - original_max) over native axes",
            {"case_native_z_span": measured(case_box[5] - case_box[2], "mm")}, growth, BOUNDS_TOL_MM, "mm",
            reason=f"Registration not accepted ({registration.get('reason', 'carriage residual > 0.5 mm')}): relative check.",
            proof=change_proof("G9", changes, ["G0"]) if growth <= BOUNDS_TOL_MM else None)

    inputs, engaged, through, counts = {}, [], False, {}
    for joint in cache.facts["threaded_joints"]:
        counts[joint["joint"]] = n = counts.get(joint["joint"], 0) + 1
        part, axis, sign = after.get(joint["index"]), joint["axis"], joint["direction"]
        tip = (part["bounds"][axis + 3] if sign > 0 else part["bounds"][axis]) if part else joint["head_seat"]
        length, to_thread = (tip - joint["head_seat"]) * sign, (joint["thread_near"] - joint["head_seat"]) * sign
        depth = (joint["thread_far"] - joint["thread_near"]) * sign
        engaged.append(min(max(length - to_thread, 0.0), depth) / joint["nominal_d"])
        through |= length - to_thread > depth
        key = f"{joint['joint']}_{n}"
        inputs.update({f"{key}.length": measured(length, "mm"), f"{key}.head_seat_to_thread": measured(to_thread, "mm"),
                       f"{key}.thread_depth": measured(depth, "mm"), f"{key}.nominal_diameter": measured(joint["nominal_d"], "mm"),
                       f"{key}.engagement": measured(engaged[-1] * joint["nominal_d"], "mm")})
    checks["G10_thread_engagement"] = calculation(  # always computed: PASS or FAIL on its value
        "engagement_d = min over the screws of each threaded joint of clip(length - head_seat_to_thread, 0, thread_depth) "
        "/ nominal_diameter; length = |tip - head_seat| along the screw axis; a tip beyond the thread's far end is not "
        "allowed (FAIL)", inputs, min(engaged) if engaged and not through else None, config.thread_engagement_ratio, "d",
        operator=">=", reason=f"Joints: {', '.join(f'{k} ({v} screws)' for k, v in counts.items())} into aluminium "
        "threads; the other thread joints are not evaluated (README notes). The original fails too: the M8 x 80 end "
        "12.0 mm and the M5 x 50 end 5.0 mm short of their threads (baseline finding).")

    materials = sorted({p["material"] for p in specs})
    limits = [ALLOY_LEAD_BOUND[m][0] if m in ALLOY_LEAD_BOUND else None for m in materials]
    unsourced = [m for m, v in zip(materials, limits) if v is None]
    checks["G11_NP1_lead"] = calculation(
        "max over made-part materials of the specification lead bound", {f"lead_bound.{m}": measured(v, "% mass")
        for m, v in zip(materials, limits) if v is not None}, None if None in limits else max(limits), config.lead_limit_percent, "% mass",
        reason="EN 573-3 'other' (each) bound, which includes Pb when no Pb limit is listed (stockist data sheet)."
               + "".join(f" No sourced lead bound for {m}." for m in unsourced))
    checks["G11_NP1_lead"]["sources"] = [ALLOY_LEAD_BOUND[m][1] for m in materials if m in ALLOY_LEAD_BOUND]

    labels = [p["name"] for p in case_parts if FASTENER.search(p["name"])]
    metric = sum(METRIC.search(name) is not None for name in labels)
    checks["G12_NP2_metric_threads"] = calculation(
        "fastener labels without an ISO metric designation (M + diameter)", {"fastener_labels": measured(len(labels), "count"),
        "metric_labels": measured(metric, "count")}, len(labels) - metric, 0, "count",
        reason="Thread forms are not in the CAD export; all exported fastener labels are metric.",
        proof=change_proof("G12", changes, ["G0", "G3"]))

    plates = req["non_physical_requirements"]["supply"]["rules"]
    choices = next(r["plate_thickness_mm"]["value"] for r in plates if r["id"] == "NP3_stock_thickness")
    thick = [(p["name"], p["spans_sorted_mm"][0]) for p in case_parts if p["name"] in made]
    checks["G13_NP3_stock"] = calculation(
        "count of made-part occurrences without an approved plate thickness >= part thickness",
        {f"{n}.{i}.thickness": measured(t, "mm") for i, (n, t) in enumerate(thick, 1)}, sum(not any(c >= t for c in choices) for _, t in thick), 0, "count")

    transport = {r["id"]: r for r in req["non_physical_requirements"]["transport"]["rules"]}
    padding, limits_mm = transport["NP4_parcel_size"]["padding_mm"]["value"], transport["NP4_parcel_size"]["parcel_limit_mm"]["value"]
    spans = sorted(case_box[i + 3] - case_box[i] + 2 * padding for i in range(3))
    checks["G14_NP4_parcel"] = calculation(
        "max(sorted(native_spans + 2 * padding) - sorted(parcel_limits))", {**{f"padded_span_{i}": measured(s, "mm") for i, s in enumerate(spans, 1)},
        **{f"limit_{i}": measured(v, "mm") for i, v in enumerate(sorted(limits_mm), 1)}}, max(s - v for s, v in zip(spans, sorted(limits_mm))), 0, "mm")

    density = {p["part_id"]: material_properties(req, p["material"])["density_g_cm3"]["value"] for p in specs}
    mass = [sum(p["volume_mm3"] * density[made[p["name"]]["part_id"]] * 1e-6 for p in parts if p["name"] in made)
            for parts in (original_parts, case_parts)]
    checks["G15_NP5_mass"] = calculation(
        "case_mass - original_mass; mass = sum(volume * density * 1e-6) over made parts",
        {"original_mass": measured(mass[0], "kg"), "case_mass": measured(mass[1], "kg")}, mass[1] - mass[0], 0, "kg")

    counts = [sum(abs(sum(p["name"] == n for p in parts) - spec["quantity"]) for n, spec in made.items()) for parts in (original_parts, case_parts)]
    checks["G16_quantities"] = calculation("sum over made parts of |count - quantity| (original + case)",
                                           {"original_deviation": measured(counts[0], "count"), "case_deviation": measured(counts[1], "count")},
                                           sum(counts), 0, "count")

    changed = {i for i in before.keys() | after.keys() if (before.get(i) or after.get(i))["name"] not in made
               and not same_facts(before.get(i), after.get(i))}
    documented, inputs = set(), {"changed_bought_parts": measured(len(changed), "count")}
    for sub in substitutions:
        urls = [sub[side]["url"] for side in ("price_from", "price_to") if sub[side].get("url")]
        inputs.update({f"{sub['id']}.price_from": measured(piece_price(sub["price_from"]), f"{sub['currency']}/piece"),
                       f"{sub['id']}.price_to": measured(piece_price(sub["price_to"]), f"{sub['currency']}/piece"),
                       f"{sub['id']}.prices_with_source_url": measured(len(urls), "count")})
        if sub["reason"].strip() and len(urls) == 2:
            documented |= expected[sub["id"]].keys()
    checks["G17_bought_parts"] = calculation(
        "count of changed bought-part occurrences without a declared substitution that gives a reason and both prices, "
        "each with a source URL", inputs, len(changed - documented), 0, "count",
        reason="subassembly.yaml bought_parts rule: a changed bought part needs its reason, price and price source.")
    checks["G17_bought_parts"]["sources"] = [sub[side]["url"] for sub in substitutions for side in ("price_from", "price_to")
                                             if sub[side].get("url")]
    return checks
