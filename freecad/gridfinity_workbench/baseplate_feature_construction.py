"""Base plate feature module.

Contains implementation to conscruct baseplate features.
"""

import math

import FreeCAD as fc  # noqa: N813
import Part

from . import clip_profiles
from . import junction_screws as junction_screw_shapes
from . import const, utils
from . import magnet_hole as magnet_hole_module
from .param import (
    BaseplateCoreParams,
    ClickSpringParams,
    ClipParams,
    ClipParamsData,
    FundamentalsParams,
    FundamentalsParamsData,
    JunctionScrewParams,
    JunctionScrewParamsData,
    ScrewStubParams,
)
from .baseplate_full_layout import GridfinityLayout, GridfinityLayoutGeometry


# Cached param instances for defaults - loaded once at module init
_fundamentals = FundamentalsParams()
_fundamentals.load_saved_defaults()

_core = BaseplateCoreParams()
_core.load_saved_defaults()

_click_springs = ClickSpringParams()
_click_springs.load_saved_defaults()

_junction_screws = JunctionScrewParams()
_junction_screws.load_saved_defaults()

_screw_stubs = ScrewStubParams()
_screw_stubs.load_saved_defaults()

_clip = ClipParams()
_clip.load_saved_defaults()


def magnet_holes_properties(obj: fc.DocumentObject) -> None:
    """Make baseplate magnet holes."""
    magnet_hole_module.add_properties(
        obj,
        remove_channel=False,
        chamfer=True,
        magnet_holes_default=True,
    )
    obj.setEditorMode("MagnetHoles", ("ReadOnly", "Hidden"))

    obj.addProperty(
        "App::PropertyLength",
        "MagnetEdgeThickness",
        "NonStandard",
        "Thickness of edge around magnets <br> <br> default = 1.2 mm",
    ).MagnetEdgeThickness = const.MAGNET_EDGE_THICKNESS

    obj.addProperty(
        "App::PropertyLength",
        "MagnetBase",
        "NonStandard",
        "Thickness of base under the magnets <br> <br> default = 0.4 mm",
    ).MagnetBase = const.MAGNET_BASE

    obj.addProperty(
        "App::PropertyLength",
        "MagnetBaseHole",
        "NonStandard",
        "Diameter of the hole at the bottom of the magnet cutout"
        "<br> Set to zero to make disapear"
        "<br> <br> default = 3 mm",
    ).MagnetBaseHole = const.MAGNET_BASE_HOLE

    ## Gridfinity Hidden Properties
    obj.addProperty(
        "App::PropertyLength",
        "BaseThickness",
        "Hidden",
        "Thickness of base under the normal baseplate  profile <br> <br> default = 6.4 mm",
    ).BaseThickness = const.BASE_THICKNESS


def make_magnet_holes(obj: fc.DocumentObject, layout: GridfinityLayout) -> Part.Shape:
    """Create magentholes for a baseplate."""
    x_hole_pos = obj.xGridSize / 2 - obj.MagnetHoleDistanceFromEdge
    y_hole_pos = obj.yGridSize / 2 - obj.MagnetHoleDistanceFromEdge

    # Magnet holes
    shape = magnet_hole_module.from_obj(obj)
    shape = shape.translate(fc.Vector(0, 0, -obj.MagnetHoleDepth))
    screw_hole = Part.makeCylinder(
        obj.MagnetBaseHole / 2,
        obj.MagnetHoleDepth + obj.BaseThickness,
        fc.Vector(0, 0, 0),
        fc.Vector(0, 0, -1),
    )
    shape = shape.fuse(screw_hole)
    shape = utils.copy_and_translate(shape, utils.corners(x_hole_pos, y_hole_pos))

    shape.translate(fc.Vector(obj.xGridSize / 2, obj.yGridSize / 2))

    shape = utils.copy_in_layout(shape, layout, obj.xGridSize, obj.yGridSize)
    return shape.translate(fc.Vector(-obj.xLocationOffset, -obj.yLocationOffset))


def screw_bottom_chamfer_properties(obj: fc.DocumentObject) -> None:
    """Create Baseplate Connection Holes."""
    ## Gridfinity Non Standard Parameters
    obj.addProperty(
        "App::PropertyLength",
        "ScrewHoleDiameter",
        "NonStandard",
        "Diameter of screw holes inside magnet holes <br> <br> default = 3 mm",
    ).ScrewHoleDiameter = const.SCREW_HOLE_DIAMETER

    ## Gridfinity Expert Only Parameters
    obj.addProperty(
        "App::PropertyLength",
        "MagnetBottomChamfer",
        "zzExpertOnly",
        "Chamfer of screwholes on the bottom of the baseplate, allows the use of countersuck"
        "m3 screws in the bottom up to a bin <br> <br> default = 3 mm",
    ).MagnetBottomChamfer = const.MAGNET_BOTTOM_CHAMFER


def make_screw_bottom_chamfer(obj: fc.DocumentObject, layout: GridfinityLayout) -> Part.Shape:
    """Create screw chamfer for a baseplate."""
    x_hole_pos = obj.xGridSize / 2 - obj.MagnetHoleDistanceFromEdge
    y_hole_pos = obj.yGridSize / 2 - obj.MagnetHoleDistanceFromEdge

    ch = Part.makeCone(
        obj.ScrewHoleDiameter / 2 + obj.MagnetBottomChamfer,
        obj.ScrewHoleDiameter / 2,
        obj.MagnetBottomChamfer,
        fc.Vector(0, 0, -obj.TotalHeight + obj.BaseProfileHeight),
    )

    hm1 = utils.copy_and_translate(ch, utils.corners(x_hole_pos, y_hole_pos))
    hm2 = utils.copy_in_layout(hm1, layout, obj.xGridSize, obj.yGridSize)
    return hm2.translate(
        fc.Vector(obj.xGridSize / 2 - obj.xLocationOffset, obj.yGridSize / 2 - obj.yLocationOffset),
    )


def connection_holes_properties(obj: fc.DocumentObject) -> None:
    """Create Baseplate Connection Holes."""
    ## Gridfinity Non Standard Parameters
    obj.addProperty(
        "App::PropertyLength",
        "ConnectionHoleDiameter",
        "NonStandard",
        "Holes on the sides to connect multiple baseplates together <br> <br> default = 3.2 mm",
    ).ConnectionHoleDiameter = const.CONNECTION_HOLE_DIAMETER


def make_connection_holes(obj: fc.DocumentObject, layout: GridfinityLayout) -> Part.Shape:
    """Create connection holes for a baseplate."""
    c1 = Part.makeCylinder(
        obj.ConnectionHoleDiameter / 2,
        obj.BaseThickness,
        fc.Vector(0, -obj.yGridSize / 2, -obj.BaseThickness / 2),
        fc.Vector(0, 1, 0),
    )
    c2 = Part.makeCylinder(
        obj.ConnectionHoleDiameter / 2,
        obj.BaseThickness,
        fc.Vector(
            0,
            -obj.yGridSize / 2 + obj.yTotalWidth - obj.BaseThickness,
            -obj.BaseThickness / 2,
        ),
        fc.Vector(0, 1, 0),
    )

    c3 = Part.makeCylinder(
        obj.ConnectionHoleDiameter / 2,
        obj.BaseThickness,
        fc.Vector(-obj.xGridSize / 2, 0, -obj.BaseThickness / 2),
        fc.Vector(1, 0, 0),
    )
    c4 = Part.makeCylinder(
        obj.ConnectionHoleDiameter / 2,
        obj.BaseThickness,
        fc.Vector(
            -obj.xGridSize / 2 + obj.xTotalWidth - obj.BaseThickness,
            0,
            -obj.BaseThickness / 2,
        ),
        fc.Vector(1, 0, 0),
    )

    vec_list = [fc.Vector(x * obj.xGridSize, 0) for x in range(len(layout))]
    hx = utils.copy_and_translate(c1.fuse(c2), vec_list)

    vec_list = [fc.Vector(0, y * obj.yGridSize) for y in range(len(layout[-1]))]
    hy = utils.copy_and_translate(c3.fuse(c4), vec_list)

    fuse_total = hx.fuse(hy)
    fuse_total = fuse_total.translate(
        fc.Vector(obj.xGridSize / 2 - obj.xLocationOffset, obj.yGridSize / 2 - obj.yLocationOffset),
    )

    return fuse_total


def _center_cut_face(obj: fc.DocumentObject) -> Part.Face:
    """Create wire for the baseplate center cut."""
    x_inframedis = (
        obj.xGridSize / 2 - obj.BaseProfileMainHalfWidth - obj.BaseProfileLowerChamferSize
    )

    y_inframedis = (
        obj.yGridSize / 2 - obj.BaseProfileMainHalfWidth - obj.BaseProfileLowerChamferSize
    )

    x_magedge = (
        obj.xGridSize / 2
        - obj.MagnetHoleDistanceFromEdge
        - obj.MagnetHoleDiameter / 2
        - obj.MagnetEdgeThickness
    )

    y_magedge = (
        obj.yGridSize / 2
        - obj.MagnetHoleDistanceFromEdge
        - obj.MagnetHoleDiameter / 2
        - obj.MagnetEdgeThickness
    )

    x_magcenter = obj.xGridSize / 2 - obj.MagnetHoleDistanceFromEdge
    y_magcenter = obj.yGridSize / 2 - obj.MagnetHoleDistanceFromEdge

    x_smfillpos = x_inframedis - obj.SmallFillet + obj.SmallFillet * math.sin(math.pi / 4)
    y_smfillpos = y_inframedis - obj.SmallFillet + obj.SmallFillet * math.sin(math.pi / 4)

    x_smfillposmag = x_magedge - obj.SmallFillet + obj.SmallFillet * math.sin(math.pi / 4)
    y_smfillposmag = y_magedge - obj.SmallFillet + obj.SmallFillet * math.sin(math.pi / 4)

    x_smfilloffcen = (
        obj.xGridSize / 2
        - obj.MagnetHoleDistanceFromEdge
        - obj.MagnetHoleDiameter / 2
        - obj.MagnetEdgeThickness
        - obj.SmallFillet
    )

    y_smfilloffcen = (
        obj.yGridSize / 2
        - obj.MagnetHoleDistanceFromEdge
        - obj.MagnetHoleDiameter / 2
        - obj.MagnetEdgeThickness
        - obj.SmallFillet
    )

    x_smfillins = x_inframedis - obj.SmallFillet
    y_smfillins = y_inframedis - obj.SmallFillet

    x_bigfillpos = (
        obj.xGridSize / 2
        - obj.MagnetHoleDistanceFromEdge
        - (obj.MagnetHoleDiameter / 2 + obj.MagnetEdgeThickness) * math.sin(math.pi / 4)
    )

    y_bigfillpos = (
        obj.yGridSize / 2
        - obj.MagnetHoleDistanceFromEdge
        - (obj.MagnetHoleDiameter / 2 + obj.MagnetEdgeThickness) * math.sin(math.pi / 4)
    )

    mec_middle = fc.Vector(0, 0, 0)

    v1 = fc.Vector(0, -y_inframedis)
    v2 = fc.Vector(-x_smfilloffcen, -y_inframedis)
    v3 = fc.Vector(-x_magedge, -y_smfillins)
    v4 = fc.Vector(-x_magedge, -y_magcenter)
    v5 = fc.Vector(-x_magcenter, -y_magedge)
    v6 = fc.Vector(-x_smfillins, -y_magedge)
    v7 = fc.Vector(-x_inframedis, -y_smfilloffcen)
    v8 = fc.Vector(-x_inframedis, 0)

    va1 = fc.Vector(-x_smfillposmag, -y_smfillpos)
    va2 = fc.Vector(-x_bigfillpos, -y_bigfillpos)
    va3 = fc.Vector(-x_smfillpos, -y_smfillposmag)

    l1 = Part.LineSegment(v1, v2)
    ar1 = Part.Arc(l1.EndPoint, va1, v3)
    l2 = Part.LineSegment(ar1.EndPoint, v4)
    ar2 = Part.Arc(l2.EndPoint, va2, v5)
    l3 = Part.LineSegment(ar2.EndPoint, v6)
    ar3 = Part.Arc(l3.EndPoint, va3, v7)
    l4 = Part.LineSegment(ar3.EndPoint, v8)
    l5 = Part.LineSegment(l4.EndPoint, mec_middle)
    l6 = Part.LineSegment(l5.EndPoint, l1.StartPoint)

    return utils.curve_to_face([l1, ar1, l2, ar2, l3, ar3, l4, l5, l6])


def center_cut_properties(obj: fc.DocumentObject) -> None:
    """Cut out the  center section of each baseplate grid."""
    obj.addProperty(
        "App::PropertyLength",
        "SmallFillet",
        "NonStandard",
        "Fillets of the main cutout in each grid of the baseplate <br> <br> default = 1 mm",
    ).SmallFillet = const.BASEPLATE_SMALL_FILLET


def make_center_cut(obj: fc.DocumentObject, layout: GridfinityLayout) -> Part.Shape:
    """Create baseplate center cutout."""
    face = _center_cut_face(obj)

    partial_shape1 = face.extrude(fc.Vector(0, 0, -obj.TotalHeight))
    partial_shape2 = partial_shape1.mirror(fc.Vector(0, 0, 0), fc.Vector(0, 1, 0))
    partial_shape3 = partial_shape1.mirror(fc.Vector(0, 0, 0), fc.Vector(1, 0, 0))
    partial_shape4 = partial_shape2.mirror(fc.Vector(0, 0, 0), fc.Vector(1, 0, 0))

    shape = partial_shape1.multiFuse([partial_shape2, partial_shape3, partial_shape4])

    fuse_total = utils.copy_in_layout(shape, layout, obj.xGridSize, obj.yGridSize)

    return fuse_total.translate(
        fc.Vector(obj.xGridSize / 2 - obj.xLocationOffset, obj.yGridSize / 2 - obj.yLocationOffset),
    )


def junction_screw_holes_properties(obj: fc.DocumentObject) -> None:
    """Properties for junction screw holes at internal grid intersections."""
    obj.addProperty(
        "App::PropertyBool",
        "JunctionScrewHoles",
        "GridfinityNonStandard",
        "Toggle internal junction screw holes",
    ).JunctionScrewHoles = _junction_screws.get_value("enabled")

    obj.addProperty(
        "App::PropertyLength",
        "JunctionScrewDiameter",
        "GridfinityNonStandard",
        "Diameter of internal junction screw holes <br> <br> default = 3.3 mm",
    ).JunctionScrewDiameter = _junction_screws.get_value("screw_diameter")

    obj.addProperty(
        "App::PropertyLength",
        "JunctionCounterboreDiameter",
        "GridfinityNonStandard",
        "Counterbore diameter for junction screw holes <br> <br> default = 6 mm",
    ).JunctionCounterboreDiameter = _junction_screws.get_value("counterbore_diameter")

    obj.addProperty(
        "App::PropertyLength",
        "JunctionCounterboreDepth",
        "GridfinityNonStandard",
        "Counterbore depth for junction screw holes <br> <br> default = 1.5 mm",
    ).JunctionCounterboreDepth = _junction_screws.get_value("counterbore_depth")

    obj.addProperty(
        "App::PropertyBool",
        "ScrewStubsEnabled",
        "GridfinityNonStandard",
        "Enable support screw stubs at internal junctions",
    ).ScrewStubsEnabled = _screw_stubs.get_value("enabled")

    obj.addProperty(
        "App::PropertyLength",
        "ScrewStubClearance",
        "GridfinityNonStandard",
        "Radial clearance for support screw stubs <br> <br> default = 0.15 mm",
    ).ScrewStubClearance = _screw_stubs.get_value("clearance")


def clip_cutouts_properties(obj: fc.DocumentObject) -> None:
    """Properties for clip connector cutouts on baseplate edges."""
    obj.addProperty(
        "App::PropertyBool",
        "ClipCutoutsEnabled",
        "GridfinityNonStandard",
        "Toggle clip connector cutouts",
    ).ClipCutoutsEnabled = _clip.get_value("enabled")

    obj.addProperty(
        "App::PropertyLength",
        "ClipLength",
        "GridfinityNonStandard",
        "Length of clip cutout along X <br> <br> default = 3 mm",
    ).ClipLength = _clip.get_value("clip_length")

    obj.addProperty(
        "App::PropertyBool",
        "FillerRightEnabled",
        "GridfinityNonStandard",
        "Enable filler strip on +X side",
    ).FillerRightEnabled = False
    obj.addProperty(
        "App::PropertyLength",
        "FillerRightWidth",
        "GridfinityNonStandard",
        "Width of filler strip on +X side <br> <br> default = 30 mm",
    ).FillerRightWidth = 30

    obj.addProperty(
        "App::PropertyBool",
        "FillerLeftEnabled",
        "GridfinityNonStandard",
        "Enable filler strip on -X side",
    ).FillerLeftEnabled = False
    obj.addProperty(
        "App::PropertyLength",
        "FillerLeftWidth",
        "GridfinityNonStandard",
        "Width of filler strip on -X side <br> <br> default = 30 mm",
    ).FillerLeftWidth = 30

    obj.addProperty(
        "App::PropertyBool",
        "FillerTopEnabled",
        "GridfinityNonStandard",
        "Enable filler strip on +Y side",
    ).FillerTopEnabled = False
    obj.addProperty(
        "App::PropertyLength",
        "FillerTopWidth",
        "GridfinityNonStandard",
        "Width of filler strip on +Y side <br> <br> default = 30 mm",
    ).FillerTopWidth = 30

    obj.addProperty(
        "App::PropertyBool",
        "FillerBottomEnabled",
        "GridfinityNonStandard",
        "Enable filler strip on -Y side",
    ).FillerBottomEnabled = False
    obj.addProperty(
        "App::PropertyLength",
        "FillerBottomWidth",
        "GridfinityNonStandard",
        "Width of filler strip on -Y side <br> <br> default = 30 mm",
    ).FillerBottomWidth = 30


def _profile_wire_to_centered_x_solid(profile_wire: Part.Wire, length: float) -> Part.Shape:
    """Extrude profile along X and center it around x=0."""
    solid = Part.Face(profile_wire).extrude(fc.Vector(length, 0, 0))
    solid.translate(fc.Vector(-length / 2, 0, 0))
    return solid


def make_clip_cutouts(
    obj: fc.DocumentObject,
    layout: GridfinityLayout,
    *,
    geometry: GridfinityLayoutGeometry | None = None,
) -> Part.Shape | None:
    """Create clip cutouts at junctions with exactly 2 orthogonal neighbors."""
    unitmm = fc.Units.Quantity("1 mm")

    max_clip_length = 2 * obj.BaseProfileMainHalfWidth
    if obj.ClipLength >= max_clip_length:
        raise ValueError(
            f"ClipLength ({obj.ClipLength}) must be smaller than "
            f"2*BaseProfileMainHalfWidth ({max_clip_length})"
        )

    use_layout = (
        [[cell.exists for cell in col] for col in geometry.cells]
        if geometry is not None
        else layout
    )
    nx = len(use_layout)
    ny = len(use_layout[0])
    clip_wire = clip_profiles.build_clip_cutout_profile_wire(
        obj.BaseProfileMainHalfWidth,
        obj.BaseProfileMainHeight,
    )
    clip_cutout_top_z = clip_wire.BoundBox.ZMax * unitmm
    max_clip_cutout_top_z = obj.BaseProfileMainHeight + obj.BaseProfileMainHalfWidth
    if clip_cutout_top_z <= max_clip_cutout_top_z:
        raise ValueError(
            f"Clip cutout top Z after scaling ({clip_cutout_top_z}) must be greater than "
            f"BaseProfileMainHeight + BaseProfileMainHalfWidth ({max_clip_cutout_top_z})"
        )
    clip_x = _profile_wire_to_centered_x_solid(clip_wire, obj.ClipLength)

    clip_y = clip_x.copy()
    clip_y.rotate(fc.Vector(0, 0, 0), fc.Vector(0, 0, 1), 90)

    cutouts = []
    if geometry is not None:
        nx, ny = geometry.size()
        for ix in range(nx + 1):
            for iy in range(ny + 1):
                neighbours = geometry.junction_neighbours(ix, iy)
                if neighbours.count_true() != 2:
                    continue
                orientation = neighbours.exists().is_side()
                if orientation is None:
                    continue
                x = geometry.line_x(ix)
                y = geometry.line_y(iy)
                if orientation == "horizontal":
                    cutouts.append(clip_x.translated(fc.Vector(x, y, 0)))
                else:
                    cutouts.append(clip_y.translated(fc.Vector(x, y, 0)))
    else:

        def cell(x: int, y: int) -> bool:
            if 0 <= x < nx and 0 <= y < ny:
                return bool(use_layout[x][y])
            return False

        for ix in range(nx + 1):
            for iy in range(ny + 1):
                south_west_present = cell(ix - 1, iy - 1)
                south_east_present = cell(ix, iy - 1)
                north_west_present = cell(ix - 1, iy)
                north_east_present = cell(ix, iy)

                neighbour_count = (
                    south_west_present
                    + south_east_present
                    + north_west_present
                    + north_east_present
                )
                if neighbour_count != 2:
                    continue

                has_horizontal_pair = (south_west_present and south_east_present) or (
                    north_west_present and north_east_present
                )
                has_vertical_pair = (south_west_present and north_west_present) or (
                    south_east_present and north_east_present
                )
                if not (has_horizontal_pair or has_vertical_pair):
                    continue

                x = ix * obj.xGridSize
                y = iy * obj.yGridSize
                if has_horizontal_pair:
                    cutouts.append(clip_x.translated(fc.Vector(x, y, 0)))
                else:
                    cutouts.append(clip_y.translated(fc.Vector(x, y, 0)))

    if not cutouts:
        return None
    return cutouts[0].multiFuse(cutouts[1:]) if len(cutouts) > 1 else cutouts[0]


def make_clip_cutouts_from_params(
    fundamentals: FundamentalsParamsData,
    clip_cutouts: ClipParamsData,
    *,
    geometry: GridfinityLayoutGeometry,
) -> Part.Shape | None:
    unitmm = fc.Units.Quantity("1 mm")

    max_clip_length = 2 * fundamentals.main_half_width
    if clip_cutouts.clip_length >= max_clip_length:
        raise ValueError(
            f"ClipLength ({clip_cutouts.clip_length}) must be smaller than "
            f"2*BaseProfileMainHalfWidth ({max_clip_length})"
        )

    clip_wire = clip_profiles.build_clip_cutout_profile_wire(
        fundamentals.main_half_width,
        fundamentals.main_height,
    )
    clip_cutout_top_z = clip_wire.BoundBox.ZMax * unitmm
    max_clip_cutout_top_z = fundamentals.main_height + fundamentals.main_half_width
    if clip_cutout_top_z <= max_clip_cutout_top_z:
        raise ValueError(
            f"Clip cutout top Z after scaling ({clip_cutout_top_z}) must be greater than "
            f"BaseProfileMainHeight + BaseProfileMainHalfWidth ({max_clip_cutout_top_z})"
        )
    clip_x = _profile_wire_to_centered_x_solid(clip_wire, clip_cutouts.clip_length)

    clip_y = clip_x.copy()
    clip_y.rotate(fc.Vector(0, 0, 0), fc.Vector(0, 0, 1), 90)

    cutouts = []
    nx, ny = geometry.size()
    for ix in range(nx + 1):
        for iy in range(ny + 1):
            neighbours = geometry.junction_neighbours(ix, iy)
            if neighbours.count_true() != 2:
                continue

            orientation = neighbours.exists().is_side()
            if orientation is None:
                continue

            if neighbours.has_tiny():
                continue

            x = geometry.line_x(ix)
            y = geometry.line_y(iy)
            if orientation == "horizontal":
                cutouts.append(clip_x.translated(fc.Vector(x, y, 0)))
            else:
                cutouts.append(clip_y.translated(fc.Vector(x, y, 0)))

    if not cutouts:
        return None
    return cutouts[0].multiFuse(cutouts[1:]) if len(cutouts) > 1 else cutouts[0]


def make_junction_screw_holes(
    obj: fc.DocumentObject,
    layout: GridfinityLayout,
    *,
    geometry: GridfinityLayoutGeometry | None = None,
) -> Part.Shape | None:
    """Create internal junction screw holes with top-side counterbores.

    For custom layouts, a junction hole is only created where all four surrounding
    cells exist in the layout.
    """
    if geometry is None:
        nx = len(layout)
        ny = len(layout[0])
    else:
        nx, ny = geometry.size()

    through_depth = obj.TotalHeight + 0.1 * fc.Units.Quantity("1 mm")
    top_z = obj.TotalHeight

    cutters = []
    for ix in range(1, nx):
        for iy in range(1, ny):
            if geometry is None:
                if not (
                    layout[ix - 1][iy - 1]
                    and layout[ix][iy - 1]
                    and layout[ix - 1][iy]
                    and layout[ix][iy]
                ):
                    continue
                x = ix * obj.xGridSize
                y = iy * obj.yGridSize
            else:
                neighbours = geometry.junction_neighbours(ix, iy)
                if neighbours.count_true() != 4:
                    continue
                x = geometry.line_x(ix)
                y = geometry.line_y(iy)

            through = Part.makeCylinder(
                obj.JunctionScrewDiameter / 2,
                through_depth,
                fc.Vector(x, y, top_z),
                fc.Vector(0, 0, -1),
            )
            counterbore = Part.makeCylinder(
                obj.JunctionCounterboreDiameter / 2,
                obj.JunctionCounterboreDepth,
                fc.Vector(x, y, top_z),
                fc.Vector(0, 0, -1),
            )
            # 90 degree included-angle transition at the end of the counterbore.
            transition_height = (obj.JunctionCounterboreDiameter - obj.JunctionScrewDiameter) / 2
            transition = Part.makeCone(
                obj.JunctionCounterboreDiameter / 2,
                obj.JunctionScrewDiameter / 2,
                transition_height,
                fc.Vector(x, y, top_z - obj.JunctionCounterboreDepth),
                fc.Vector(0, 0, -1),
            )
            cutters.extend([through, counterbore, transition])

    if not cutters:
        return None
    return cutters[0].multiFuse(cutters[1:]) if len(cutters) > 1 else cutters[0]


def make_junction_screw_holes_from_params(
    fundamentals: FundamentalsParamsData,
    junction_screws: JunctionScrewParamsData,
    top_z: fc.Units.Quantity,
    *,
    geometry: GridfinityLayoutGeometry,
) -> Part.Shape | None:
    return junction_screw_shapes.holes_shape(junction_screws, top_z, geometry)


def base_values_properties(obj: fc.DocumentObject) -> None:
    """Create BinBaseValues.

    Args:
        obj (FreeCAD.DocumentObject): Document object

    """
    ## Reference Parameters
    obj.addProperty(
        "App::PropertyLength",
        "BaseProfileHeight",
        "ReferenceParameters",
        "Height of the Gridfinity Base Profile",
    )

    ## Expert Only Parameters
    obj.addProperty(
        "App::PropertyLength",
        "BaseProfileMainHalfWidth",
        "zzExpertOnly",
        "Half width of main profile section <br> <br> default = 2.15 mm",
    ).BaseProfileMainHalfWidth = _fundamentals.get_value("main_half_width")

    obj.addProperty(
        "App::PropertyLength",
        "BaseProfileMainHeight",
        "zzExpertOnly",
        "Height of main (vertical) section <br> <br> default = 2.5 mm",
    ).BaseProfileMainHeight = _fundamentals.get_value("main_height")

    obj.addProperty(
        "App::PropertyLength",
        "BaseProfileLowerChamferSize",
        "zzExpertOnly",
        "Lower chamfer size <br> <br> default = 0.7 mm",
    ).BaseProfileLowerChamferSize = _core.get_value("lower_chamfer_size")

    obj.addProperty(
        "App::PropertyBool",
        "BaseProfileLowerChamferEnabled",
        "zzExpertOnly",
        "Enable lower chamfer",
    ).BaseProfileLowerChamferEnabled = _core.get_value("lower_chamfer_enabled")

    obj.addProperty(
        "App::PropertyLength",
        "BaseProfileTopCrop",
        "zzExpertOnly",
        "Vertical crop from apex <br> <br> default = 0.8 mm",
    ).BaseProfileTopCrop = _core.get_value("top_crop")

    obj.addProperty(
        "App::PropertyLength",
        "BinOuterRadius",
        "zzExpertOnly",
        "Outer radius of the bin",
    ).BinOuterRadius = _fundamentals.get_value("outer_radius")

    obj.addProperty(
        "App::PropertyLength",
        "BinVerticalRadius",
        "zzExpertOnly",
        "Radius of the base profile Vertical section",
    ).BinVerticalRadius = (
        _fundamentals.get_value("outer_radius") - _fundamentals.get_value("main_half_width")
    )

    # TODO: Clearance is not used for baseplates, only bins. Hardcoded until bin rework.
    obj.addProperty(
        "App::PropertyLength",
        "Clearance",
        "zzExpertOnly",
        "The Clearance between bin and baseplate <br> <br>default = 0.25 mm",
    ).Clearance = 0.25

    obj.addProperty(
        "App::PropertyBool",
        "ClickSpringsEnabled",
        "GridfinityNonStandard",
        "Enable click spring notch generation",
    ).ClickSpringsEnabled = _click_springs.get_value("enabled")

    obj.addProperty(
        "App::PropertyLength",
        "ClickThickness",
        "GridfinityNonStandard",
        "Click spring notch thickness <br> <br> default = 0.8 mm",
    ).ClickThickness = _click_springs.get_value("click_thickness")

    obj.addProperty(
        "App::PropertyLength",
        "ClickLength",
        "GridfinityNonStandard",
        "Click spring notch length <br> <br> default = 12 mm",
    ).ClickLength = _click_springs.get_value("click_length")

    obj.addProperty(
        "App::PropertyLength",
        "ClickOffset",
        "GridfinityNonStandard",
        "Click spring notch center offset in Y <br> <br> default = 0.55 mm",
    ).ClickOffset = _click_springs.get_value("click_offset")

    ## Expressions
    obj.setExpression(
        "BaseProfileHeight",
        "BaseProfileMainHeight + BaseProfileMainHalfWidth - BaseProfileTopCrop",
    )
    obj.setExpression(
        "BinVerticalRadius",
        "BinOuterRadius - BaseProfileMainHalfWidth",
    )

    junction_screw_holes_properties(obj)
    clip_cutouts_properties(obj)


def solid_shape_properties(obj: fc.DocumentObject) -> None:
    """Make solid which the baseplate is cut from."""
    obj.addProperty(
        "App::PropertyLength",
        "TotalHeight",
        "ReferenceDimensions",
        "total height of the bin",
    )


def make_solid_shape(
    obj: fc.DocumentObject,
    baseplate_outside_shape: Part.Wire,
    *,
    baseplate_type: str,
) -> Part.Shape:
    """Create solid which baseplate is cut from.

    Args:
        obj (FreeCAD.DocumentObject): Document object.
        baseplate_outside_shape (Part.Wire): outside profile of the baseplate shape
        baseplate_type (str): type of baseplate being generated

    Returns:
        Part.Shape: Extruded part for the baseplate to be cut from.

    """
    ## Calculated Parameters
    if baseplate_type == "magnet":
        obj.TotalHeight = obj.BaseProfileHeight + obj.MagnetHoleDepth + obj.MagnetBase
    elif baseplate_type == "screw_together":
        obj.TotalHeight = obj.BaseProfileHeight + obj.BaseThickness
    else:
        obj.TotalHeight = obj.BaseProfileHeight

    ## Baseplate Solid Shape Generation
    face = Part.Face(baseplate_outside_shape)

    fuse_total = face.extrude(fc.Vector(0, 0, obj.TotalHeight))
    fuse_total = fuse_total.translate(fc.Vector(-obj.xLocationOffset, -obj.yLocationOffset))

    return fuse_total
