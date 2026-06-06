"""Module containing gridfinity feature constructions."""

from __future__ import annotations

import math
from typing import Literal

import FreeCAD as fc  # noqa: N813
import Part

from . import (
    baseplate_cell_cache,
    baseplate_corner_roundover,
    baseplate_full_layout,
    const,
    junction_screws,
    utils,
)
from . import baseplate_click_springs as click_springs
from . import label_shelf as label_shelf_module
from . import magnet_hole as magnet_hole_module
from .param import (
    BaseplateCoreParamsData,
    CombinedBaseplateParamsData,
    CombinedSupportBaseplateParamsData,
    FundamentalsParamsData,
)

unitmm = fc.Units.Quantity("1 mm")
zeromm = fc.Units.Quantity("0 mm")

ECO_USABLE_HEIGHT = 14
SMALL_NUMBER = 0.01

GridfinityLayout = list[list[bool]]


def label_shelf_properties(obj: fc.DocumentObject, *, label_style_default: str) -> None:
    """Add label shelf properties to an object.

    Args:
        obj (FreeCAD.DocumentObject): Document object.
        label_style_default (str): Default label shelf style.

    """
    ## Gridfinity Parameters
    obj.addProperty(
        "App::PropertyEnumeration",
        "LabelShelfStyle",
        "Gridfinity",
        "Choose to have the label shelf Off or a Standard or Overhang style",
    ).LabelShelfStyle = ["Off", "Standard", "Overhang"]
    obj.LabelShelfStyle = label_style_default

    obj.addProperty(
        "App::PropertyEnumeration",
        "LabelShelfPlacement",
        "Gridfinity",
        "Choose the Placement of the label shelf for each compartement",
    ).LabelShelfPlacement = ["Center", "Full Width", "Left", "Right"]

    ## Gridfinity Non Standard Parameters
    obj.addProperty(
        "App::PropertyLength",
        "LabelShelfWidth",
        "GridfinityNonStandard",
        "Width of the Label Shelf, how far it sticks out from the wall <br> <br> default = 12 mm",
    ).LabelShelfWidth = const.LABEL_SHELF_WIDTH

    obj.addProperty(
        "App::PropertyLength",
        "LabelShelfLength",
        "GridfinityNonStandard",
        "Length of the Label Shelf, how long it is <br> <br> default = 42 mm",
    ).LabelShelfLength = const.LABEL_SHELF_LENGTH

    obj.addProperty(
        "App::PropertyAngle",
        "LabelShelfAngle",
        "GridfinityNonStandard",
        "Angle of the bottom part of the Label Shelf <br> <br> default = 45",
    ).LabelShelfAngle = const.LABEL_SHELF_ANGLE

    ## Expert Only Parameters
    obj.addProperty(
        "App::PropertyLength",
        "LabelShelfStackingOffset",
        "zzExpertOnly",
        "label shelf height decreased when stacking lip is enabled so bin above does not sit"
        "uneven with one end on the label shelf <br> <br> default = 0.4 mm",
    ).LabelShelfStackingOffset = const.LABEL_SHELF_STACKING_OFFSET

    obj.addProperty(
        "App::PropertyLength",
        "LabelShelfVerticalThickness",
        "zzExpertOnly",
        "Vertical Thickness of the Label Shelf <br> <br> default = 2 mm",
    ).LabelShelfVerticalThickness = const.LABEL_SHELF_VERTICAL_THICKNESS


def make_label_shelf(obj: fc.DocumentObject, bintype: Literal["eco", "standard"]) -> Part.Shape:
    """Create label shelf."""
    if (
        bintype == "eco"
        and obj.TotalHeight < ECO_USABLE_HEIGHT
        and obj.LabelShelfStyle != "Overhang"
    ):
        obj.LabelShelfStyle = "Overhang"
        fc.Console.PrintWarning("Label shelf style set to Overhang due to low bin height\n")

    xdiv = obj.xDividers + 1
    ydiv = obj.yDividers + 1
    xcompwidth = (
        obj.xTotalWidth - obj.WallThickness * 2 - obj.DividerThickness * obj.xDividers
    ) / xdiv
    ycompwidth = (
        obj.yTotalWidth - obj.WallThickness * 2 - obj.DividerThickness * obj.yDividers
    ) / ydiv

    shelf_placement = (
        obj.LabelShelfPlacement if obj.LabelShelfLength <= ycompwidth else "Full Width"
    )

    shelf_angle = obj.LabelShelfAngle.Value
    if obj.LabelShelfStyle == "Overhang":
        shelf_angle = 0
        shelf_placement = "Full Width"

    length = obj.LabelShelfLength
    if shelf_placement == "Full Width":
        ydiv = 1
        length = obj.yTotalWidth - obj.WallThickness * 2

    width = calc_stacking_lip_offset(obj) + obj.LabelShelfWidth
    assert width >= 0

    thickness = obj.LabelShelfVerticalThickness
    height = thickness + math.tan(math.radians(shelf_angle)) * width

    funcfuse = label_shelf_module.from_dimensions(
        length=length,
        width=width,
        thickness=thickness,
        height=height,
    )

    if height > obj.UsableHeight:
        boundingbox = Part.makeBox(width, length, height, fc.Vector(0, 0, -obj.UsableHeight))
        funcfuse = funcfuse.common(boundingbox)

    funcfuse = utils.copy_in_grid(
        funcfuse,
        x_count=xdiv,
        y_count=ydiv,
        x_offset=xcompwidth + obj.DividerThickness,
        y_offset=ycompwidth + obj.DividerThickness,
    )

    if shelf_placement == "Center":
        funcfuse.translate(fc.Vector(0, ycompwidth / 2 - obj.LabelShelfLength / 2))
    elif shelf_placement == "Right":
        funcfuse.translate(fc.Vector(0, ycompwidth - obj.LabelShelfLength))

    funcfuse = label_shelf_module.outside_fillet(
        funcfuse,
        offset=0,
        radius=obj.BinOuterRadius - obj.WallThickness,
        height=height,
        y_width=obj.Clearance + obj.yTotalWidth - obj.WallThickness,
    )

    funcfuse.translate(
        fc.Vector(
            obj.Clearance + obj.WallThickness - obj.xLocationOffset,
            obj.Clearance + obj.WallThickness - obj.yLocationOffset,
            -obj.LabelShelfStackingOffset if obj.StackingLip else 0,
        ),
    )

    return funcfuse


def scoop_properties(obj: fc.DocumentObject, *, scoop_default: bool) -> None:
    """Create bin compartments with the option for dividers.

    Args:
        obj (FreeCAD.DocumentObject): Document object.
        scoop_default (bool): Default state of the scoop feature.

    """
    obj.addProperty(
        "App::PropertyLength",
        "ScoopRadius",
        "GridfinityNonStandard",
        "Radius of the Scoop <br> <br> default = 21 mm",
    ).ScoopRadius = const.SCOOP_RADIUS

    obj.addProperty(
        "App::PropertyBool",
        "Scoop",
        "Gridfinity",
        "Toggle the Scoop fillet on or off",
    ).Scoop = scoop_default


def make_scoop(
    obj: fc.DocumentObject,
    *,
    usable_height: None | fc.Units.Quantity = None,
) -> Part.Shape:
    """Create scoop.

    Args:
        obj: The object onto which to add the scoop.
        usable_height: Override the obj's UsableHeight value (for EcoBins).

    EcoBins are constructed in such a way that when the scoop is added, the
    proper usable height (for correct geometry) has to be provided separately.

    """
    if usable_height is None:
        usable_height = obj.UsableHeight

    scooprad1 = obj.ScoopRadius + unitmm
    scooprad2 = obj.ScoopRadius + unitmm
    scooprad3 = obj.ScoopRadius + unitmm

    xcomp_w = (obj.xTotalWidth - obj.WallThickness * 2 - obj.xDividers * obj.DividerThickness) / (
        obj.xDividers + 1
    )

    xdivscoop = obj.xDividerHeight - obj.HeightUnitValue - obj.LabelShelfStackingOffset

    if obj.ScoopRadius > xdivscoop and obj.xDividerHeight != 0:
        scooprad1 = xdivscoop - unitmm
    if obj.ScoopRadius > xcomp_w and obj.xDividers > 0:
        scooprad2 = xcomp_w - 2 * unitmm
    if obj.ScoopRadius > usable_height > 0:
        scooprad3 = usable_height - obj.LabelShelfStackingOffset

    scooprad = min(obj.ScoopRadius, scooprad1, scooprad2, scooprad3)

    if scooprad <= 0:
        raise RuntimeError("Scoop could not be made due to bin selected parameters")

    v1 = fc.Vector(
        obj.xTotalWidth + obj.Clearance - obj.WallThickness,
        0,
        -usable_height + scooprad,
    )
    v2 = fc.Vector(
        obj.xTotalWidth + obj.Clearance - obj.WallThickness,
        0,
        -usable_height,  # type: ignore[arg-type]
    )
    v3 = fc.Vector(
        obj.xTotalWidth + obj.Clearance - obj.WallThickness - scooprad,
        0,
        -usable_height,  # type: ignore[arg-type]
    )

    l1 = Part.LineSegment(v1, v2)
    l2 = Part.LineSegment(v2, v3)

    vc1 = fc.Vector(
        obj.xTotalWidth
        + obj.Clearance
        - obj.WallThickness
        - scooprad
        + scooprad * math.sin(math.pi / 4),
        0,
        -usable_height + scooprad - scooprad * math.sin(math.pi / 4),
    )

    c1 = Part.Arc(v1, vc1, v3)

    s1 = Part.Shape([l1, l2, c1])

    wire = Part.Wire(s1.Edges)

    face = Part.Face(wire)

    xdiv = obj.xDividers + 1
    compwidth = (obj.xTotalWidth - obj.WallThickness * 2 - obj.DividerThickness * obj.xDividers) / (
        xdiv
    )

    scoop = face.extrude(fc.Vector(0, obj.yTotalWidth - obj.WallThickness * 2))

    stacking_lip_offset = calc_stacking_lip_offset(obj)

    vec_list = []
    for x in range(xdiv):
        xtranslate = stacking_lip_offset.Value if x == 0 else x * (compwidth + obj.DividerThickness)
        vec_list.append(fc.Vector(-xtranslate, obj.Clearance + obj.WallThickness))

    funcfuse = utils.copy_and_translate(scoop, vec_list)

    if obj.StackingLip and stacking_lip_offset.Value > 0:  # Scoop is offset from the wall
        scoopbox = Part.makeBox(
            stacking_lip_offset.Value,
            obj.yTotalWidth - obj.WallThickness * 2,
            usable_height,  # type: ignore[arg-type]
            fc.Vector(
                obj.xTotalWidth + obj.Clearance - obj.WallThickness,
                obj.Clearance + obj.WallThickness,
            ),
            fc.Vector(0, 0, -1),
        )
        funcfuse = funcfuse.fuse(scoopbox)

        edges = [
            edge
            for edge in funcfuse.Edges
            if abs(edge.Vertexes[0].Z - edge.Vertexes[1].Z) == usable_height
            and edge.Vertexes[0].X == edge.Vertexes[1].X
        ]

        funcfuse = funcfuse.makeFillet(stacking_lip_offset - 0.01 * unitmm, edges)
    else:  # No stacking lip: Trim scoop to stop it extending outside the rounded bin corners
        bin_outside_shape = utils.create_rounded_rectangle(
            obj.xTotalWidth,
            obj.yTotalWidth,
            0,
            obj.BinOuterRadius,
        ).translate(
            fc.Vector(obj.xTotalWidth / 2 + obj.Clearance, obj.yTotalWidth / 2 + obj.Clearance),
        )
        bin_outside_solid = Part.Face(bin_outside_shape).extrude(
            fc.Vector(0, 0, -obj.TotalHeight + obj.BaseProfileHeight),
        )
        funcfuse = funcfuse.common(bin_outside_solid)

    return funcfuse.translate(fc.Vector(-obj.xLocationOffset, -obj.yLocationOffset))


def _corner_fillets(
    obj: fc.DocumentObject,
    xcomp_width: float,
    ycomp_width: float,
) -> Part.Shape:
    def make_fillet(rotation: float, translation: fc.Vector) -> Part.Shape:
        radius = obj.InsideFilletRadius
        arc = radius - radius * math.sin(math.pi / 4)

        v1 = fc.Vector(0, 0)
        v2 = fc.Vector(0, radius)
        v_arc = fc.Vector(arc, arc)
        v3 = fc.Vector(radius, 0)

        lines = [
            Part.LineSegment(v1, v2),
            Part.Arc(v2, v_arc, v3),
            Part.LineSegment(v3, v1),
        ]

        face = utils.curve_to_face(lines)
        face.rotate(fc.Vector(0, 0, 0), fc.Vector(0, 0, 1), rotation)
        face.translate(translation)
        return face.extrude(fc.Vector(0, 0, -obj.TotalHeight))

    bottom_right_fillet = make_fillet(
        rotation=90,
        translation=fc.Vector(
            obj.Clearance + obj.WallThickness + xcomp_width,
            obj.Clearance + obj.WallThickness,
            -obj.LabelShelfStackingOffset if obj.StackingLip else 0,
        ),
    )
    top_right_fillet = make_fillet(
        rotation=180,
        translation=fc.Vector(
            obj.Clearance + obj.WallThickness + xcomp_width,
            obj.Clearance + obj.WallThickness + ycomp_width,
            -obj.LabelShelfStackingOffset if obj.StackingLip else 0,
        ),
    )
    top_left_fillet = make_fillet(
        rotation=270,
        translation=fc.Vector(
            obj.Clearance + obj.WallThickness,
            obj.Clearance + obj.WallThickness + ycomp_width,
            -obj.LabelShelfStackingOffset if obj.StackingLip else 0,
        ),
    )
    bottom_left_fillet = make_fillet(
        rotation=0,
        translation=fc.Vector(
            obj.Clearance + obj.WallThickness,
            obj.Clearance + obj.WallThickness,
            -obj.LabelShelfStackingOffset if obj.StackingLip else 0,
        ),
    )

    fillets_solid = utils.multi_fuse(
        [bottom_right_fillet, top_right_fillet, top_left_fillet, bottom_left_fillet],
    )
    vec_list = [
        fc.Vector(
            x * (xcomp_width + obj.DividerThickness),
            y * (ycomp_width + obj.DividerThickness),
        )
        for x in range(obj.xDividers + 1)
        for y in range(obj.yDividers + 1)
    ]
    fillets_solid = utils.copy_and_translate(fillets_solid, vec_list)

    return fillets_solid


def _make_compartments_no_deviders(
    obj: fc.DocumentObject,
    func_fuse: Part.Shape,
) -> Part.Shape:
    # Fillet Bottom edges
    b_edges = []
    for edge in func_fuse.Edges:
        z0 = edge.Vertexes[0].Point.z
        z1 = edge.Vertexes[1].Point.z

        if z0 < 0 and z1 < 0:
            b_edges.append(edge)

    return func_fuse.makeFillet(obj.InsideFilletRadius, b_edges)


def _make_compartments_with_deviders(
    obj: fc.DocumentObject,
    func_fuse: Part.Shape,
) -> Part.Shape:
    xdivheight = obj.xDividerHeight if obj.xDividerHeight != 0 else obj.TotalHeight
    ydivheight = obj.yDividerHeight if obj.yDividerHeight != 0 else obj.TotalHeight

    stackingoffset = -obj.LabelShelfStackingOffset if obj.StackingLip else zeromm

    xcomp_w = (obj.xTotalWidth - obj.WallThickness * 2 - obj.xDividers * obj.DividerThickness) / (
        obj.xDividers + 1
    )
    ycomp_w = (obj.yTotalWidth - obj.WallThickness * 2 - obj.yDividers * obj.DividerThickness) / (
        obj.yDividers + 1
    )

    xtranslate = xcomp_w + obj.WallThickness - obj.DividerThickness
    ytranslate = ycomp_w + obj.WallThickness

    # dividers in x direction
    xdiv: Part.Shape | None = None
    for _ in range(obj.xDividers):
        comp = Part.makeBox(
            obj.DividerThickness,
            obj.yTotalWidth,
            xdivheight + stackingoffset,
            fc.Vector(
                obj.Clearance + obj.DividerThickness,
                obj.Clearance,
                -obj.TotalHeight,
            ),
            fc.Vector(0, 0, 1),
        )
        comp.translate(fc.Vector(xtranslate, 0))
        xdiv = comp if xdiv is None else xdiv.fuse(comp)
        xtranslate += xcomp_w + obj.DividerThickness

    # dividers in y direction
    ydiv: Part.Shape | None = None
    for _ in range(obj.yDividers):
        comp = Part.makeBox(
            obj.xTotalWidth,
            obj.DividerThickness,
            ydivheight + stackingoffset,
            fc.Vector(obj.Clearance, obj.Clearance, -obj.TotalHeight),
            fc.Vector(0, 0, 1),
        )

        comp.translate(fc.Vector(0, ytranslate))
        ydiv = comp if ydiv is None else ydiv.fuse(comp)
        ytranslate += ycomp_w + obj.DividerThickness

    if xdiv:
        func_fuse = func_fuse.cut(xdiv)
    if ydiv:
        func_fuse = func_fuse.cut(ydiv)

    func_fuse = func_fuse.cut(_corner_fillets(obj, xcomp_w, ycomp_w))

    return func_fuse


def compartments_properties(obj: fc.DocumentObject, x_div_default: int, y_div_default: int) -> None:
    """Create bin compartments with the option for dividers.

    Args:
        obj (FreeCAD.DocumentObject): Document object.
        x_div_default (int): Default number of dividers.
        y_div_default (int): Default number of dividers.

    """
    ## Gridfinity Parameters

    obj.addProperty(
        "App::PropertyInteger",
        "xDividers",
        "Gridfinity",
        "Number of Dividers in the x direction",
    ).xDividers = x_div_default

    obj.addProperty(
        "App::PropertyInteger",
        "yDividers",
        "Gridfinity",
        "Number of Dividers in the y direction",
    ).yDividers = y_div_default

    ## Gridfinity Non Standard Parameters
    obj.addProperty(
        "App::PropertyLength",
        "InsideFilletRadius",
        "GridfinityNonStandard",
        "inside fillet at the bottom of the bin <br> <br> default = 1.85 mm",
    ).InsideFilletRadius = const.INSIDE_FILLET_RADIUS

    obj.addProperty(
        "App::PropertyLength",
        "DividerThickness",
        "GridfinityNonStandard",
        (
            "Thickness of the dividers, ideally an even multiple of printer layer width"
            "<br> <br> default = 1.2 mm"
        ),
    ).DividerThickness = const.DIVIDER_THICKNESS

    obj.addProperty(
        "App::PropertyLength",
        "xDividerHeight",
        "GridfinityNonStandard",
        "Custom Height of x dividers <br> <br> default = 0 mm = full height",
    ).xDividerHeight = const.CUSTOM_X_DIVIDER_HEIGHT

    obj.addProperty(
        "App::PropertyLength",
        "yDividerHeight",
        "GridfinityNonStandard",
        "Custom Height of y dividers <br> <br> default = 0 mm = full height",
    ).yDividerHeight = const.CUSTOM_Y_DIVIDER_HEIGHT

    ## Referance Parameters
    obj.addProperty(
        "App::PropertyLength",
        "UsableHeight",
        "ReferenceParameters",
        (
            "Height of the bin minus the bottom unit, "
            "the amount of the bin that can be effectively used"
        ),
    )


def make_compartments(obj: fc.DocumentObject, bin_inside_solid: Part.Shape) -> Part.Shape:
    """Create compartment cutout objects.

    Args:
        obj (FreeCAD.DocumentObject): Document object.
        bin_inside_solid (Part.Wire): solid negative of inside bin walls

    Returns:
        Part.Shape: Compartments cutout shape.

    """
    ## Error Checks
    divmin = (
        obj.HeightUnitValue + obj.InsideFilletRadius + 0.05 * unitmm + obj.LabelShelfStackingOffset
    )

    if obj.xDividerHeight < divmin and obj.xDividerHeight != 0:
        obj.xDividerHeight = divmin
        fc.Console.PrintWarning(f"Divider Height must be equal to or greater than:  {divmin}\n")

    if obj.yDividerHeight < divmin and obj.yDividerHeight != 0:
        obj.yDividerHeight = divmin
        fc.Console.PrintWarning(f"Divider Height must be equal to or greater than:  {divmin}\n")

    if (
        obj.xDividerHeight < obj.TotalHeight
        and obj.LabelShelfStyle != "Off"
        and obj.xDividerHeight != 0
        and obj.xDividers != 0
    ):
        obj.LabelShelfStyle = "Off"
        fc.Console.PrintWarning("Label Shelf turned off for less than full height x dividers\n")
    ## Compartment Generation

    if obj.xDividers == 0 and obj.yDividers == 0:
        func_fuse = _make_compartments_no_deviders(obj, bin_inside_solid)
    else:
        func_fuse = _make_compartments_with_deviders(obj, bin_inside_solid)

    return func_fuse.translate(fc.Vector(-obj.xLocationOffset, -obj.yLocationOffset))


def _eco_bin_deviders(obj: fc.DocumentObject, xcomp_w: float, ycomp_w: float) -> Part.Shape:
    stackingoffset = -obj.LabelShelfStackingOffset if obj.StackingLip else zeromm

    xdivheight = obj.xDividerHeight if obj.xDividerHeight != 0 else obj.TotalHeight
    ydivheight = obj.yDividerHeight if obj.yDividerHeight != 0 else obj.TotalHeight

    xtranslate = xcomp_w + obj.WallThickness - obj.DividerThickness
    ytranslate = ycomp_w + obj.WallThickness

    assembly: Part.Shape | None = None

    # dividers in x direction
    for _ in range(obj.xDividers):
        comp = Part.makeBox(
            obj.DividerThickness,
            obj.yTotalWidth,
            xdivheight + stackingoffset,
            fc.Vector(
                -obj.xGridSize / 2 + obj.Clearance + obj.DividerThickness,
                -obj.yGridSize / 2 + obj.Clearance,
                -obj.TotalHeight,
            ),
            fc.Vector(0, 0, 1),
        )
        comp.translate(fc.Vector(xtranslate, 0))

        assembly = comp if assembly is None else assembly.fuse(comp)
        xtranslate += xcomp_w + obj.DividerThickness

    # dividers in y direction
    for _ in range(obj.yDividers):
        comp = Part.makeBox(
            obj.xTotalWidth,
            obj.DividerThickness,
            ydivheight + stackingoffset,
            fc.Vector(
                -obj.xGridSize / 2 + obj.Clearance,
                -obj.yGridSize / 2 + obj.Clearance,
                -obj.TotalHeight,
            ),
            fc.Vector(0, 0, 1),
        )
        comp.translate(fc.Vector(0, ytranslate))
        assembly = comp if assembly is None else assembly.fuse(comp)
        ytranslate += ycomp_w + obj.DividerThickness

    return assembly.translate(fc.Vector(obj.xGridSize / 2, obj.yGridSize / 2))


def eco_error_check(obj: fc.DocumentObject) -> None:
    """Check if eco dividers are possible with current parameters."""
    # Divider Minimum Height

    divmin = obj.HeightUnitValue + obj.InsideFilletRadius + 0.05 * unitmm

    if obj.xDividerHeight < divmin and obj.xDividerHeight != 0:
        obj.xDividerHeight = divmin
        fc.Console.PrintWarning(
            f"Divider Height must be equal to or greater than:  {divmin}\n",
        )

    if obj.yDividerHeight < divmin and obj.yDividerHeight != 0:
        obj.yDividerHeight = divmin
        fc.Console.PrintWarning(
            f"Divider Height must be equal to or greater than:  {divmin}\n",
        )

    if obj.InsideFilletRadius > (1.6 * unitmm):
        obj.InsideFilletRadius = 1.6 * unitmm
        fc.Console.PrintWarning(
            "Inside Fillet Radius must be equal to or less than:  1.6 mm\n",
        )


def eco_compartments_properties(obj: fc.DocumentObject) -> None:
    """Create Eco bin dividers."""
    ## Gridfinity Parameters
    obj.addProperty(
        "App::PropertyLength",
        "BaseWallThickness",
        "Gridfinity",
        "Wall thickness of the bin base",
    ).BaseWallThickness = const.BASE_WALL_THICKNESS

    obj.addProperty(
        "App::PropertyInteger",
        "xDividers",
        "Gridfinity",
        "Number of Dividers in the x direction",
    ).xDividers = const.ECO_X_DIVIDERS

    obj.addProperty(
        "App::PropertyInteger",
        "yDividers",
        "Gridfinity",
        "Number of Dividers in the y direction",
    ).yDividers = const.ECO_Y_DIVIDERS

    ## Gridfinity Non Standard Parameters
    obj.addProperty(
        "App::PropertyLength",
        "InsideFilletRadius",
        "GridfinityNonStandard",
        "inside fillet at the bottom of the bin <br> <br> default = 1.5 mm",
    ).InsideFilletRadius = const.ECO_INSIDE_FILLET_RADIUS

    obj.addProperty(
        "App::PropertyLength",
        "DividerThickness",
        "GridfinityNonStandard",
        (
            "Thickness of the dividers, ideally an even multiple of layer width <br> <br> "
            "default = 0.8 mm"
        ),
    ).DividerThickness = const.ECO_DIVIDER_THICKNESS

    obj.addProperty(
        "App::PropertyLength",
        "xDividerHeight",
        "GridfinityNonStandard",
        "Custom Height of x dividers <br> <br> default = 0 mm = full height",
    ).xDividerHeight = const.CUSTOM_X_DIVIDER_HEIGHT

    obj.addProperty(
        "App::PropertyLength",
        "yDividerHeight",
        "GridfinityNonStandard",
        "Custom Height of y dividers <br> <br> default = 0 mm = full height",
    ).yDividerHeight = const.CUSTOM_Y_DIVIDER_HEIGHT

    ## Reference Parameters
    obj.addProperty(
        "App::PropertyLength",
        "UsableHeight",
        "ReferenceParameters",
        (
            "Height of the bin minus the bottom unit, "
            "the amount of the bin that can be effectively used"
        ),
    )
    ## Hidden Parameters
    obj.setEditorMode("ScrewHoles", 2)


def make_eco_compartments(
    obj: fc.DocumentObject,
    layout: GridfinityLayout,
    bin_inside_solid: Part.Shape,
) -> Part.Shape:
    """Create eco bin cutouts.

    Args:
        obj (FreeCAD.DocumentObject): Document object.
        layout (GridfinityLayout): 2 dimentional list of feature locations.
        bin_inside_solid (Part.Wire): Profile of bin inside wall

    Returns:
        Part.Shape: Eco bin cutout shape.

    """
    eco_error_check(obj)

    ## Compartement Generation

    base_offset = obj.BaseWallThickness * math.tan(math.pi / 8)

    x_bt_cmf_width = (
        obj.xGridSize
        - obj.Clearance * 2
        - 2 * obj.BaseProfileMainHalfWidth
        - 2 * obj.BaseWallThickness
        - 2 * 0.4 * unitmm
    )
    y_bt_cmf_width = (
        obj.yGridSize
        - obj.Clearance * 2
        - 2 * obj.BaseProfileMainHalfWidth
        - 2 * obj.BaseWallThickness
        - 2 * 0.4 * unitmm
    )

    x_vert_width = (
        obj.xGridSize
        - obj.Clearance * 2
        - 2 * obj.BaseProfileMainHalfWidth
        - 2 * obj.BaseWallThickness
    )
    y_vert_width = (
        obj.yGridSize
        - obj.Clearance * 2
        - 2 * obj.BaseProfileMainHalfWidth
        - 2 * obj.BaseWallThickness
    )

    bt_chf_rad = obj.BinVerticalRadius - 0.4 * unitmm - obj.BaseWallThickness
    bt_chf_rad = 0.01 * unitmm if bt_chf_rad <= SMALL_NUMBER else bt_chf_rad

    v_chf_rad = obj.BinVerticalRadius - obj.BaseWallThickness
    v_chf_rad = 0.01 * unitmm if v_chf_rad <= SMALL_NUMBER else v_chf_rad

    magoffset = zeromm
    tp_chf_offset = zeromm
    if obj.MagnetHoles:
        magoffset = obj.MagnetHoleDepth
        if (obj.MagnetHoleDepth + obj.BaseWallThickness) > (
            obj.BaseProfileMainHeight + base_offset
        ):
            tp_chf_offset = (obj.MagnetHoleDepth + obj.BaseWallThickness) - (
                obj.BaseProfileMainHeight + base_offset
            )

    bottom_chamfer = utils.rounded_rectangle_chamfer(
        x_bt_cmf_width,
        y_bt_cmf_width,
        -obj.TotalHeight + obj.BaseWallThickness + magoffset,
        0.4 * unitmm,
        bt_chf_rad,
        v_chf_rad,
    )

    vertical_section = utils.rounded_rectangle_extrude(
        x_vert_width,
        y_vert_width,
        -obj.TotalHeight + obj.BaseWallThickness + 0.4 * unitmm + magoffset,
        obj.BaseProfileMainHeight + base_offset - obj.BaseWallThickness - 0.4 * unitmm,
        v_chf_rad,
    )

    top_chamfer = utils.rounded_rectangle_chamfer(
        x_vert_width + tp_chf_offset,
        y_vert_width + tp_chf_offset,
        -obj.TotalHeight + obj.BaseProfileMainHeight + base_offset + tp_chf_offset,
        obj.BaseProfileMainHalfWidth + obj.BaseWallThickness - tp_chf_offset,
        v_chf_rad,
        obj.BinOuterRadius,
    )
    assembly = bottom_chamfer.multiFuse([vertical_section, top_chamfer])

    eco_base_cut = utils.copy_in_layout(assembly, layout, obj.xGridSize, obj.yGridSize)
    eco_base_cut.translate(fc.Vector(obj.xGridSize / 2, obj.yGridSize / 2))

    func_fuse = bin_inside_solid.fuse(eco_base_cut)

    trim_tanslation = fc.Vector(
        obj.xTotalWidth / 2 + obj.Clearance,
        obj.yTotalWidth / 2 + obj.Clearance,
    )
    outer_trim1 = utils.rounded_rectangle_extrude(
        obj.xTotalWidth - obj.WallThickness * 2,
        obj.yTotalWidth - obj.WallThickness * 2,
        -obj.TotalHeight,
        obj.TotalHeight,
        obj.BinOuterRadius - obj.WallThickness,
    ).translate(trim_tanslation)

    outer_trim2 = utils.rounded_rectangle_extrude(
        obj.xTotalWidth + 20 * unitmm,
        obj.yTotalWidth + 20 * unitmm,
        -obj.TotalHeight,
        obj.TotalHeight - obj.BaseProfileHeight,
        obj.BinOuterRadius,
    ).translate(trim_tanslation)

    outer_trim2 = outer_trim2.cut(outer_trim1)

    func_fuse = func_fuse.cut(outer_trim2)

    xcomp_w = (obj.xTotalWidth - obj.WallThickness * 2 - obj.xDividers * obj.DividerThickness) / (
        obj.xDividers + 1
    )
    ycomp_w = (obj.yTotalWidth - obj.WallThickness * 2 - obj.yDividers * obj.DividerThickness) / (
        obj.yDividers + 1
    )
    if obj.xDividers > 0 or obj.yDividers > 0:
        func_fuse = func_fuse.cut(_eco_bin_deviders(obj, xcomp_w, ycomp_w))

    func_fuse = func_fuse.cut(_corner_fillets(obj, xcomp_w, ycomp_w))

    return func_fuse.translate(fc.Vector(-obj.xLocationOffset, -obj.yLocationOffset))


def bin_base_values_properties(obj: fc.DocumentObject) -> None:
    """Create BinBaseValues.

    Args:
        obj (FreeCAD.DocumentObject): Document object

    """
    ## Expert Only Parameters
    obj.addProperty(
        "App::PropertyLength",
        "BaseProfileMainHalfWidth",
        "zzExpertOnly",
        "Half width of main profile section <br> <br> default = 2.15 mm",
    ).BaseProfileMainHalfWidth = 2.15

    obj.addProperty(
        "App::PropertyLength",
        "BaseProfileMainHeight",
        "zzExpertOnly",
        "Height of main (vertical) section <br> <br> default = 2.5 mm",
    ).BaseProfileMainHeight = 2.5

    obj.addProperty(
        "App::PropertyLength",
        "BaseProfileLowerChamferSize",
        "zzExpertOnly",
        "Lower chamfer size <br> <br> default = 0.7 mm",
    ).BaseProfileLowerChamferSize = 0.7

    obj.addProperty(
        "App::PropertyBool",
        "BaseProfileLowerChamferEnabled",
        "ShouldBeHidden",
        "Enable lower chamfer",
    ).BaseProfileLowerChamferEnabled = True

    obj.addProperty(
        "App::PropertyLength",
        "BaseProfileTopCrop",
        "zzExpertOnly",
        "Vertical crop from apex <br> <br> default = 0.8 mm",
    ).BaseProfileTopCrop = 0.8

    obj.addProperty(
        "App::PropertyLength",
        "BinOuterRadius",
        "zzExpertOnly",
        "Outer radius of the bin",
    ).BinOuterRadius = const.BIN_OUTER_RADIUS

    obj.addProperty(
        "App::PropertyLength",
        "BinVerticalRadius",
        "zzExpertOnly",
        "Radius of the base profile Vertical section",
    ).BinVerticalRadius = const.BIN_BASE_VERTICAL_RADIUS

    obj.addProperty(
        "App::PropertyLength",
        "Clearance",
        "zzExpertOnly",
        (
            "The clearance on each side of a bin between before the edge of the grid,"
            "gives some clearance between bins <br> <br>"
            "default = 0.25 mm"
        ),
    ).Clearance = const.CLEARANCE

    ## Reference Parameters
    obj.addProperty(
        "App::PropertyLength",
        "BaseProfileHeight",
        "ReferenceParameters",
        "Height of the Gridfinity Base Profile, bottom of the bin",
    )

    ## Expressions
    obj.setExpression(
        "BaseProfileHeight",
        "BaseProfileMainHeight + BaseProfileMainHalfWidth",
    )


def make_complex_bin_base(
    obj: fc.DocumentObject,
    layout: GridfinityLayout,
    *,
    for_cutout: bool = False,
) -> Part.Shape:
    """Creaet complex shaped bin base."""
    single = make_complex_bin_base_single(obj, for_cutout=for_cutout)
    fuse_total = utils.copy_in_layout(single, layout, obj.xGridSize, obj.yGridSize)

    return fuse_total.translate(
        fc.Vector(obj.xGridSize / 2 - obj.xLocationOffset, obj.yGridSize / 2 - obj.yLocationOffset),
    )


def make_complex_bin_base_single(
    obj: fc.DocumentObject,
    *,
    for_cutout: bool = False,
) -> Part.Shape:
    """Create one-cell complex shaped bin base centered at origin."""
    if obj.BaseProfileTopCrop >= obj.BaseProfileMainHalfWidth:
        raise ValueError(
            f"BaseProfileTopCrop ({obj.BaseProfileTopCrop}) must be smaller than "
            f"BaseProfileMainHalfWidth ({obj.BaseProfileMainHalfWidth})",
        )

    lower_enabled = (
        bool(getattr(obj, "BaseProfileLowerChamferEnabled", True)) if for_cutout else True
    )
    lower_size = obj.BaseProfileLowerChamferSize if lower_enabled else 0 * unitmm
    upper_size = obj.BaseProfileMainHalfWidth

    # Main section width is compatibility-critical and independent from top ledge tuning.
    clearance_for_widths = 0 * unitmm if for_cutout else obj.Clearance
    x_vert_width = (obj.xGridSize - clearance_for_widths * 2) - 2 * obj.BaseProfileMainHalfWidth
    y_vert_width = (obj.yGridSize - clearance_for_widths * 2) - 2 * obj.BaseProfileMainHalfWidth

    x_bt_cmf_width = x_vert_width - 2 * lower_size
    y_bt_cmf_width = y_vert_width - 2 * lower_size

    vertical_section_height = obj.BaseProfileMainHeight - lower_size

    vertical_section = utils.rounded_rectangle_extrude(
        x_vert_width,
        y_vert_width,
        -obj.TotalHeight + lower_size,
        vertical_section_height,
        obj.BinVerticalRadius,
    )

    if lower_enabled:
        bottom_chamfer = utils.rounded_rectangle_chamfer(
            x_bt_cmf_width,
            y_bt_cmf_width,
            -obj.TotalHeight,
            lower_size,
            obj.BinVerticalRadius - lower_size,
            obj.BinVerticalRadius,
        )
        assembly = bottom_chamfer.fuse(vertical_section)
    else:
        assembly = vertical_section

    top_chamfer = utils.rounded_rectangle_chamfer(
        x_vert_width,
        y_vert_width,
        -obj.TotalHeight + lower_size + vertical_section_height,
        upper_size,
        obj.BinVerticalRadius,
        obj.BinOuterRadius,
    )

    if lower_enabled:
        assembly = bottom_chamfer.multiFuse([vertical_section, top_chamfer])
    else:
        assembly = vertical_section.fuse(top_chamfer)

    if for_cutout:
        top_crop = obj.BaseProfileTopCrop
        crop_slab = utils.make_centered_box(
            obj.xGridSize * 2,
            obj.yGridSize * 2,
            top_crop + obj.TotalHeight,
        )
        assembly = assembly.cut(crop_slab)

    return assembly


def make_complex_bin_base_single_from_params(
    fundamentals: FundamentalsParamsData,
    core: BaseplateCoreParamsData,
    *,
    x_size_override: float | None = None,
    y_size_override: float | None = None,
) -> Part.Shape:
    """Create one-cell complex shaped bin base centered at origin from baseplate params.

    Args:
        fundamentals: Fundamental dimensions with grid_size as standard cell size.
        core: Core parameters.
        x_size_override: Optional override for cell X dimension (for filler cells).
        y_size_override: Optional override for cell Y dimension (for filler cells).

    """
    x_size = x_size_override if x_size_override is not None else float(fundamentals.grid_size)
    y_size = y_size_override if y_size_override is not None else float(fundamentals.grid_size)

    lower_enabled = bool(core.lower_chamfer_enabled)
    lower_size = float(core.lower_chamfer_size) if lower_enabled else 0.0
    upper_size = float(fundamentals.main_half_width)
    total_height = float(fundamentals.main_height) + float(fundamentals.main_half_width)
    bin_vertical_radius = float(fundamentals.outer_radius) - float(fundamentals.main_half_width)
    if bin_vertical_radius <= 0:
        raise ValueError(
            f"BinOuterRadius ({fundamentals.outer_radius}) must be greater than "
            f"BaseProfileMainHalfWidth ({fundamentals.main_half_width})",
        )

    x_vert_width = x_size - 2 * float(fundamentals.main_half_width)
    y_vert_width = y_size - 2 * float(fundamentals.main_half_width)
    x_bt_cmf_width = x_vert_width - 2 * lower_size
    y_bt_cmf_width = y_vert_width - 2 * lower_size
    vertical_section_height = float(fundamentals.main_height) - lower_size

    if x_vert_width <= 0 or y_vert_width <= 0:
        return Part.Shape()
    if lower_enabled and (x_bt_cmf_width <= 0 or y_bt_cmf_width <= 0):
        return Part.Shape()
    # Cell too small for corner radius - treat as tiny cell
    if x_vert_width <= 2 * bin_vertical_radius or y_vert_width <= 2 * bin_vertical_radius:
        return Part.Shape()

    vertical_section = utils.rounded_rectangle_extrude(
        x_vert_width,
        y_vert_width,
        -total_height + lower_size,
        vertical_section_height,
        bin_vertical_radius,
    )

    if lower_enabled:
        bottom_chamfer = utils.rounded_rectangle_chamfer(
            x_bt_cmf_width,
            y_bt_cmf_width,
            -total_height,
            lower_size,
            bin_vertical_radius - lower_size,
            bin_vertical_radius,
        )
        assembly = bottom_chamfer.fuse(vertical_section)
    else:
        assembly = vertical_section

    top_chamfer = utils.rounded_rectangle_chamfer(
        x_vert_width,
        y_vert_width,
        -total_height + lower_size + vertical_section_height,
        upper_size,
        bin_vertical_radius,
        float(fundamentals.outer_radius),
    )

    if lower_enabled:
        assembly = bottom_chamfer.multiFuse([vertical_section, top_chamfer])
    else:
        assembly = vertical_section.fuse(top_chamfer)

    return assembly


def _top_planar_faces(shape: Part.Shape) -> list[Part.Face]:
    """Return all top-most +Z planar faces from shape."""
    top_z = max(face.BoundBox.ZMax for face in shape.Faces)
    z_tol = 1e-7

    faces = []
    for face in shape.Faces:
        if abs(face.BoundBox.ZMax - top_z) > z_tol:
            continue
        if not isinstance(face.Surface, Part.Plane):
            continue
        u_min, u_max, v_min, v_max = face.ParameterRange
        normal = face.normalAt((u_min + u_max) / 2, (v_min + v_max) / 2)
        if normal.z > 0:
            faces.append(face)
    return faces


def make_baseplate_top_support(  # noqa: C901, PLR0915
    params: CombinedBaseplateParamsData | CombinedSupportBaseplateParamsData,
    layout: GridfinityLayout,
    x_location_offset: float = 0.0,
    y_location_offset: float = 0.0,
) -> Part.Shape:
    """Create support body from per-cell slabs and optional center cutouts."""
    main_half_width = params.fundamentals.main_half_width
    outer_radius = params.fundamentals.outer_radius
    bin_vertical_radius = float(outer_radius) - float(main_half_width)
    top_half_width = params.baseplate_core.top_crop
    run = main_half_width + params.click_springs.click_offset - top_half_width

    if run <= 0:
        raise ValueError(
            "Invalid support geometry: BaseProfileMainHalfWidth + ClickOffset "
            "must be greater than BaseProfileTopCrop",
        )

    # Support settings are now nested inside stacking
    support_data = params.stacking.support
    loft_height = run / math.tan(math.radians(float(support_data.overhang_angle)))
    if loft_height <= 0:
        raise ValueError("Invalid support geometry: computed loft height must be positive")

    # Extract junction_screws if available (CombinedBaseplateParamsData)
    # CombinedSupportBaseplateParamsData doesn't have these
    junction_screws_data = getattr(params, "junction_screws", None)
    stacking_data = params.stacking
    connecting_clips_data = getattr(params, "connecting_clips", None)

    # Build a CombinedBaseplateParamsData for build_full_layout
    from .param import (
        ConnectingClipsParamsData,
        JunctionScrewsParamsData,
        ScrewStubsParamsData,
        StackingParamsData,
        SupportParamsData,
    )

    baseplate_params = CombinedBaseplateParamsData(
        fundamentals=params.fundamentals,
        baseplate_size=params.baseplate_size,
        baseplate_core=params.baseplate_core,
        click_springs=params.click_springs,
        junction_screws=junction_screws_data
        or JunctionScrewsParamsData(
            enabled=False,
            screw_diameter=zeromm,
            counterbore_diameter=zeromm,
            counterbore_depth=zeromm,
        ),
        stacking=stacking_data
        or StackingParamsData(
            enabled=False,
            instance_count=1,
            corner_stitching=False,
            stitching_thickness=zeromm,
            screw_stubs=ScrewStubsParamsData(enabled=False, clearance=zeromm),
            support=SupportParamsData(overhang_angle=support_data.overhang_angle),
        ),
        connecting_clips=connecting_clips_data
        or ConnectingClipsParamsData(enabled=False, tolerance=zeromm, clip_length=zeromm),
    )

    geometry = baseplate_full_layout.build_full_layout(
        baseplate_params,
        layout,
        include_spring_masks=bool(params.click_springs.enabled),
    )
    use_layout = [[cell.exists for cell in col] for col in geometry.cells]
    nx_cells = len(geometry.cells)
    ny_cells = len(geometry.cells[0]) if nx_cells > 0 else 0

    slabs: list[Part.Shape] = []
    cutters: list[Part.Shape] = []
    for ix in range(nx_cells):
        for iy in range(ny_cells):
            if not use_layout[ix][iy]:
                continue

            cell_meta = geometry.cells[ix][iy]
            cell_width = cell_meta.width
            cell_height = cell_meta.height
            center_x, center_y = geometry.cell_center(ix, iy)
            cell_center = fc.Vector(
                center_x - x_location_offset,
                center_y - y_location_offset,
                0,
            )

            slab_key = baseplate_cell_cache.make_key(
                {
                    "kind": "support_cell_slab",
                    "width": cell_width,
                    "height": cell_height,
                    "loft_height": float(loft_height),
                },
            )

            def _build_slab(
                cw: float = cell_width,
                ch: float = cell_height,
                lh: float = float(loft_height),
            ) -> Part.Shape:
                return Part.makeBox(
                    cw,
                    ch,
                    lh,
                    fc.Vector(-cw / 2, -ch / 2, 0),
                    fc.Vector(0, 0, 1),
                )

            slab = baseplate_cell_cache.get_or_build(slab_key, _build_slab)
            slab.translate(cell_center)
            slabs.append(slab)

            is_tiny = cell_meta.is_tiny
            geometry.cells[ix][iy].is_tiny = is_tiny
            if is_tiny:
                continue

            x_a = cell_width - 2 * float(main_half_width)
            y_a = cell_height - 2 * float(main_half_width)
            x_b = cell_width - 2 * float(top_half_width)
            y_b = cell_height - 2 * float(top_half_width)
            if x_a <= 0 or y_a <= 0 or x_b <= 0 or y_b <= 0:
                continue

            r_a = min(bin_vertical_radius, max(0.001, min(x_a, y_a) / 2 - 1e-6))
            r_b = min(
                bin_vertical_radius + float(main_half_width) - float(top_half_width),
                max(0.001, min(x_b, y_b) / 2 - 1e-6),
            )

            profile_a_face = Part.Face(utils.create_rounded_rectangle(x_a, y_a, 0, r_a))

            if bool(params.click_springs.enabled):
                seed = click_springs.make_support_click_spring_seed(
                    cell_inner_width=x_a,
                    cell_height=cell_height,
                    click_offset=float(params.click_springs.click_offset),
                    click_length=float(params.click_springs.click_length),
                )
                shift_x = cell_meta.spring_shift_x if cell_meta.kind == "Filler" else 0.0
                shift_y = cell_meta.spring_shift_y if cell_meta.kind == "Filler" else 0.0
                profile_a_face = click_springs.carve_support_profile_with_click_springs(
                    profile_a_face,
                    support_seed=seed,
                    mask=cell_meta.get_mask(),
                    shift_x=shift_x,
                    shift_y=shift_y,
                )

            profile_a = profile_a_face.OuterWire
            profile_a.translate(fc.Vector(0, 0, float(loft_height)))
            profile_b = utils.create_rounded_rectangle(x_b, y_b, 0, r_b)
            cutter_key = baseplate_cell_cache.make_key(
                {
                    "kind": "support_cell_cutter",
                    "x_a": x_a,
                    "y_a": y_a,
                    "x_b": x_b,
                    "y_b": y_b,
                    "r_a": r_a,
                    "r_b": r_b,
                    "loft_height": float(loft_height),
                    "click_enabled": bool(params.click_springs.enabled),
                    "click_length": float(params.click_springs.click_length),
                    "click_offset": float(params.click_springs.click_offset),
                    "mask": cell_meta.get_mask(),
                    "shift_x": cell_meta.spring_shift_x if cell_meta.kind == "Filler" else 0.0,
                    "shift_y": cell_meta.spring_shift_y if cell_meta.kind == "Filler" else 0.0,
                },
            )

            def _build_cutter(
                pb: Part.Wire = profile_b,
                pa: Part.Wire = profile_a,
            ) -> Part.Shape:
                return utils.make_loft([pb, pa], solid=True)

            cutter = baseplate_cell_cache.get_or_build(cutter_key, _build_cutter)
            cutter.translate(cell_center)
            cutters.append(cutter)

    if not slabs:
        return Part.Shape()

    support_solid = utils.multi_fuse(slabs)
    if cutters:
        support_solid = support_solid.cut(utils.multi_fuse(cutters))

    screw_stubs_data = stacking_data.screw_stubs if stacking_data else None
    if (
        junction_screws_data is not None
        and screw_stubs_data is not None
        and junction_screws_data.enabled
        and screw_stubs_data.enabled
    ):
        stub_shape = junction_screws.stubs_shape(
            junction_screws_data,
            screw_stubs_data,
            0 * unitmm,  # Bottom of support
            geometry,
        )
        if stub_shape is not None:
            support_solid = support_solid.fuse(stub_shape)

    return baseplate_corner_roundover.apply_layout_corner_roundover(
        support_solid,
        geometry=geometry,
        outside_radius=float(outer_radius),
        height=float(loft_height),
    )


def blank_bin_recessed_top_properties(obj: fc.DocumentObject) -> None:
    """Create blank bin recessed top section."""
    ## Gridfinity Non Standard Parameters
    obj.addProperty(
        "App::PropertyLength",
        "RecessedTopDepth",
        "GridfinityNonStandard",
        "height per unit <br> <br> default = 0 mm",
    ).RecessedTopDepth = const.RECESSED_TOP_DEPTH


def make_blank_bin_recessed_top(obj: fc.DocumentObject, bin_inside_shape: Part.Wire) -> Part.Shape:
    """Generate Rectanble layout and calculate relevant parameters."""
    face = Part.Face(bin_inside_shape)
    fuse_total = face.extrude(fc.Vector(0, 0, -obj.RecessedTopDepth))
    return fuse_total.translate(fc.Vector(-obj.xLocationOffset, -obj.yLocationOffset))


def bin_bottom_holes_properties(obj: fc.DocumentObject, *, magnet_holes_default: bool) -> None:
    """Create bin solid mid section.

    Args:
        obj (FreeCAD.DocumentObject): Document object
        magnet_holes_default (bool): does the object have magnet holes

    """
    magnet_hole_module.add_properties(
        obj,
        remove_channel=True,
        chamfer=False,
        magnet_holes_default=magnet_holes_default,
    )

    ## Gridfinity Parameters
    obj.addProperty(
        "App::PropertyBool",
        "ScrewHoles",
        "Gridfinity",
        "Toggle the screw holes on or off",
    ).ScrewHoles = const.SCREW_HOLES

    ## Gridfinity Non Standard Parameters
    obj.addProperty(
        "App::PropertyLength",
        "SequentialBridgingLayerHeight",
        "GridfinityNonStandard",
        "Layer Height that you print in for optimal print results,"
        "used for  screw holes bridging with magnet holes also on",
    ).SequentialBridgingLayerHeight = const.SEQUENTIAL_BRIDGING_LAYER_HEIGHT

    obj.addProperty(
        "App::PropertyLength",
        "ScrewHoleDiameter",
        "GridfinityNonStandard",
        "Diameter of Screw Holes, used to put screws in bin to secure in place"
        "<br> <br> default = 3.0 mm",
    ).ScrewHoleDiameter = const.SCREW_HOLE_DIAMETER

    obj.addProperty(
        "App::PropertyLength",
        "ScrewHoleDepth",
        "GridfinityNonStandard",
        "Depth of Screw Holes <br> <br> default = 6.0 mm",
    ).ScrewHoleDepth = const.SCREW_HOLE_DEPTH


def _make_holes_interface(obj: fc.DocumentObject) -> Part.Shape:
    sqbr1_depth = obj.MagnetHoleDepth + obj.SequentialBridgingLayerHeight
    sqbr2_depth = obj.MagnetHoleDepth + obj.SequentialBridgingLayerHeight * 2

    b1 = utils.make_centered_box(
        obj.ScrewHoleDiameter,
        obj.ScrewHoleDiameter,
        sqbr2_depth,
    )
    arc_pt_off_x = (
        math.sqrt(
            ((obj.MagnetHoleDiameter / 2) ** 2) - ((obj.ScrewHoleDiameter / 2) ** 2),
        )
    ) * unitmm
    arc_pt_off_y = obj.ScrewHoleDiameter / 2

    va1 = fc.Vector(arc_pt_off_x, arc_pt_off_y)
    va2 = fc.Vector(-arc_pt_off_x, arc_pt_off_y)
    va3 = fc.Vector(-arc_pt_off_x, -arc_pt_off_y)
    va4 = fc.Vector(arc_pt_off_x, -arc_pt_off_y)
    var1 = fc.Vector(obj.MagnetHoleDiameter / 2, 0)
    var2 = fc.Vector(-obj.MagnetHoleDiameter / 2, 0)
    line_1 = Part.LineSegment(va1, va2)
    line_2 = Part.LineSegment(va3, va4)
    ar1 = Part.Arc(va1, var1, va4)
    ar2 = Part.Arc(va2, var2, va3)
    s1 = Part.Shape([line_1, ar1, ar2, line_2])
    w1 = Part.Wire(s1.Edges)
    sq1_1 = Part.Face(w1)
    sq1_1 = sq1_1.extrude(fc.Vector(0, 0, sqbr1_depth))

    return sq1_1.fuse(b1)


def make_bin_bottom_holes(
    obj: fc.DocumentObject,
    layout: GridfinityLayout,
) -> Part.Shape:
    """Make bin bottom holes."""
    shapes = []
    if obj.MagnetHoles:
        shapes.append(magnet_hole_module.from_obj(obj))
    if obj.ScrewHoles:
        shapes.append(Part.makeCylinder(obj.ScrewHoleDiameter / 2, obj.ScrewHoleDepth))
    if obj.ScrewHoles and obj.MagnetHoles:
        shapes.append(_make_holes_interface(obj))
    shape = utils.multi_fuse(shapes)

    x_pos = obj.xGridSize / 2 - obj.MagnetHoleDistanceFromEdge
    y_pos = obj.yGridSize / 2 - obj.MagnetHoleDistanceFromEdge
    shape = utils.copy_and_translate(shape, utils.corners(x_pos, y_pos, -obj.TotalHeight))

    if obj.MagnetHoles and obj.MagnetRemoveChannel:
        remove_channel = magnet_hole_module.remove_channel(obj).translate(
            fc.Vector(0, 0, -obj.TotalHeight),
        )
        shape = shape.fuse(remove_channel)

    shape = utils.copy_in_layout(shape, layout, obj.xGridSize, obj.yGridSize)
    shape.translate(
        fc.Vector(obj.xGridSize / 2 - obj.xLocationOffset, obj.yGridSize / 2 - obj.yLocationOffset),
    )

    return shape


def calc_stacking_lip_offset(obj: fc.DocumentObject) -> fc.Units.Quantity:
    """Calculate width of stacking lip relative to the inside wall."""
    return (
        (
            obj.StackingLipTopLedge
            + obj.StackingLipTopChamfer
            + (obj.StackingLipBottomChamfer if not obj.StackingLipThinStyle else zeromm)
            - obj.WallThickness
        )
        if obj.StackingLip
        else zeromm
    )


def _stacking_lip_profile(obj: fc.DocumentObject) -> Part.Wire:
    """Create stacking lip profile wire."""
    ## Calculated Values
    obj.StackingLipTopChamfer = (
        obj.BaseProfileMainHalfWidth - obj.Clearance - obj.StackingLipTopLedge
    )

    ## Stacking Lip Generation
    x1 = obj.Clearance
    x2 = x1 + obj.StackingLipTopLedge
    x3 = x2 + obj.StackingLipTopChamfer
    x4 = x3 + obj.StackingLipBottomChamfer
    x5 = obj.Clearance + obj.WallThickness
    y = obj.yGridSize / 2
    z1 = obj.StackingLipBottomChamfer + obj.StackingLipVerticalSection + obj.StackingLipTopChamfer
    z2 = obj.StackingLipBottomChamfer + obj.StackingLipVerticalSection
    z3 = obj.StackingLipBottomChamfer
    z4 = -obj.StackingLipVerticalSection
    z5 = (
        z4
        - obj.StackingLipTopLedge
        - obj.StackingLipTopChamfer
        - obj.StackingLipBottomChamfer
        + obj.WallThickness
    )
    st = [
        fc.Vector(x1, y, 0),
        fc.Vector(x1, y, z1),
        fc.Vector(x2, y, z1),
        fc.Vector(x3, y, z2),
        fc.Vector(x3, y, z3),
        fc.Vector(x4, y, 0),
        fc.Vector(x4, y, z4),
        fc.Vector(x5, y, z5),
        fc.Vector(x1, y, z5),
    ]
    if obj.StackingLipThinStyle:
        st[4:] = [  # Modify the bottom section of the stacking lip profile
            fc.Vector(x3, y, 0),
            fc.Vector(x5, y, -abs(x5.Value - x3.Value)),  # 45 degree chamfer under the lip
            fc.Vector(x1, y, -abs(x5.Value - x3.Value)),
        ]

    stacking_lip_profile = Part.Wire(Part.Shape(utils.loop(st)).Edges)

    return stacking_lip_profile


def stacking_lip_properties(
    obj: fc.DocumentObject,
    *,
    stacking_lip_default: bool,
) -> None:
    """Create bin stacking lip.

    Args:
        obj (FreeCAD.DocumentObject): Document object
        stacking_lip_default (bool): stacking lip on or off

    """
    ## Gridfinity Parameters
    obj.addProperty(
        "App::PropertyBool",
        "StackingLip",
        "Gridfinity",
        "Toggle the stacking lip on or off",
    ).StackingLip = stacking_lip_default

    ## Gridfinity Parameters
    obj.addProperty(
        "App::PropertyBool",
        "StackingLipThinStyle",
        "Gridfinity",
        "Toggle the thin style stacking lip on or off",
    ).StackingLipThinStyle = const.STACKING_LIP_THIN_STYLE

    ## Expert Only Parameters
    obj.addProperty(
        "App::PropertyLength",
        "StackingLipTopLedge",
        "zzExpertOnly",
        "Top Ledge of the stacking lip <br> <br> default = 0.4 mm",
    ).StackingLipTopLedge = const.STACKING_LIP_TOP_LEDGE

    obj.addProperty(
        "App::PropertyLength",
        "StackingLipTopChamfer",
        "zzExpertOnly",
        "Top Chamfer of the Stacking lip",
    )

    obj.addProperty(
        "App::PropertyLength",
        "StackingLipBottomChamfer",
        "zzExpertOnly",
        "Bottom Chamfer of the Stacking lip<br> <br> default = 0.7 mm",
    ).StackingLipBottomChamfer = const.STACKING_LIP_BOTTOM_CHAMFER

    obj.addProperty(
        "App::PropertyLength",
        "StackingLipVerticalSection",
        "zzExpertOnly",
        "vertical section of the Stacking lip<br> <br> default = 1.8 mm",
    ).StackingLipVerticalSection = const.STACKING_LIP_VERTICAL_SECTION


def make_stacking_lip(obj: fc.DocumentObject, bin_outside_shape: Part.Wire) -> Part.Shape:
    """Create stacking lip based on input bin shape.

    Args:
        obj (FreeCAD.DocumentObject): DocumentObject
        bin_outside_shape (Part.Wire): exterior wall of the bin

    """
    wire = _stacking_lip_profile(obj)
    stacking_lip = Part.Wire(bin_outside_shape).makePipe(wire)
    stacking_lip = Part.makeSolid(stacking_lip)
    stacking_lip = stacking_lip.translate(
        fc.Vector(-obj.xLocationOffset, -obj.yLocationOffset),
    )

    return stacking_lip


def bin_solid_mid_section_properties(
    obj: fc.DocumentObject,
    default_height_units: int,
    default_wall_thickness: float,
) -> None:
    """Create bin solid mid section and add properties.

    Args:
        obj (FreeCAD.DocumentObject): Document object
        default_height_units (int): height units of the bin at generation
        default_wall_thickness (int): Wall thickness of the bin at generation

    """
    ## Gridfinity Standard Parameters
    obj.addProperty(
        "App::PropertyInteger",
        "HeightUnits",
        "Gridfinity",
        "Height of the bin in units, each is 7 mm",
    ).HeightUnits = default_height_units

    ## Gridfinity Non Standard Parameters
    obj.addProperty(
        "App::PropertyLength",
        "CustomHeight",
        "GridfinityNonStandard",
        "total height of the bin using the custom height instead of increments of 7 mm",
    ).CustomHeight = 42

    obj.addProperty(
        "App::PropertyBool",
        "NonStandardHeight",
        "GridfinityNonStandard",
        "use a custom height if selected",
    ).NonStandardHeight = False

    obj.addProperty(
        "App::PropertyLength",
        "WallThickness",
        "GridfinityNonStandard",
        "for stacking lip",
    ).WallThickness = default_wall_thickness

    ## Reference Parameters
    obj.addProperty(
        "App::PropertyLength",
        "TotalHeight",
        "ReferenceParameters",
        "total height of the bin",
    )
    ## Expert Only Parameters
    obj.addProperty(
        "App::PropertyLength",
        "HeightUnitValue",
        "zzExpertOnly",
        "height per unit, default is 7mm",
    ).HeightUnitValue = const.HEIGHT_UNIT_VALUE

    ## Expressions
    obj.setExpression(
        "TotalHeight",
        "NonStandardHeight == 1 ? CustomHeight : (HeightUnits * HeightUnitValue)",
    )


def make_bin_solid_mid_section(obj: fc.DocumentObject, bin_outside_shape: Part.Wire) -> Part.Shape:
    """Generate bin solid mid section.

    Args:
        obj (FreeCAD.DocumentObject): Document object.
        bin_outside_shape (Part.Wire): shape of the bin

    """
    face = Part.Face(bin_outside_shape)

    fuse_total = face.extrude(fc.Vector(0, 0, -obj.TotalHeight + obj.BaseProfileHeight))
    fuse_total = fuse_total.translate(fc.Vector(-obj.xLocationOffset, -obj.yLocationOffset))

    return fuse_total
