"""Register the native STEP frame to the subassembly.yaml frame: a rigid transform fitted to the IF4 carriage centres.

Computed at run time from the cached facts and the YAML points (cheap), so a --set of a YAML point takes effect.
"""

from itertools import permutations

import numpy as np

from src.cache import CARRIAGE, Z_FRAME

CARRIAGE_TOLERANCE_MM = 0.5
SPINDLE, X_NUT = "Spindle GDZ-23", "GewindeMutter16x5"


def center(box):
    return np.array([(box[i] + box[i + 3]) / 2 for i in range(3)])


def kabsch(native, target):
    """Proper rotation R (det +1) and translation t minimizing |R native + t - target|^2."""
    a, b = native.mean(axis=0), target.mean(axis=0)
    u, _, vt = np.linalg.svd((native - a).T @ (target - b))
    rotation = vt.T @ np.diag([1.0, 1.0, np.sign(np.linalg.det(vt.T @ u.T))]) @ u.T
    return rotation, b - rotation @ a


def register(facts, requirements):
    """Fit native -> YAML on the four X carriages. The carriage rectangle is symmetric, so the assignment with the
    smallest X-nut and spindle-axis residuals is chosen; those two are checks, not fit points (box centres may be biased)."""
    parts = facts["parts"]
    native = np.array([center(p["bounds"]) for p in parts if p["name"] == CARRIAGE and Z_FRAME in p["parents"]])
    interfaces = {i["id"]: i for i in requirements["interfaces_that_must_not_change"]}
    target = np.array([[c[a] for a in "xyz"] for c in interfaces["IF4_x_axis_carriages"]["carriage_centres_mm"]])
    (nut,) = [center(p["bounds"]) for p in parts if p["name"] == X_NUT]
    nut_yaml = np.array([interfaces["IF5_x_axis_ball_nut"]["nut_centre_mm"][a] for a in "xyz"])
    (spindle,) = [center(p["bounds"]) for p in parts if p["name"] == SPINDLE]
    axis_yaml = np.array([requirements["reference_points"]["spindle_axis"][f"{a}_mm"]["value"] for a in "xy"])
    if len(native) != len(target) or len(native) < 3:
        return {"accepted": False, "reason": f"{len(native)} native X carriages for {len(target)} YAML centres"}
    fits = []
    for order in permutations(range(len(target))):
        rotation, translation = kabsch(native, target[list(order)])
        residuals = np.linalg.norm(native @ rotation.T + translation - target[list(order)], axis=1)
        nut_residual = float(np.linalg.norm(rotation @ nut + translation - nut_yaml))
        axis_residual = float(np.linalg.norm((rotation @ spindle + translation)[:2] - axis_yaml))
        fits.append((float(residuals.max()) > CARRIAGE_TOLERANCE_MM, nut_residual + axis_residual, rotation, translation,
                     residuals, nut_residual, axis_residual))
    _, _, rotation, translation, residuals, nut_residual, axis_residual = min(fits, key=lambda f: f[:2])
    return {"accepted": bool(residuals.max() <= CARRIAGE_TOLERANCE_MM), "rotation": rotation.round(12).tolist(),
            "translation_mm": translation.tolist(), "carriage_residuals_mm": residuals.tolist(),
            "x_nut_residual_mm": nut_residual, "spindle_axis_residual_mm": axis_residual}


def to_yaml(registration, point):
    return np.array(registration["rotation"]) @ np.asarray(point, dtype=float) + np.array(registration["translation_mm"])


def yaml_box(registration, boxes):
    """Axis-aligned YAML-frame box around the native boxes (all 8 corners transformed)."""
    corners = np.array([[b[i], b[j], b[k]] for b in boxes for i in (0, 3) for j in (1, 4) for k in (2, 5)])
    moved = corners @ np.array(registration["rotation"]).T + np.array(registration["translation_mm"])
    return moved.min(axis=0).tolist() + moved.max(axis=0).tolist()


def tool_solid(facts):
    """(part index, solid number) of the cutting tool: the spindle solid at the native Z extreme, or None."""
    extreme = facts["native_extremes"]["z"]["max"]
    return (extreme["part"], extreme["solid"]) if facts["parts"][extreme["part"]]["name"] == SPINDLE else None


def tool_report(facts, registration):
    """Spindle nose (lowest non-tool spindle solid) and tool tip in the YAML frame, and the CAD tool stick-out."""
    tool = tool_solid(facts)
    if tool is None or not registration["accepted"]:
        return None
    spindle = facts["parts"][tool[0]]
    tip_box = spindle["solid_bounds"][tool[1] - 1]
    body = [b for k, b in enumerate(spindle["solid_bounds"], 1) if k != tool[1]]
    axis = center(tip_box)[:2]
    nose = to_yaml(registration, [*axis, max(b[5] for b in body)])[2]
    tip = to_yaml(registration, [*axis, tip_box[5]])[2]
    return {"spindle_nose_z": float(nose), "tool_tip_z": float(tip), "stick_out_mm": float(abs(nose - tip))}
