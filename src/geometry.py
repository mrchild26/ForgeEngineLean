"""STEP/BREP I/O and the solid operations used by the cache, the trim rule and the graders (pythonocc-core)."""

from math import isclose, isfinite
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import NamedTuple

from OCC.Core.APIHeaderSection import APIHeaderSection_MakeHeader
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRep import BRep_Builder
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.BRepCheck import BRepCheck_Analyzer
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCC.Core.BRepTools import breptools
from OCC.Core.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
from OCC.Core.GProp import GProp_GProps
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.Message import Message_Fail, message
from OCC.Core.STEPCAFControl import STEPCAFControl_Reader
from OCC.Core.STEPControl import STEPControl_AsIs, STEPControl_Reader, STEPControl_Writer
from OCC.Core.TCollection import TCollection_HAsciiString
from OCC.Core.TDF import TDF_Label, TDF_LabelSequence
from OCC.Core.TDocStd import TDocStd_Document
from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_SOLID
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.TopTools import TopTools_ListOfShape
from OCC.Core.TopoDS import TopoDS_Compound, TopoDS_Shape, topods
from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool
from OCC.Core.gp import gp_Ax2, gp_Dir, gp_Pnt

BOUNDS_TOL_MM = 1e-5
VOLUME_TOL_MM3 = 0.01
STEP_TIMESTAMP = "2026-11-24T00:00:00"  # fixed FILE_NAME time stamp: re-running writes byte-identical STEP files


def quiet_occt_messages():
    """OCCT prints transfer statistics for every STEP read/write. Keep only its failures on the console; a failed read or
    write still raises in this module."""
    printers = message.DefaultMessenger().Printers()
    for index in range(1, printers.Length() + 1):
        printers.Value(index).SetTraceLevel(Message_Fail)


quiet_occt_messages()


class PlacedPart(NamedTuple):
    name: str
    parents: tuple
    shape: TopoDS_Shape


def load_assembly_parts(step_path):
    """Read STEP leaf occurrences with their accumulated assembly placements."""
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    if reader.ReadFile(str(step_path)) != IFSelect_RetDone:
        raise RuntimeError(f"Cannot read assembly STEP: {step_path}")
    document = TDocStd_Document("assembly")
    if not reader.Transfer(document):
        raise RuntimeError("Assembly STEP transfer failed")
    shape_tool = XCAFDoc_DocumentTool.ShapeTool(document.Main())

    def find_parts(label, location, parents):
        definition = label
        if shape_tool.IsReference(label):
            definition = TDF_Label()
            if not shape_tool.GetReferredShape(label, definition):
                raise RuntimeError("Could not resolve an assembly component")
            location = location.Multiplied(shape_tool.GetLocation(label))
        name = definition.GetLabelName()
        if shape_tool.IsAssembly(definition):
            children = TDF_LabelSequence()
            shape_tool.GetComponents(definition, children)
            for index in range(1, children.Length() + 1):
                yield from find_parts(children.Value(index), location, parents + (name,))
        else:
            part = shape_tool.GetShape(definition).Moved(location)
            if part.IsNull():
                raise RuntimeError(f"An occurrence of {name} has no geometry")
            yield PlacedPart(name, parents, part)

    roots = TDF_LabelSequence()
    shape_tool.GetFreeShapes(roots)
    return tuple(part for index in range(1, roots.Length() + 1)
                 for part in find_parts(roots.Value(index), TopLoc_Location(), ()))


def bounds(shape):
    box = Bnd_Box()
    brepbndlib.AddOptimal(shape, box, False, False)  # default bounds extend past faces by the CAD tolerance
    return box.Get()


def volume_mm3(shape):
    props = GProp_GProps()
    brepgprop.VolumeProperties(shape, props)
    return props.Mass()


def area_mm2(shape):
    props = GProp_GProps()
    brepgprop.SurfaceProperties(shape, props)
    return props.Mass()


def _explore(shape, kind):
    explorer = TopExp_Explorer(shape, kind)
    while explorer.More():
        yield explorer.Current()
        explorer.Next()


def faces(shape):
    return (topods.Face(face) for face in _explore(shape, TopAbs_FACE))


def solids(shape):
    return [topods.Solid(solid) for solid in _explore(shape, TopAbs_SOLID)]


def cylinders(shape):
    for face in faces(shape):
        surface = BRepAdaptor_Surface(face)
        if surface.GetType() == GeomAbs_Cylinder:
            yield surface.Cylinder()


def cylinder_faces(shape):
    """(gp_Cylinder, face bounds) of every cylindrical face."""
    for face in faces(shape):
        surface = BRepAdaptor_Surface(face)
        if surface.GetType() == GeomAbs_Cylinder:
            yield surface.Cylinder(), bounds(face)


def plane_faces(shape, axis_index):
    """(position along the axis, face bounds) of every planar face normal to native axis 0/1/2."""
    for face in faces(shape):
        surface = BRepAdaptor_Surface(face)
        if surface.GetType() == GeomAbs_Plane and abs(surface.Plane().Axis().Direction().Coord(axis_index + 1)) > 0.999999:
            yield surface.Plane().Location().Coord(axis_index + 1), bounds(face)


def faces_at_y(shape, y_mm):
    for face in faces(shape):
        surface = BRepAdaptor_Surface(face)
        if surface.GetType() == GeomAbs_Plane:
            plane = surface.Plane()
            if abs(plane.Axis().Direction().Y()) > 0.999999 and isclose(plane.Location().Y(), y_mm, abs_tol=BOUNDS_TOL_MM):
                yield face


def outer_hole_section(shape, box):
    """Outboard Y bores of a connector: (smaller X edge ligament, hole diameter, bore depth, Z width), or None."""
    bores = set()
    for face in faces(shape):
        surface = BRepAdaptor_Surface(face)
        if surface.GetType() == GeomAbs_Cylinder and abs(surface.Cylinder().Axis().Direction().Y()) > 0.999999:
            cylinder, face_box = surface.Cylinder(), bounds(face)
            bores.add((round(cylinder.Location().X(), 6), round(cylinder.Radius() * 2, 6), round(face_box[4] - face_box[1], 6)))
    axes = sorted({x for x, _, _ in bores})
    outer = sorted(bore for bore in bores if axes and bore[0] in (axes[0], axes[-1]))
    if len(axes) != 4 or len(outer) != 2:
        return None
    ligament, diameter, depth = min((min(x - box[0], box[3] - x) - d / 2, d, depth) for x, d, depth in outer)
    return ligament, diameter, depth, round(box[5] - box[2], 6)


def connector_arm_geometry(shape):
    """Outboard arm between inner and outer bolt axes: (span, eccentricity, Z width, Y depth), or None."""
    box = bounds(shape)
    section = outer_hole_section(shape, box)
    axes = sorted({round(c.Location().X(), 6) for c in cylinders(shape) if abs(c.Axis().Direction().Y()) > 0.999999})
    if section is None or section[0] <= 0 or len(axes) != 4:
        return None
    _, _, y_depth, z_width = section
    left, right = axes[1] - axes[0], axes[3] - axes[2]
    if abs(left - right) > 1e-5 or min(left, y_depth, z_width) <= 0:
        return None
    return left, (box[4] - y_depth / 2) - box[1], z_width, y_depth


def setup_count(shape):
    """One setup per unsigned cylindrical axis direction family, at least one (cost model)."""
    directions = {min(axis, tuple(-v for v in axis)) for axis in
                  (tuple(round(v, 6) for v in cylinder.Axis().Direction().Coord()) for cylinder in cylinders(shape))}
    return max(1, len(directions))


def build_boolean(operation, first, second):
    arguments, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
    arguments.Append(first)
    tools.Append(second)
    operation.SetArguments(arguments)
    operation.SetTools(tools)
    operation.SetNonDestructive(True)
    operation.SetRunParallel(True)
    operation.Build()
    if not operation.IsDone() or operation.Shape().IsNull():
        raise RuntimeError("Boolean operation failed")
    return operation.Shape()


def common_shape(first, second):
    return build_boolean(BRepAlgoAPI_Common(), first, second)


def fused_solid(first, second):
    """Union of two touching primitives as one valid solid."""
    result = solids(build_boolean(BRepAlgoAPI_Fuse(), first, second))
    if len(result) != 1 or not BRepCheck_Analyzer(result[0]).IsValid():
        raise RuntimeError("The simplified solid is not one valid solid")
    return result[0]


def motor_envelope(axis_x, axis_y, flange_z, body_mm, shaft_diameter, shaft_length):
    """Simplified motor: a body box below the flange face and the shaft cylinder above it (motor axis along +Z)."""
    width, depth, length = body_mm
    body = BRepPrimAPI_MakeBox(gp_Pnt(axis_x - width / 2, axis_y - depth / 2, flange_z - length), width, depth, length).Shape()
    shaft = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(axis_x, axis_y, flange_z), gp_Dir(0, 0, 1)), shaft_diameter / 2,
                                     shaft_length).Shape()
    return fused_solid(body, shaft)


def socket_head_screw(seat, shank_direction, shank_diameter, length, head_diameter, head_height):
    """Simplified socket head screw: shank from the head seat along shank_direction, head on the other side of the
    seat; thread and socket not modelled. seat = (x, y, z); shank_direction = unit vector along a native axis."""
    point, direction = gp_Pnt(*seat), gp_Dir(*shank_direction)
    shank = BRepPrimAPI_MakeCylinder(gp_Ax2(point, direction), shank_diameter / 2, length).Shape()
    head = BRepPrimAPI_MakeCylinder(gp_Ax2(point, direction.Reversed()), head_diameter / 2, head_height).Shape()
    return fused_solid(shank, head)


def occurrence_offsets(originals, axis_index=1):
    """Placements of each occurrence relative to the first; each must keep the trim axis (mirror allowed)."""
    reference = originals[0]
    offsets = []
    for original in originals:
        if not original.IsPartner(reference) or original.Orientation() != reference.Orientation():
            raise ValueError("The occurrences must share the same oriented STEP definition")
        offset = original.Location().Multiplied(reference.Location().Inverted())
        transform = offset.Transformation()
        others = [row for row in (1, 2, 3) if row != axis_index]
        if not isclose(abs(transform.Value(axis_index, axis_index)), 1, abs_tol=1e-9) or not all(
                isclose(transform.Value(row, axis_index), 0, abs_tol=1e-9) for row in others):
            raise ValueError("A placement moves the trim off its axis")
        offsets.append(offset)
    return tuple(offsets)


def protected_region(original, seat_radius_mm):
    """Box enclosing the ball-nut face (min-Y plane), every mounting hole and its bolt seat."""
    _, ymin, zmin, _, ymax, zmax = bounds(original)
    axes = set()
    for cylinder in cylinders(original):
        if abs(cylinder.Axis().Direction().Y()) < 0.999999:
            raise RuntimeError("Unexpected mounting hole direction")
        if cylinder.Radius() > seat_radius_mm:
            raise RuntimeError("A mounting hole exceeds the protected seat radius")
        axes.add((round(cylinder.Location().X(), 6), round(cylinder.Location().Z(), 6)))
    nut_faces = list(faces_at_y(original, ymin))
    if len(axes) != 4 or len(nut_faces) != 1:
        raise RuntimeError("Expected four mounting axes and one ball-nut face")
    face_xmin, _, _, face_xmax, _, _ = bounds(nut_faces[0])
    xmin = min(face_xmin, min(x for x, _ in axes) - seat_radius_mm)
    xmax = max(face_xmax, max(x for x, _ in axes) + seat_radius_mm)
    return BRepPrimAPI_MakeBox(gp_Pnt(xmin, ymin - 1, zmin - 1), xmax - xmin, ymax - ymin + 2, zmax - zmin + 2).Shape()


def protected_volumes(original, candidate, region):
    """(original core, candidate core, shared core) volumes inside the protected region."""
    original_core, candidate_core = common_shape(original, region), common_shape(candidate, region)
    return volume_mm3(original_core), volume_mm3(candidate_core), volume_mm3(common_shape(original_core, candidate_core))


def trim_symmetric_x(original, trim_mm, seat_radius_mm):
    """Remove equal X-end slabs from a placed solid; refuse a cut into the protected region."""
    if not isfinite(trim_mm) or trim_mm <= 0:
        raise ValueError("trim_mm must be finite and positive")
    xmin, ymin, zmin, xmax, ymax, zmax = bounds(original)
    left_cut, right_cut = xmin + trim_mm, xmax - trim_mm
    region = protected_region(original, seat_radius_mm)
    protected_xmin, _, _, protected_xmax, _, _ = bounds(region)
    if left_cut >= protected_xmin - BOUNDS_TOL_MM or right_cut <= protected_xmax + BOUNDS_TOL_MM:
        raise ValueError("The trim reaches a protected mounting or ball-nut region")
    candidate = original
    for cutter_x in (xmin - 1, right_cut):  # cutters overhang the stock in Y and Z
        cutter = BRepPrimAPI_MakeBox(gp_Pnt(cutter_x, ymin - 1, zmin - 1), trim_mm + 1, ymax - ymin + 2,
                                     zmax - zmin + 2).Shape()
        candidate = build_boolean(BRepAlgoAPI_Cut(), candidate, cutter)
    if not BRepCheck_Analyzer(candidate).IsValid():
        raise RuntimeError("The trimmed solid is invalid")
    if not all(isclose(a, b, abs_tol=BOUNDS_TOL_MM)
               for a, b in zip(bounds(candidate), (left_cut, ymin, zmin, right_cut, ymax, zmax))):
        raise RuntimeError("The trimmed bounds do not match the requested cuts")
    return candidate


def read_step_shape(path):
    reader = STEPControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone or reader.TransferRoots() == 0:
        raise RuntimeError(f"Could not read STEP geometry: {path}")
    shape = reader.OneShape()
    if shape.IsNull():
        raise RuntimeError(f"No shape transferred from STEP: {path}")
    return shape


def placement_key(shape):
    """Sort key: Z min, then X min, then Y min (rounded), so equal-height solids keep a stable order."""
    box = bounds(shape)
    return tuple(round(box[i], 3) for i in (2, 0, 1))


def read_step_solids(path):
    """Placed solids of a part STEP, sorted by Z min (then X, Y)."""
    return tuple(sorted(solids(read_step_shape(path)), key=placement_key))


def same_solid(a, b):
    """Bounds within 1e-5 mm and both volumes equal to their common volume within 0.01 mm^3."""
    if not all(isclose(x, y, abs_tol=BOUNDS_TOL_MM) for x, y in zip(bounds(a), bounds(b))):
        return False
    shared = volume_mm3(common_shape(a, b))
    return all(abs(volume_mm3(shape) - shared) <= VOLUME_TOL_MM3 for shape in (a, b))


def write_verified_step(path, placed_shapes):
    """Write placed solids to one STEP in the source frame and return the verified reimport."""
    path = Path(path)
    compound, builder = TopoDS_Compound(), BRep_Builder()
    builder.MakeCompound(compound)
    for shape in placed_shapes:
        builder.Add(compound, shape)
    path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=path.parent) as staging:
        staged = Path(staging) / path.name
        writer = STEPControl_Writer()
        if writer.Transfer(compound, STEPControl_AsIs) != IFSelect_RetDone:
            raise RuntimeError(f"Could not write {path}")
        APIHeaderSection_MakeHeader(writer.Model()).SetTimeStamp(TCollection_HAsciiString(STEP_TIMESTAMP))
        if writer.Write(str(staged)) != IFSelect_RetDone:
            raise RuntimeError(f"Could not write {path}")
        imported = read_step_solids(staged)
        expected = sorted(placed_shapes, key=placement_key)
        if len(imported) != len(expected) or not all(
                BRepCheck_Analyzer(b).IsValid() and same_solid(a, b) for a, b in zip(expected, imported)):
            raise RuntimeError(f"STEP round trip changed the geometry in {path.name}")
        staged.replace(path)
    return imported


def write_brep(shape, path):
    if not breptools.Write(shape, str(path)):
        raise RuntimeError(f"Could not write BREP {path}")


def read_brep(path):
    shape = TopoDS_Shape()
    if not breptools.Read(shape, str(path), BRep_Builder()) or shape.IsNull():
        raise RuntimeError(f"Could not read BREP {path}")
    return shape
