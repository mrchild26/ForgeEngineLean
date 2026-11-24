"""Import the 67 MB source STEP once; cache raw measurements (facts.json) and the solids the booleans need (BREP).

The cache key is the SHA-256 of the source STEP plus CACHE_VERSION. Facts are raw measurements of the original
assembly only, so editing subassembly.yaml, rates.yaml or the rules never requires a rebuild.
"""

import hashlib
import json
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp

from OCC.Core.BRep import BRep_Builder
from OCC.Core.TopoDS import TopoDS_Compound

from src.config import ROOT
from src.geometry import (bounds, cylinder_faces, cylinders, load_assembly_parts, plane_faces, read_brep, same_solid,
                          setup_count, solids, volume_mm3, write_brep)

CACHE_VERSION = 4  # v2: connector pair as one compound; v3: Z motor, head seats; v4: threaded joints (M8 clamp, M5 motor)
CACHE_ROOT = ROOT / "cache"
SOURCE_STEP = ROOT / "cad" / "Z Achse Komplett Isel.STEP"
CONNECTOR, GUIDE_PLATE, CLAMP_PLATE = "ZXVerbinder", "ZFuehrungsHalter", "MotorHalterPlatteIsel"
CARRIAGE, RAIL, Z_FRAME, Z_NUT = "ARC15FN_block", "AR15-rail 270", "Z-Isel-Spindel", "GewindeMutterIsel"
Z_MOTOR, Z_SCREW, MOTOR_GROUP = "Nema 23 76x56", "kugelgewindespindeln-211122_20352", "Nema23mitHalter"
STEP_NAME_ALIASES = {"SensorPlatteZ": "SensorPlatte"}  # subassembly.yaml part_id -> name in the STEP file


def source_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 23), b""):
            digest.update(chunk)
    return digest.hexdigest()


def part_facts(index, part):
    box = bounds(part.shape)
    parts_solids = solids(part.shape)
    z_bores = [2 * c.Radius() for c in cylinders(part.shape) if abs(c.Axis().Direction().Z()) > 0.999999]
    return {"index": index, "name": part.name, "parents": list(part.parents), "bounds": list(box),
            "solid_bounds": [list(bounds(s)) for s in parts_solids],
            "volume_mm3": volume_mm3(part.shape) if parts_solids else None,
            "spans_sorted_mm": sorted(round(box[i + 3] - box[i], 6) for i in range(3)),
            "setups": setup_count(part.shape), "z_bore_max_mm": max(z_bores) if z_bores else None}


def rail_coverage(parts):
    """Z rails on the Z frame and the four Z carriages outside it: common rail span and carriage span."""
    rails = [p["bounds"] for p in parts if p["name"] == RAIL and Z_FRAME in p["parents"]]
    blocks = [p["bounds"] for p in parts if p["name"] == CARRIAGE and Z_FRAME not in p["parents"]]
    if len(rails) != 2 or len(blocks) != 4:
        return None
    rail_min, rail_max = max(b[2] for b in rails), min(b[5] for b in rails)
    block_min, block_max = min(b[2] for b in blocks), max(b[5] for b in blocks)
    return {"rail_zmin": rail_min, "rail_zmax": rail_max, "carriage_zmin": block_min, "carriage_zmax": block_max,
            "coverage_mm": max(0.0, rail_max - rail_min - (block_max - block_min))}


def rear_clamp_m8(placed):
    """Exported M8 x 80 screws coaxial with the four 6.8 mm Y bores of the carriage plate (old fit_evidence)."""
    plates = [p for p in placed if p.name == CLAMP_PLATE]
    if len(plates) != 1:
        return []
    plate_box = bounds(plates[0].shape)
    axes = {(round(c.Location().X(), 5), round(c.Location().Z(), 5)) for c in cylinders(plates[0].shape)
            if abs(c.Axis().Direction().Y()) > 0.999999 and abs(c.Radius() * 2 - 6.8) < 1e-5}
    found = []
    for index, part in enumerate(placed):
        if re.search(r"\bM8\s*x\s*80\b", part.name, re.I):
            box = bounds(part.shape)
            x, z = (box[0] + box[3]) / 2, (box[2] + box[5]) / 2
            if any(abs(ax - x) < 0.01 and abs(az - z) < 0.01 for ax, az in axes) and box[1] > plate_box[4]:
                # Head seat: the underside of the head, the inner Y face as wide as the head (the head is at max Y).
                seats = [y for y, fb in plane_faces(part.shape, 1)
                         if box[1] + 0.5 < y < box[4] - 0.5 and fb[3] - fb[0] >= 0.9 * (box[3] - box[0])]
                found.append({"index": index, "axis_x": x, "axis_z": z, "screw_ymin": box[1], "screw_ymax": box[4],
                              "head_seat_y": max(seats) if seats else None, "head_diameter_mm": box[3] - box[0],
                              "plate_ymin": plate_box[1], "plate_ymax": plate_box[4], "gap_to_plate_mm": box[1] - plate_box[4]})
    return sorted(found, key=lambda s: (s["axis_x"], s["axis_z"])) if len(found) == len(axes) == 4 else []


def motor_m5(placed):
    """The Z-motor M5 screws (head at -Z) and the coaxial 4.2 mm tap-drill holes above their tips."""
    screws = [(i, p) for i, p in enumerate(placed) if re.search(r"\bM5\s*x\s*50\b", p.name) and MOTOR_GROUP in p.parents]
    boxes = {i: bounds(p.shape) for i, p in screws}
    holes = set()  # (part name, axis x, axis y, z0, z1) of every 4.2 mm Z bore (split faces merged) above a screw tip
    for part in placed:
        box = bounds(part.shape)
        if any(box[2] >= b[5] - 1e-6 and box[0] <= b[0] and b[3] <= box[3] and box[1] <= b[1] and b[4] <= box[4]
               for b in boxes.values()):
            holes |= {(part.name, round(c.Location().X(), 6), round(c.Location().Y(), 6), round(fb[2], 6), round(fb[5], 6))
                      for c, fb in cylinder_faces(part.shape)
                      if abs(c.Axis().Direction().Z()) > 0.999999 and abs(2 * c.Radius() - 4.2) < 1e-3}
    found = []
    for index, screw in screws:
        b = boxes[index]
        x, y = (b[0] + b[3]) / 2, (b[1] + b[4]) / 2
        seats = [z for z, fb in plane_faces(screw.shape, 2) if b[2] + 0.5 < z < b[5] - 0.5 and fb[3] - fb[0] >= 0.9 * (b[3] - b[0])]
        thread = [h for h in holes if abs(h[1] - x) < 0.05 and abs(h[2] - y) < 0.05 and h[3] >= b[5] - 1e-6]
        if seats and len(thread) == 1:
            found.append({"index": index, "axis_x": x, "axis_y": y, "head_seat_z": min(seats), "tip_z": b[5],
                          "thread_part": thread[0][0], "thread_z0": thread[0][3], "thread_z1": thread[0][4]})
    return sorted(found, key=lambda s: (s["axis_x"], s["axis_y"])) if len(found) == len(screws) == 4 else []


def threaded_joints(placed, clamp, motor):
    """Screw joints into aluminium threads, normalized: axis (native 0/1/2), direction head -> tip, head seat, thread."""
    diameter = lambda index: float(re.search(r"\bM(\d+)", placed[index].name).group(1))  # noqa: E731
    return ([{"joint": "rear_clamp_m8", "index": s["index"], "axis": 1, "direction": -1, "point": [s["axis_x"], s["axis_z"]],
              "nominal_d": diameter(s["index"]), "head_seat": s["head_seat_y"], "head_diameter": s["head_diameter_mm"],
              "thread_part": CLAMP_PLATE, "thread_near": s["plate_ymax"], "thread_far": s["plate_ymin"]} for s in clamp]
            + [{"joint": "motor_m5", "index": s["index"], "axis": 2, "direction": 1, "point": [s["axis_x"], s["axis_y"]],
                "nominal_d": diameter(s["index"]), "head_seat": s["head_seat_z"],
                "head_diameter": bounds(placed[s["index"]].shape)[3] - bounds(placed[s["index"]].shape)[0],
                "thread_part": s["thread_part"], "thread_near": s["thread_z0"], "thread_far": s["thread_z1"]} for s in motor])


def z_motor(placed):
    """Flange face, shaft axis and length of the Z motor: anchors for a motor substitution."""
    motors = [(i, p) for i, p in enumerate(placed) if p.name == Z_MOTOR]
    if len(motors) != 1:
        return None
    index, motor = motors[0]
    box = bounds(motor.shape)
    # Shaft: the largest Z cylinder that reaches the motor's top (the shaft tip, within its chamfer).
    shafts = [c for c, fb in cylinder_faces(motor.shape) if abs(c.Axis().Direction().Z()) > 0.999999 and fb[5] > box[5] - 1]
    # Flange face: the highest Z face as wide as the square body (the boss and shaft are narrower).
    flange = [z for z, fb in plane_faces(motor.shape, 2) if fb[3] - fb[0] >= 0.9 * (box[3] - box[0])]
    if not shafts or not flange:
        return None
    shaft = max(shafts, key=lambda c: c.Radius())
    return {"index": index, "axis_x": shaft.Location().X(), "axis_y": shaft.Location().Y(), "shaft_diameter_mm": 2 * shaft.Radius(),
            "shaft_tip_z": box[5], "flange_face_z": max(flange), "rear_z": box[2], "body_width_x_mm": box[3] - box[0]}


def z_moving_set(parts):
    """The subassembly owning the four Z carriages moves in Z; return its part indices and union box."""
    carriages = [p for p in parts if p["name"] == CARRIAGE and Z_FRAME not in p["parents"]]
    owners = {p["parents"][-1] for p in carriages if p["parents"]}
    if len(carriages) != 4 or len(owners) != 1:
        return None
    owner = owners.pop()
    members = [p for p in parts if owner in p["parents"]]
    box = [min(p["bounds"][i] for p in members) for i in range(3)] + [max(p["bounds"][i] for p in members) for i in range(3, 6)]
    return {"owner": owner, "indices": [p["index"] for p in members], "bounds": box}


def native_extremes(parts):
    """Per axis, the solid (or solid-less part box) that sets the native min and max."""
    items = [(p["index"], k, b) for p in parts for k, b in enumerate(p["solid_bounds"] or [p["bounds"]], 1)]
    result = {}
    for axis, name in enumerate("xyz"):
        low, high = min(items, key=lambda it: it[2][axis]), max(items, key=lambda it: it[2][axis + 3])
        result[name] = {"min": {"part": low[0], "solid": low[1], "value": low[2][axis]},
                        "max": {"part": high[0], "solid": high[1], "value": high[2][axis + 3]}}
    return result


def build(step_path=SOURCE_STEP, root=CACHE_ROOT):
    """Import the STEP once and write facts.json plus BREP solids into cache/<sha12>-v<version>/."""
    started = time.perf_counter()
    digest = source_hash(step_path)
    placed = load_assembly_parts(step_path)
    stages = {"step_import": time.perf_counter() - started}
    parts = [part_facts(i, p) for i, p in enumerate(placed)]
    stages["part_facts"] = time.perf_counter() - started - sum(stages.values())
    connectors = sorted((p.shape for p in placed if p.name == CONNECTOR), key=lambda s: bounds(s)[2])
    guides = [p.shape for p in placed if p.name == GUIDE_PLATE]
    if len(connectors) != 2 or len(guides) != 1:
        raise RuntimeError("Expected two ZXVerbinder occurrences and one ZFuehrungsHalter")
    clamp, motor = rear_clamp_m8(placed), motor_m5(placed)
    facts = {"cache_version": CACHE_VERSION, "source": {"path": Path(step_path).name, "sha256": digest},
             "parts": parts, "rail_coverage": rail_coverage(parts), "rear_clamp_m8": clamp,
             "threaded_joints": threaded_joints(placed, clamp, motor),
             "z_motor": z_motor(placed), "z_moving_set": z_moving_set(parts), "native_extremes": native_extremes(parts),
             "connector_indices": [p["index"] for p in sorted((p for p in parts if p["name"] == CONNECTOR),
                                                               key=lambda p: p["bounds"][2])]}
    stages["derived_facts"] = time.perf_counter() - started - sum(stages.values())
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(mkdtemp(dir=root))
    try:
        # Both connectors in one compound keep their shared definition, so occurrence_offsets() still applies.
        pair = TopoDS_Compound()
        builder = BRep_Builder()
        builder.MakeCompound(pair)
        for shape in connectors:
            builder.Add(pair, shape)
        write_brep(pair, staging / "zxverbinder_pair.brep")
        write_brep(guides[0], staging / "zfuehrungshalter.brep")
        restored = read_connectors(staging)
        if not all(same_solid(a, b) for a, b in zip(connectors, restored)) or not same_solid(
                guides[0], read_brep(staging / "zfuehrungshalter.brep")):
            raise RuntimeError("BREP round trip changed a cached solid")
        stages["brep_round_trip"] = time.perf_counter() - started - sum(stages.values())
        facts["build_seconds"] = {"total": round(time.perf_counter() - started, 1), **{k: round(v, 1) for k, v in stages.items()}}
        (staging / "facts.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")
        target = root / f"{digest[:12]}-v{CACHE_VERSION}"
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    for stale in root.glob(f"{digest[:12]}-v*"):  # older cache versions of the same source STEP
        if stale != target and stale.is_dir():
            shutil.rmtree(stale)
    return target


@dataclass(frozen=True)
class AssemblyCache:
    directory: Path
    facts: dict
    connectors: tuple  # the two original ZXVerbinder solids in the source frame, sorted by Z min
    guide_plate: object
    built: bool
    seconds: float

    def parts_named(self, name):
        return [p for p in self.facts["parts"] if p["name"] == name]

    def occurrences(self, part_id):
        """Facts of every STEP occurrence of a made part id from subassembly.yaml."""
        return self.parts_named(STEP_NAME_ALIASES.get(part_id, part_id))


def load(step_path=SOURCE_STEP, root=CACHE_ROOT):
    """Return the cached assembly, building it first if the source STEP has no valid cache entry."""
    started = time.perf_counter()
    directory = Path(root) / f"{source_hash(step_path)[:12]}-v{CACHE_VERSION}"
    built = not (directory / "facts.json").is_file()
    if built:
        directory = build(step_path, root)
    facts = json.loads((directory / "facts.json").read_text(encoding="utf-8"))
    return AssemblyCache(directory, facts, read_connectors(directory), read_brep(directory / "zfuehrungshalter.brep"),
                         built, round(time.perf_counter() - started, 2))


def read_connectors(directory):
    return tuple(sorted(solids(read_brep(Path(directory) / "zxverbinder_pair.brep")), key=lambda s: bounds(s)[2]))


if __name__ == "__main__":
    cache = load(sys.argv[1] if len(sys.argv) > 1 else SOURCE_STEP)
    print(f"{'built' if cache.built else 'loaded'} {cache.directory.name} in {cache.seconds} s")
