"""Feature modules contain bins an baseplate objects."""

# ruff: noqa: D101, D102, D107
from __future__ import annotations

import contextlib
from abc import abstractmethod

import FreeCAD as fc  # noqa: N813
import Part

try:
    import FreeCADGui as fcg  # noqa: N813
except ImportError:  # pragma: no cover
    fcg = None

from . import (
    baseplate_builder,
    check_version,
    clip_profiles,
    const,
    grid_initial_layout,
    label_shelf,
    utils,
)
from . import feature_construction as feat
from .custom_shape_features import (
    clean_up_layout,
    custom_shape_solid,
    custom_shape_stacking_lip,
    custom_shape_trim,
    cut_outside_shape,
    vertical_edge_fillet,
    vertical_edge_fillet_with_concave_edges,
)
from .drawer_split import PrintableAxisChunk, split_axis_into_printable_chunks
from .param import (
    BaseplateCoreParams,
    BaseplateSizeParams,
    ClickSpringsParams,
    CombinedBaseplateParams,
    CombinedConnectingClipsParams,
    CombinedDrawerBaseplateParams,
    CombinedDrawerBaseplateParamsData,
    CombinedSupportBaseplateParams,
    ConnectingClipsParams,
    FundamentalsParams,
    JunctionScrewsParams,
    StackingParams,
)
from .version import __version__

unitmm = fc.Units.Quantity("1 mm")


def format_axis_with_filler(cells: int, *, low_fill: bool, high_fill: bool) -> str:
    """Format axis dimension with filler markers (F+N or N+F or F+N+F).

    Args:
        cells: Number of grid cells.
        low_fill: True if filler on low side (left for X, bottom for Y).
        high_fill: True if filler on high side (right for X, top for Y).

    Returns:
        Formatted string like "4", "F+4", "4+F", or "F+4+F".

    """
    prefix = "F+" if low_fill else ""
    suffix = "+F" if high_fill else ""
    return f"{prefix}{cells}{suffix}"


class FoundationGridfinity:
    def __init__(self, obj: fc.DocumentObject) -> None:
        obj.addProperty(
            "App::PropertyString",
            "version",
            "version",
            "Gridfinity Workbench Version",
        ).version = __version__

        obj.Proxy = self

    def onDocumentRestored(self, obj: fc.DocumentObject) -> None:  # noqa: N802
        check_version.migrate_object_version(obj)

    def execute(self, fp: Part.Feature) -> None:
        gridfinity_shape = self.generate_gridfinity_shape(fp)

        if hasattr(fp, "BaseFeature") and fp.BaseFeature is not None:
            # we're inside a PartDesign Body, thus need to fuse with the base feature

            gridfinity_shape.Placement = (
                fp.Placement
            )  # ensure the bin is placed correctly before fusing

            result_shape = fp.BaseFeature.Shape.fuse(gridfinity_shape)
            try:
                result_shape.transformShape(fp.Placement.inverse().toMatrix(), copy=True)
            except TypeError:
                result_shape.transformShape(fp.Placement.inverse().toMatrix(), True)  # noqa: FBT003

            fp.Shape = result_shape

        else:
            fp.Shape = gridfinity_shape

    @abstractmethod
    def generate_gridfinity_shape(self, fp: fc.DocumentObject) -> Part.Shape:
        """Generate the TopoShape of the object."""

    def dumps(self) -> dict:
        """Needed for JSON Serialization when saving a file containing gridfinity object."""
        return {}

    def loads(self, state: dict) -> None:
        """Needed for JSON Serialization when opening a file containing gridfinity object.

        State argument required, otherwise expecting argument error message.
        """


class FullBin(FoundationGridfinity):
    """Gridfinity abstract FullBin object.

    This is not a standalone command, but is used as a base for for BinBlank and BinBase.
    """

    def __init__(
        self,
        obj: fc.DocumentObject,
        *,
        height_units_default: int,
        stacking_lip_default: bool,
    ) -> None:
        super().__init__(obj)

        grid_initial_layout.rectangle_layout_properties(obj, baseplate_default=False)
        feat.bin_solid_mid_section_properties(
            obj,
            default_height_units=height_units_default,
            default_wall_thickness=const.WALL_THICKNESS,
        )
        feat.blank_bin_recessed_top_properties(obj)
        feat.stacking_lip_properties(obj, stacking_lip_default=stacking_lip_default)
        feat.bin_bottom_holes_properties(obj, magnet_holes_default=const.MAGNET_HOLES)
        feat.bin_base_values_properties(obj)

    def generate_gridfinity_shape(self, obj: fc.DocumentObject) -> Part.Shape:
        layout = grid_initial_layout.make_rectangle_layout(obj)

        bin_outside_shape = utils.create_rounded_rectangle(
            obj.xTotalWidth,
            obj.yTotalWidth,
            0,
            obj.BinOuterRadius,
        )
        bin_outside_shape.translate(
            fc.Vector(obj.xTotalWidth / 2 + obj.Clearance, obj.yTotalWidth / 2 + obj.Clearance),
        )

        bin_inside_shape = utils.create_rounded_rectangle(
            obj.xTotalWidth - obj.WallThickness * 2,
            obj.yTotalWidth - obj.WallThickness * 2,
            0,
            obj.BinOuterRadius - obj.WallThickness,
        )
        bin_inside_shape.translate(
            fc.Vector(obj.xTotalWidth / 2 + obj.Clearance, obj.yTotalWidth / 2 + obj.Clearance),
        )

        fuse_total = feat.make_bin_solid_mid_section(obj, bin_outside_shape)
        fuse_total = fuse_total.fuse(feat.make_complex_bin_base(obj, layout))

        if obj.RecessedTopDepth > 0:
            fuse_total = fuse_total.cut(feat.make_blank_bin_recessed_top(obj, bin_inside_shape))

        if obj.StackingLip:
            fuse_total = fuse_total.fuse(feat.make_stacking_lip(obj, bin_outside_shape))

        if obj.ScrewHoles or obj.MagnetHoles:
            fuse_total = fuse_total.cut(feat.make_bin_bottom_holes(obj, layout))

        return fuse_total


class BinBlank(FullBin):
    def __init__(self, obj: fc.DocumentObject) -> None:
        super().__init__(
            obj,
            height_units_default=const.HEIGHT_UNITS,
            stacking_lip_default=const.STACKING_LIP,
        )


class BinBase(FullBin):
    def __init__(self, obj: fc.DocumentObject) -> None:
        super().__init__(
            obj,
            height_units_default=1,
            stacking_lip_default=False,
        )
        obj.setEditorMode("StackingLip", 2)
        obj.setEditorMode("RecessedTopDepth", 2)
        obj.setEditorMode("WallThickness", 2)


class StorageBin(FoundationGridfinity):
    """Gridfinity abstract StorageBin object.

    This is not a standalone command, but is used as a base for for SimpleStorageBin and PartsBin.
    """

    def __init__(
        self,
        obj: fc.DocumentObject,
        *,
        x_div_default: int,
        y_div_default: int,
        label_style_default: str,
        scoop_default: bool,
    ) -> None:
        super().__init__(obj)

        grid_initial_layout.rectangle_layout_properties(obj, baseplate_default=False)
        feat.bin_solid_mid_section_properties(
            obj,
            default_height_units=const.HEIGHT_UNITS,
            default_wall_thickness=const.WALL_THICKNESS,
        )
        feat.stacking_lip_properties(obj, stacking_lip_default=const.STACKING_LIP)
        feat.bin_bottom_holes_properties(obj, magnet_holes_default=const.MAGNET_HOLES)
        feat.bin_base_values_properties(obj)
        feat.compartments_properties(obj, x_div_default=x_div_default, y_div_default=y_div_default)
        feat.label_shelf_properties(obj, label_style_default=label_style_default)
        feat.scoop_properties(obj, scoop_default=scoop_default)

        obj.setExpression("UsableHeight", "TotalHeight - HeightUnitValue")

    def generate_gridfinity_shape(self, obj: fc.DocumentObject) -> Part.Shape:
        layout = grid_initial_layout.make_rectangle_layout(obj)

        bin_outside_shape = utils.create_rounded_rectangle(
            obj.xTotalWidth,
            obj.yTotalWidth,
            0,
            obj.BinOuterRadius,
        )
        bin_outside_shape.translate(
            fc.Vector(obj.xTotalWidth / 2 + obj.Clearance, obj.yTotalWidth / 2 + obj.Clearance),
        )

        bin_inside_shape = utils.create_rounded_rectangle(
            obj.xTotalWidth - obj.WallThickness * 2,
            obj.yTotalWidth - obj.WallThickness * 2,
            0,
            max(obj.BinOuterRadius - obj.WallThickness, 0.5 * unitmm),
        )
        bin_inside_shape.translate(
            fc.Vector(obj.xTotalWidth / 2 + obj.Clearance, obj.yTotalWidth / 2 + obj.Clearance),
        )

        fuse_total = feat.make_bin_solid_mid_section(obj, bin_outside_shape)
        fuse_total = fuse_total.fuse(feat.make_complex_bin_base(obj, layout))
        face = Part.Face(bin_inside_shape).translate(fc.Vector(0, 0, -obj.UsableHeight))
        compartments = face.extrude(fc.Vector(0, 0, obj.UsableHeight))

        fuse_total = fuse_total.cut(feat.make_compartments(obj, compartments))

        if obj.StackingLip:
            fuse_total = fuse_total.fuse(feat.make_stacking_lip(obj, bin_outside_shape))

        if obj.ScrewHoles or obj.MagnetHoles:
            fuse_total = fuse_total.cut(feat.make_bin_bottom_holes(obj, layout))

        if obj.LabelShelfStyle != "Off":
            fuse_total = fuse_total.fuse(feat.make_label_shelf(obj, "standard"))

        if obj.Scoop:
            fuse_total = fuse_total.fuse(feat.make_scoop(obj))

        return fuse_total.removeSplitter()


class SimpleStorageBin(StorageBin):
    def __init__(self, obj: fc.DocumentObject) -> None:
        super().__init__(
            obj,
            x_div_default=0,
            y_div_default=0,
            label_style_default="Off",
            scoop_default=False,
        )


class PartsBin(StorageBin):
    def __init__(self, obj: fc.DocumentObject) -> None:
        super().__init__(
            obj,
            x_div_default=const.X_DIVIDERS,
            y_div_default=const.Y_DIVIDERS,
            label_style_default="Standard",
            scoop_default=const.SCOOP,
        )


class EcoBin(FoundationGridfinity):
    def __init__(self, obj: fc.DocumentObject) -> None:
        super().__init__(obj)

        grid_initial_layout.rectangle_layout_properties(obj, baseplate_default=False)
        feat.bin_solid_mid_section_properties(
            obj,
            default_height_units=const.HEIGHT_UNITS,
            default_wall_thickness=const.ECO_WALL_THICKNESS,
        )
        feat.stacking_lip_properties(obj, stacking_lip_default=const.STACKING_LIP)
        feat.bin_bottom_holes_properties(obj, magnet_holes_default=False)
        feat.bin_base_values_properties(obj)
        feat.label_shelf_properties(obj, label_style_default="Standard")
        feat.eco_compartments_properties(obj)
        feat.scoop_properties(obj, scoop_default=False)

        obj.setExpression("UsableHeight", "TotalHeight - HeightUnitValue")

    def generate_gridfinity_shape(self, obj: fc.DocumentObject) -> Part.Shape:
        layout = grid_initial_layout.make_rectangle_layout(obj)

        bin_outside_shape = utils.create_rounded_rectangle(
            obj.xTotalWidth,
            obj.yTotalWidth,
            0,
            obj.BinOuterRadius,
        )
        bin_outside_shape.translate(
            fc.Vector(obj.xTotalWidth / 2 + obj.Clearance, obj.yTotalWidth / 2 + obj.Clearance, 0),
        )

        bin_inside_shape = utils.create_rounded_rectangle(
            obj.xTotalWidth - obj.WallThickness * 2,
            obj.yTotalWidth - obj.WallThickness * 2,
            0,
            obj.BinOuterRadius - obj.WallThickness,
        )
        bin_inside_shape.translate(
            fc.Vector(obj.xTotalWidth / 2 + obj.Clearance, obj.yTotalWidth / 2 + obj.Clearance, 0),
        )

        fuse_total = feat.make_bin_solid_mid_section(obj, bin_outside_shape)
        fuse_total = fuse_total.fuse(feat.make_complex_bin_base(obj, layout))
        face = Part.Face(bin_inside_shape).translate(
            fc.Vector(
                0,
                0,
                -obj.TotalHeight + obj.BaseProfileHeight + obj.BaseWallThickness,
            ),
        )

        compartment_solid = face.extrude(
            fc.Vector(0, 0, obj.TotalHeight - obj.BaseProfileHeight - obj.BaseWallThickness),
        )

        # First cut eco compartments to create the interior spaces
        eco_compartments = feat.make_eco_compartments(obj, layout, compartment_solid)
        fuse_total = fuse_total.cut(eco_compartments)

        # Now add scoop, but only where eco compartments exist (reversed logic)
        if obj.Scoop:
            scoop = feat.make_scoop(obj, usable_height=obj.TotalHeight - obj.BaseWallThickness)
            # Only add scoop where compartments exist - use intersection to constrain
            scoop_constrained = scoop.common(eco_compartments)
            fuse_total = fuse_total.fuse(scoop_constrained)

        if obj.ScrewHoles or obj.MagnetHoles:
            fuse_total = fuse_total.cut(feat.make_bin_bottom_holes(obj, layout))

        if obj.StackingLip:
            fuse_total = fuse_total.fuse(feat.make_stacking_lip(obj, bin_outside_shape))

        if obj.LabelShelfStyle != "Off":
            fuse_total = fuse_total.fuse(feat.make_label_shelf(obj, "eco"))

        return fuse_total.removeSplitter()


class Baseplate(FoundationGridfinity):
    def __init__(self, obj: fc.DocumentObject) -> None:
        super().__init__(obj)
        CombinedBaseplateParams().add_all_properties_to_object(obj)

    def generate_gridfinity_shape(self, obj: fc.DocumentObject) -> Part.Shape:
        params = CombinedBaseplateParams().from_obj(obj)
        data = params.data()

        if data.stacking.enabled:
            return _build_stacked_baseplates_shape(obj)

        return baseplate_builder.build_simple_baseplate_from_params(data, preview=False)


class DrawerBaseplateGroup:
    """Group container for drawer baseplate pieces.

    Holds parameters and manages child Baseplate objects. Children are independent
    baseplates with their own parameters, but tracked via RowIndex/ColumnIndex properties.

    Uses PropertyLinkListHidden for child storage to avoid recompute dependencies.
    Visual tree nesting is achieved via claimChildren() in the ViewProvider.

    In preview mode, no children are created. Instead, build_preview_shape() returns
    a combined preview shape for all pieces.

    On accept (PreviewBuildMode=False), children are created/updated as independent
    Baseplate objects with full parameters copied from the group.
    """

    def __init__(self, obj: fc.DocumentObject) -> None:
        obj.addProperty(
            "App::PropertyString",
            "version",
            "version",
            "Gridfinity Workbench Version",
        ).version = __version__

        CombinedDrawerBaseplateParams().add_all_properties_to_object(obj)

        obj.addProperty(
            "App::PropertyStringList",
            "PieceNames",
            "ReferenceParameters",
            "Deterministic names for generated drawer baseplate pieces",
        ).PieceNames = []
        # Use PropertyLinkListHidden to store children without creating recompute dependencies
        # Visual nesting in tree is handled by claimChildren() in ViewProvider
        obj.addProperty(
            "App::PropertyLinkListHidden",
            "Children",
            "Base",
            "Child baseplate objects (no dependency)",
        ).Children = []

        obj.Proxy = self

    def onDocumentRestored(self, obj: fc.DocumentObject) -> None:  # noqa: N802
        check_version.migrate_object_version(obj)

    def execute(self, obj: fc.DocumentObject) -> None:
        """Create/update/remove child Baseplate objects."""
        x_chunks, y_chunks_for_rows, grid_mm, full_data = _compute_drawer_splits_from_obj(obj)
        if x_chunks is None:
            return

        required_pieces = _build_required_pieces(x_chunks, y_chunks_for_rows)
        existing_children = self._get_existing_children(obj)
        self._remove_stale_children(obj, existing_children, required_pieces)
        baseplate_names = self._create_or_update_children(
            obj, x_chunks, y_chunks_for_rows, grid_mm, full_data, required_pieces, existing_children
        )
        obj.PieceNames = baseplate_names

        # Clear touched state on all children after creation/update
        # This prevents FreeCAD 1.1 "still touched after recompute" warnings
        for child in obj.Children:
            child.purgeTouched()

    def build_preview_shape(self, obj: fc.DocumentObject) -> Part.Shape:
        """Build combined preview shape for all pieces without creating children.

        Delegates to standalone build_drawer_baseplate_preview_shape() function.
        """
        params: CombinedDrawerBaseplateParams = (
            CombinedDrawerBaseplateParams().from_obj(obj)  # type: ignore[assignment]
        )
        return build_drawer_baseplate_preview_shape(params)

    def _remove_stale_children(
        self,
        obj: fc.DocumentObject,
        existing_children: dict[str, fc.DocumentObject],
        required_pieces: dict[str, tuple[int, int]],
    ) -> None:
        """Remove children that are no longer needed."""
        doc = obj.Document
        children_to_keep = []
        for piece_key, child in list(existing_children.items()):
            if piece_key not in required_pieces:
                doc.removeObject(child.Name)
            else:
                children_to_keep.append(child)
        # Update Children property with remaining children
        # (new children will be added in _create_or_update_children)
        obj.Children = children_to_keep

    def _create_or_update_children(  # noqa: PLR0913
        self,
        obj: fc.DocumentObject,
        x_chunks: list,
        y_chunks_for_rows: list,
        grid_mm: float,
        full_data: object,
        required_pieces: dict[str, tuple[int, int]],
        existing_children: dict[str, fc.DocumentObject],
    ) -> list[str]:
        """Create or update child Baseplate objects with full parameters."""
        status_bar = None
        if fc.GuiUp and fcg is not None:
            with contextlib.suppress(Exception):
                status_bar = fcg.getMainWindow().statusBar()

        doc = obj.Document
        combined_params: CombinedDrawerBaseplateParams = (
            CombinedDrawerBaseplateParams().from_obj(obj)  # type: ignore[assignment]
        )
        total_pieces = len(required_pieces)
        baseplate_names: list[str] = []

        # Tile positioning parameters
        bed_w = float(full_data.printer.bed_width)
        bed_d = float(full_data.printer.bed_depth)
        plate_gap_x = 42.0
        plate_gap_y = 42.0
        y_chunk_count = len(y_chunks_for_rows)

        for built_count, (piece_key, (row_index, column_index)) in enumerate(
            required_pieces.items(), start=1
        ):
            x_chunk = x_chunks[column_index]
            y_chunk = y_chunks_for_rows[row_index]
            width_mm = x_chunk.cells * grid_mm + x_chunk.low_fill_mm + x_chunk.high_fill_mm
            depth_mm = y_chunk.cells * grid_mm + y_chunk.low_fill_mm + y_chunk.high_fill_mm
            x_str = format_axis_with_filler(
                x_chunk.cells, low_fill=x_chunk.low_fill_mm > 0, high_fill=x_chunk.high_fill_mm > 0
            )
            y_str = format_axis_with_filler(
                y_chunk.cells, low_fill=y_chunk.low_fill_mm > 0, high_fill=y_chunk.high_fill_mm > 0
            )
            baseplate_name = (
                f"Drawer Baseplate {x_str} x {y_str} ({column_index + 1}, {row_index + 1})"
            )
            baseplate_names.append(baseplate_name)

            # Compute placement
            tile_center_x = (column_index * (bed_w + plate_gap_x)) + (0.5 * bed_w)
            tile_center_y = (y_chunk_count - 1 - row_index) * (bed_d + plate_gap_y) + 0.5 * bed_d
            placement_x = tile_center_x - (width_mm / 2)
            placement_y = tile_center_y - (depth_mm / 2)

            # Build full CombinedBaseplateParams for this chunk
            baseplate_params = _build_baseplate_params_for_chunk(combined_params, x_chunk, y_chunk)

            if piece_key in existing_children:
                child = existing_children[piece_key]
                # Update existing child's params
                baseplate_params.to_obj(child)
                child.Label = baseplate_name
                child.Placement.Base = fc.Vector(placement_x, placement_y, 0)
                child.touch()
                child.recompute()
            else:
                self._create_child_baseplate(
                    obj,
                    doc,
                    piece_key,
                    row_index,
                    column_index,
                    baseplate_name,
                    placement_x,
                    placement_y,
                    baseplate_params,
                )

            if status_bar is not None:
                status_bar.showMessage(
                    f"Drawer baseplates: {built_count}/{total_pieces} ({baseplate_name})"
                )

        if status_bar is not None:
            status_bar.showMessage(f"Drawer baseplates: {total_pieces} pieces ready", 2500)

        return baseplate_names

    def _create_child_baseplate(  # noqa: PLR0913
        self,
        obj: fc.DocumentObject,
        doc: fc.Document,
        piece_key: str,
        row_index: int,
        column_index: int,
        label: str,
        placement_x: float,
        placement_y: float,
        baseplate_params: CombinedBaseplateParams,
    ) -> None:
        """Create a single Baseplate child object with full parameters."""
        child = doc.addObject("Part::FeaturePython", piece_key)
        Baseplate(child)  # Regular Baseplate with all properties
        child.Label = label

        # Add position tracking properties for matching during edits
        child.addProperty(
            "App::PropertyInteger", "RowIndex", "DrawerPiece", "Row index in drawer grid"
        ).RowIndex = row_index
        child.addProperty(
            "App::PropertyInteger", "ColumnIndex", "DrawerPiece", "Column index in drawer grid"
        ).ColumnIndex = column_index

        # Set all baseplate params
        baseplate_params.to_obj(child)

        # Add to Children property (no dependency, just tracking)
        obj.Children = [*obj.Children, child]

        # Set placement (shapes are built at origin)
        child.Placement.Base = fc.Vector(placement_x, placement_y, 0)

        # Force immediate recompute to build shape
        child.recompute()
        child.purgeTouched()

        # Attach ViewProvider proxy
        if fc.GuiUp:
            vo = child.ViewObject
            if vo is not None and getattr(vo, "Proxy", None) is None:
                vo.Proxy = 0

    @staticmethod
    def _get_existing_children(obj: fc.DocumentObject) -> dict[str, fc.DocumentObject]:
        """Get existing Baseplate children indexed by piece key (row, col)."""
        existing: dict[str, fc.DocumentObject] = {}
        for child in getattr(obj, "Children", []):
            proxy = getattr(child, "Proxy", None)
            if isinstance(proxy, Baseplate):
                row = getattr(child, "RowIndex", None)
                col = getattr(child, "ColumnIndex", None)
                if row is not None and col is not None:
                    existing[f"Piece_{row}_{col}"] = child
        return existing

    def dumps(self) -> dict:
        return {}

    def loads(self, state: dict) -> None:
        pass


def _compute_drawer_splits_from_data(
    full_data: CombinedDrawerBaseplateParamsData,
) -> tuple[list | None, list | None, float | None]:
    """Compute drawer split chunks from params data.

    Returns (x_chunks, y_chunks_for_rows, grid_mm) or (None, None, None) if invalid.
    """
    grid_mm = float(full_data.fundamentals.grid_size)
    algo = full_data.drawer.split_algorithm
    split_algorithm = "balanced" if algo == "Balanced" else "greedy" if algo == "Greedy" else None
    if split_algorithm is None:
        return None, None, None

    x_chunks = split_axis_into_printable_chunks(
        length_mm=float(full_data.drawer.drawer_width),
        bed_mm=float(full_data.printer.bed_width),
        grid_mm=grid_mm,
        alignment=(
            "low"
            if full_data.drawer.width_filler_alignment == "Left"
            else ("high" if full_data.drawer.width_filler_alignment == "Right" else "both")
        ),
        algorithm=split_algorithm,
    )
    y_chunks = split_axis_into_printable_chunks(
        length_mm=float(full_data.drawer.drawer_depth),
        bed_mm=float(full_data.printer.bed_depth),
        grid_mm=grid_mm,
        alignment=(
            "low"
            if full_data.drawer.depth_filler_alignment == "Bottom"
            else ("high" if full_data.drawer.depth_filler_alignment == "Top" else "both")
        ),
        algorithm=split_algorithm,
    )
    return x_chunks, list(reversed(y_chunks)), grid_mm


def _compute_drawer_splits_from_obj(obj: fc.DocumentObject) -> tuple:
    """Compute drawer split chunks from group object params.

    Returns (x_chunks, y_chunks_for_rows, grid_mm, full_data) or (None, None, None, None).
    """
    combined_params = CombinedDrawerBaseplateParams().from_obj(obj)
    full_data = combined_params.data()
    x_chunks, y_chunks_for_rows, grid_mm = _compute_drawer_splits_from_data(full_data)
    if x_chunks is None:
        return None, None, None, None
    return x_chunks, y_chunks_for_rows, grid_mm, full_data


def _build_required_pieces(x_chunks: list, y_chunks_for_rows: list) -> dict[str, tuple[int, int]]:
    """Build dict of required piece keys to (row, col) indices."""
    required: dict[str, tuple[int, int]] = {}
    for row_index, y_chunk in enumerate(y_chunks_for_rows):
        for col_index, x_chunk in enumerate(x_chunks):
            if x_chunk.cells >= 1 and y_chunk.cells >= 1:
                required[f"Piece_{row_index}_{col_index}"] = (row_index, col_index)
    return required


def build_drawer_baseplate_preview_shape(
    params: CombinedDrawerBaseplateParams,
) -> Part.Shape:
    """Build combined preview shape for drawer baseplate pieces.

    Returns a compound shape containing simplified preview shapes for all pieces,
    positioned according to the tile layout.

    This is a standalone function that can be called from task panels without
    creating a DrawerBaseplateGroup object.
    """
    full_data = params.data()
    x_chunks, y_chunks_for_rows, grid_mm = _compute_drawer_splits_from_data(full_data)
    if x_chunks is None or y_chunks_for_rows is None or grid_mm is None:
        return Part.Shape()

    required_pieces = _build_required_pieces(x_chunks, y_chunks_for_rows)

    # Tile positioning parameters
    bed_w = float(full_data.printer.bed_width)
    bed_d = float(full_data.printer.bed_depth)
    plate_gap_x = 42.0
    plate_gap_y = 42.0
    y_chunk_count = len(y_chunks_for_rows)

    shapes: list[Part.Shape] = []

    for row_index, column_index in required_pieces.values():
        x_chunk = x_chunks[column_index]
        y_chunk = y_chunks_for_rows[row_index]

        # Build params for this chunk
        baseplate_params = _build_baseplate_params_for_chunk(params, x_chunk, y_chunk)

        # Build preview shape (simplified, no screws/clips/springs)
        shape = baseplate_builder.build_simple_baseplate_from_params_cached(
            baseplate_params.data(),
            preview=True,
        )

        # Compute placement
        width_mm = x_chunk.cells * grid_mm + x_chunk.low_fill_mm + x_chunk.high_fill_mm
        depth_mm = y_chunk.cells * grid_mm + y_chunk.low_fill_mm + y_chunk.high_fill_mm
        tile_center_x = (column_index * (bed_w + plate_gap_x)) + (0.5 * bed_w)
        tile_center_y = (y_chunk_count - 1 - row_index) * (bed_d + plate_gap_y) + 0.5 * bed_d
        placement_x = tile_center_x - (width_mm / 2)
        placement_y = tile_center_y - (depth_mm / 2)

        # Translate shape to tile position
        shape = shape.copy()
        shape.translate(fc.Vector(placement_x, placement_y, 0))
        shapes.append(shape)

    return Part.makeCompound(shapes) if shapes else Part.Shape()


def _copy_stacking_params(source: StackingParams) -> StackingParams:
    """Copy StackingParams including nested child groups."""
    result = StackingParams()
    result.set_values(source.get_values())
    return result


def _build_baseplate_params_for_chunk(
    group_params: CombinedDrawerBaseplateParams,
    x_chunk: PrintableAxisChunk,
    y_chunk: PrintableAxisChunk,
) -> CombinedBaseplateParams:
    """Build complete CombinedBaseplateParams for a specific chunk.

    Copies fundamentals, core, clicks, screws, clips, stacking from group params.
    Computes size params (grid counts + fillers) from chunk data.
    Uses factory defaults for filler widths - only overrides when filler is enabled.
    """
    size_kwargs: dict = {
        "x_grid_count": x_chunk.cells,
        "y_grid_count": y_chunk.cells,
        "filler_left_enabled": x_chunk.low_fill_mm > 0,
        "filler_right_enabled": x_chunk.high_fill_mm > 0,
        "filler_bottom_enabled": y_chunk.low_fill_mm > 0,
        "filler_top_enabled": y_chunk.high_fill_mm > 0,
        "custom_layout_enabled": False,
    }
    if x_chunk.low_fill_mm > 0:
        size_kwargs["filler_left_width"] = fc.Units.Quantity(f"{x_chunk.low_fill_mm} mm")
    if x_chunk.high_fill_mm > 0:
        size_kwargs["filler_right_width"] = fc.Units.Quantity(f"{x_chunk.high_fill_mm} mm")
    if y_chunk.low_fill_mm > 0:
        size_kwargs["filler_bottom_width"] = fc.Units.Quantity(f"{y_chunk.low_fill_mm} mm")
    if y_chunk.high_fill_mm > 0:
        size_kwargs["filler_top_width"] = fc.Units.Quantity(f"{y_chunk.high_fill_mm} mm")

    return CombinedBaseplateParams(
        baseplate_size=BaseplateSizeParams(use_factory_defaults=True, **size_kwargs),
        fundamentals=FundamentalsParams(
            grid_size=group_params.fundamentals.get_value("grid_size"),
            outer_radius=group_params.fundamentals.get_value("outer_radius"),
            main_half_width=group_params.fundamentals.get_value("main_half_width"),
            main_height=group_params.fundamentals.get_value("main_height"),
        ),
        baseplate_core=BaseplateCoreParams(
            lower_chamfer_enabled=group_params.baseplate_core.get_value("lower_chamfer_enabled"),
            lower_chamfer_size=group_params.baseplate_core.get_value("lower_chamfer_size"),
            top_crop=group_params.baseplate_core.get_value("top_crop"),
        ),
        stacking=_copy_stacking_params(group_params.stacking),
        click_springs=ClickSpringsParams(
            enabled=group_params.click_springs.get_value("enabled"),
            click_thickness=group_params.click_springs.get_value("click_thickness"),
            click_length=group_params.click_springs.get_value("click_length"),
            click_offset=group_params.click_springs.get_value("click_offset"),
        ),
        junction_screws=JunctionScrewsParams(
            enabled=group_params.junction_screws.get_value("enabled"),
            screw_diameter=group_params.junction_screws.get_value("screw_diameter"),
            counterbore_diameter=group_params.junction_screws.get_value("counterbore_diameter"),
            counterbore_depth=group_params.junction_screws.get_value("counterbore_depth"),
        ),
        connecting_clips=ConnectingClipsParams(
            enabled=group_params.connecting_clips.get_value("enabled"),
            tolerance=group_params.connecting_clips.get_value("tolerance"),
            clip_length=group_params.connecting_clips.get_value("clip_length"),
        ),
    )


class SupportBaseplate(FoundationGridfinity):
    def __init__(self, obj: fc.DocumentObject) -> None:
        super().__init__(obj)
        CombinedSupportBaseplateParams().add_all_properties_to_object(obj)

    def generate_gridfinity_shape(self, obj: fc.DocumentObject) -> Part.Shape:
        params = CombinedSupportBaseplateParams().from_obj(obj)
        data = params.data()
        return baseplate_builder.build_baseplate_support_cached(data)


class BaseplateSupport(FoundationGridfinity):
    """Support layer for stacked baseplates."""

    def __init__(self, obj: fc.DocumentObject, source_obj: fc.DocumentObject | None = None) -> None:
        super().__init__(obj)
        obj.addProperty(
            "App::PropertyLink",
            "SourceBaseplate",
            "Base",
            "Primary baseplate object linked to this support object.",
        ).SourceBaseplate = source_obj

    def generate_gridfinity_shape(self, obj: fc.DocumentObject) -> Part.Shape:
        source = getattr(obj, "SourceBaseplate", None)
        if source is None:
            return Part.Shape()
        return _build_stacked_support_shape(source)


def _stacked_support_prototype(obj: fc.DocumentObject) -> Part.Shape:
    """Build a single support layer for stacked baseplates."""
    params = CombinedBaseplateParams().from_obj(obj)
    data = params.data()
    return baseplate_builder.build_baseplate_support_cached(data)


def _build_corner_stitching_shape(
    obj: fc.DocumentObject,
    baseplates_bbox: object,  # Part.BoundBox
) -> Part.Shape | None:
    params = CombinedBaseplateParams().from_obj(obj)
    data = params.data()
    stitching_thickness = float(data.stacking.stitching_thickness)
    if not data.stacking.corner_stitching or stitching_thickness <= 0:
        return None

    outer_radius = float(data.fundamentals.outer_radius)
    if stitching_thickness >= outer_radius:
        return None
    if stitching_thickness > float(data.baseplate_core.top_crop):
        return None

    x_min = float(baseplates_bbox.XMin)
    x_max = float(baseplates_bbox.XMax)
    y_min = float(baseplates_bbox.YMin)
    y_max = float(baseplates_bbox.YMax)
    z_min = float(baseplates_bbox.ZMin)
    z_span = float(baseplates_bbox.ZMax - baseplates_bbox.ZMin)
    if z_span <= 0:
        return None

    outer_mid_scale = 0.2928932188134524
    inner_mid_offset = (outer_radius - stitching_thickness) * 0.7071067811865476

    def _point(  # noqa: PLR0913
        corner_x: float,
        corner_y: float,
        sign_x: int,
        sign_y: int,
        local_x: float,
        local_y: float,
    ) -> fc.Vector:
        return fc.Vector(corner_x + (sign_x * local_x), corner_y + (sign_y * local_y), 0)

    corner_specs = [
        (x_min, y_min, 1, 1),
        (x_max, y_min, -1, 1),
        (x_min, y_max, 1, -1),
        (x_max, y_max, -1, -1),
    ]
    corner_faces: list[Part.Face] = []
    for corner_x, corner_y, sign_x, sign_y in corner_specs:
        outer_start = _point(corner_x, corner_y, sign_x, sign_y, outer_radius, 0.0)
        outer_mid = _point(
            corner_x,
            corner_y,
            sign_x,
            sign_y,
            outer_radius * outer_mid_scale,
            outer_radius * outer_mid_scale,
        )
        outer_end = _point(corner_x, corner_y, sign_x, sign_y, 0.0, outer_radius)

        inner_start = _point(corner_x, corner_y, sign_x, sign_y, stitching_thickness, outer_radius)
        inner_mid = _point(
            corner_x,
            corner_y,
            sign_x,
            sign_y,
            outer_radius - inner_mid_offset,
            outer_radius - inner_mid_offset,
        )
        inner_end = _point(corner_x, corner_y, sign_x, sign_y, outer_radius, stitching_thickness)

        profile_edges = [
            Part.Arc(outer_start, outer_mid, outer_end).toShape(),
            Part.LineSegment(outer_end, inner_start).toShape(),
            Part.Arc(inner_start, inner_mid, inner_end).toShape(),
            Part.LineSegment(inner_end, outer_start).toShape(),
        ]
        corner_faces.append(Part.Face(Part.Wire(profile_edges)))

    stitching_profiles = Part.makeCompound(corner_faces)
    stitching_shape = stitching_profiles.extrude(fc.Vector(0, 0, z_span))
    stitching_shape.translate(fc.Vector(0, 0, z_min))
    return stitching_shape


def _build_stacked_baseplates_core_shape(obj: fc.DocumentObject) -> Part.Shape:
    # Build a single baseplate using params
    params = CombinedBaseplateParams().from_obj(obj)
    data = params.data()
    baseplate_shape = baseplate_builder.build_simple_baseplate_from_params(data, preview=False)
    support_shape = _stacked_support_prototype(obj)
    instance_count = max(1, data.stacking.instance_count)
    z_step = support_shape.BoundBox.ZMax

    shapes = []
    for idx in range(instance_count):
        shape = baseplate_shape.copy()
        if idx:
            shape.translate(fc.Vector(0, 0, idx * z_step))
        shapes.append(shape)
    if len(shapes) == 1:
        return shapes[0]
    return shapes[0].multiFuse(shapes[1:])


def _build_stacked_baseplates_shape(obj: fc.DocumentObject) -> Part.Shape:
    stacked_baseplates = _build_stacked_baseplates_core_shape(obj)
    stitching_shape = _build_corner_stitching_shape(obj, stacked_baseplates.BoundBox)
    if stitching_shape is None:
        return stacked_baseplates
    return stacked_baseplates.fuse(stitching_shape)


def _build_stacked_support_shape(obj: fc.DocumentObject) -> Part.Shape:
    params = CombinedBaseplateParams().from_obj(obj)
    data = params.data()
    support_shape = _stacked_support_prototype(obj)
    instance_count = max(1, data.stacking.instance_count)
    support_count = max(1, instance_count - 1)
    if support_count == 0:
        return Part.Shape()

    z_step = support_shape.BoundBox.ZMax
    shapes = []
    for idx in range(support_count):
        shape = support_shape.copy()
        if idx:
            shape.translate(fc.Vector(0, 0, idx * z_step))
        shapes.append(shape)
    stacked_supports = shapes[0] if len(shapes) == 1 else shapes[0].multiFuse(shapes[1:])

    baseplates_bbox = _build_stacked_baseplates_core_shape(obj).BoundBox
    stitching_shape = _build_corner_stitching_shape(obj, baseplates_bbox)
    if stitching_shape is None:
        return stacked_supports
    return stacked_supports.cut(stitching_shape)


class CustomBlankBin(FoundationGridfinity):
    """Gridfinity CustomBlankBin object."""

    def __init__(self, obj: fc.DocumentObject, layout: list[list[bool]]) -> None:
        super().__init__(obj)
        self.layout = layout

        grid_initial_layout.custom_shape_layout_properties(obj, baseplate_default=False)
        feat.bin_solid_mid_section_properties(
            obj,
            default_height_units=const.HEIGHT_UNITS,
            default_wall_thickness=const.WALL_THICKNESS,
        )
        feat.blank_bin_recessed_top_properties(obj)
        feat.stacking_lip_properties(obj, stacking_lip_default=const.STACKING_LIP)
        feat.bin_bottom_holes_properties(obj, magnet_holes_default=const.MAGNET_HOLES)
        feat.bin_base_values_properties(obj)

        obj.Proxy = self

    def generate_gridfinity_shape(self, obj: fc.DocumentObject) -> Part.Shape:
        """Generate BinBlank Shape."""
        ## calculated here

        obj.BaseProfileHeight = (
            obj.BaseProfileLowerChamferSize
            + obj.BaseProfileMainHeight
            + obj.BaseProfileMainHalfWidth
        )

        obj.StackingLipTopChamfer = (
            obj.BaseProfileMainHalfWidth - obj.Clearance - obj.StackingLipTopLedge
        )
        ## calculated values over
        layout = clean_up_layout(self.layout)
        grid_initial_layout.make_custom_shape_layout(obj, layout)
        solid_shape = custom_shape_solid(obj, layout, obj.TotalHeight - obj.BaseProfileHeight)
        outside_trim = custom_shape_trim(obj, layout, obj.Clearance, obj.Clearance)
        fuse_total = solid_shape.cut(outside_trim)
        fuse_total = fuse_total.removeSplitter()
        fuse_total = vertical_edge_fillet(fuse_total, obj.BinOuterRadius)
        fuse_total = fuse_total.fuse(feat.make_complex_bin_base(obj, layout))

        if obj.RecessedTopDepth > 0:
            recessed_solid = custom_shape_solid(obj, layout, obj.RecessedTopDepth)
            recessed_outside_trim = custom_shape_trim(
                obj,
                layout,
                obj.Clearance.Value + obj.WallThickness.Value,
                obj.Clearance.Value + obj.WallThickness.Value,
            )
            recessed_solid = recessed_solid.cut(recessed_outside_trim)
            recessed_solid = recessed_solid.removeSplitter()
            recessed_solid = vertical_edge_fillet(
                recessed_solid,
                obj.BinOuterRadius - obj.WallThickness,
            )
            fuse_total = fuse_total.cut(recessed_solid)
        if obj.ScrewHoles or obj.MagnetHoles:
            holes = feat.make_bin_bottom_holes(obj, layout)
            fuse_total = Part.Shape.cut(fuse_total, holes)
        if obj.StackingLip:
            fuse_total = fuse_total.fuse(
                custom_shape_stacking_lip(obj, solid_shape, layout),
            )

        return fuse_total

    def dumps(self) -> dict:
        """Needed for JSON Serialization when saving a file containing gridfinity object."""
        return {"layout": self.layout}

    def loads(self, state: dict) -> None:
        """Needed for JSON Serialization when opening a file containing gridfinity object."""
        self.layout = state["layout"]


class CustomBinBase(FoundationGridfinity):
    """Gridfinity CustomBinBase object."""

    def __init__(self, obj: fc.DocumentObject, layout: list[list[bool]]) -> None:
        super().__init__(obj)
        self.layout = layout

        grid_initial_layout.custom_shape_layout_properties(obj, baseplate_default=False)
        feat.bin_solid_mid_section_properties(
            obj,
            default_height_units=1,
            default_wall_thickness=const.WALL_THICKNESS,
        )
        feat.blank_bin_recessed_top_properties(obj)
        feat.stacking_lip_properties(obj, stacking_lip_default=False)
        feat.bin_bottom_holes_properties(obj, magnet_holes_default=const.MAGNET_HOLES)
        feat.bin_base_values_properties(obj)

        obj.Proxy = self

    def generate_gridfinity_shape(self, obj: fc.DocumentObject) -> Part.Shape:
        """Generate BinBase Shape."""
        ## calculated here
        obj.BaseProfileHeight = (
            obj.BaseProfileLowerChamferSize
            + obj.BaseProfileMainHeight
            + obj.BaseProfileMainHalfWidth
        )

        obj.StackingLipTopChamfer = (
            obj.BaseProfileMainHalfWidth - obj.Clearance - obj.StackingLipTopLedge
        )
        ## calculated values over
        layout = clean_up_layout(self.layout)
        grid_initial_layout.make_custom_shape_layout(obj, layout)
        solid_shape = custom_shape_solid(obj, layout, obj.TotalHeight - obj.BaseProfileHeight)
        outside_trim = custom_shape_trim(obj, layout, obj.Clearance, obj.Clearance)
        fuse_total = solid_shape.cut(outside_trim)
        fuse_total = fuse_total.removeSplitter()
        fuse_total = vertical_edge_fillet(fuse_total, obj.BinOuterRadius)
        fuse_total = fuse_total.fuse(feat.make_complex_bin_base(obj, layout))

        if obj.RecessedTopDepth > 0:
            recessed_solid = custom_shape_solid(obj, layout, obj.RecessedTopDepth)
            recessed_outside_trim = custom_shape_trim(
                obj,
                layout,
                obj.Clearance.Value + obj.WallThickness.Value,
                obj.Clearance.Value + obj.WallThickness.Value,
            )
            recessed_solid = recessed_solid.cut(recessed_outside_trim)
            recessed_solid = recessed_solid.removeSplitter()
            recessed_solid = vertical_edge_fillet(
                recessed_solid,
                obj.BinOuterRadius - obj.WallThickness,
            )
            fuse_total = fuse_total.cut(recessed_solid)
        if obj.ScrewHoles or obj.MagnetHoles:
            holes = feat.make_bin_bottom_holes(obj, layout)
            fuse_total = Part.Shape.cut(fuse_total, holes)
        if obj.StackingLip:
            fuse_total = fuse_total.fuse(
                custom_shape_stacking_lip(obj, solid_shape, layout),
            )

        return fuse_total

    def dumps(self) -> dict:
        """Needed for JSON Serialization when saving a file containing gridfinity object."""
        return {"layout": self.layout}

    def loads(self, state: dict) -> None:
        """Needed for JSON Serialization when opening a file containing gridfinity object."""
        self.layout = state["layout"]


class CustomEcoBin(FoundationGridfinity):
    """Gridfinity CustomEcoBin object."""

    def __init__(self, obj: fc.DocumentObject, layout: list[list[bool]]) -> None:
        super().__init__(obj)
        self.layout = layout

        grid_initial_layout.custom_shape_layout_properties(obj, baseplate_default=False)
        feat.bin_solid_mid_section_properties(
            obj,
            default_height_units=const.HEIGHT_UNITS,
            default_wall_thickness=const.WALL_THICKNESS,
        )
        feat.stacking_lip_properties(obj, stacking_lip_default=const.STACKING_LIP)
        feat.bin_bottom_holes_properties(obj, magnet_holes_default=False)
        feat.bin_base_values_properties(obj)
        feat.label_shelf_properties(obj, label_style_default="Off")
        feat.eco_compartments_properties(obj)
        feat.scoop_properties(obj, scoop_default=False)

        obj.Proxy = self

    def generate_gridfinity_shape(self, obj: fc.DocumentObject) -> Part.Shape:
        """Generate EcoBin Shape."""
        ## calculated here

        obj.BaseProfileHeight = (
            obj.BaseProfileLowerChamferSize
            + obj.BaseProfileMainHeight
            + obj.BaseProfileMainHalfWidth
        )

        obj.StackingLipTopChamfer = (
            obj.BaseProfileMainHalfWidth - obj.Clearance - obj.StackingLipTopLedge
        )
        ## calculated values over
        layout = clean_up_layout(self.layout)
        grid_initial_layout.make_custom_shape_layout(obj, layout)
        solid_shape = custom_shape_solid(obj, layout, obj.TotalHeight - obj.BaseProfileHeight)
        outside_trim = custom_shape_trim(obj, layout, obj.Clearance, obj.Clearance)
        fuse_total = solid_shape.cut(outside_trim)
        fuse_total = fuse_total.removeSplitter()
        fuse_total = vertical_edge_fillet(fuse_total, obj.BinOuterRadius)
        fuse_total = fuse_total.fuse(feat.make_complex_bin_base(obj, layout))

        feat.eco_error_check(obj)
        compartments_solid = custom_shape_solid(
            obj,
            layout,
            obj.TotalHeight - obj.BaseProfileHeight - obj.BaseWallThickness,
        )
        compartment_trim = custom_shape_trim(
            obj,
            layout,
            obj.Clearance + obj.WallThickness,
            obj.Clearance + obj.WallThickness,
        )
        compartments_solid = compartments_solid.cut(compartment_trim)
        compartments_solid = compartments_solid.removeSplitter()
        compartments_solid = vertical_edge_fillet(
            compartments_solid,
            obj.BinOuterRadius - obj.WallThickness,
        )
        inside_wall_solid_full_height = custom_shape_solid(
            obj,
            layout,
            obj.TotalHeight,
        )
        inside_wall_solid_full_height = inside_wall_solid_full_height.cut(compartment_trim)
        inside_wall_solid_full_height = inside_wall_solid_full_height.removeSplitter()
        inside_wall_solid_full_height = vertical_edge_fillet(
            inside_wall_solid_full_height,
            obj.BinOuterRadius - obj.WallThickness,
        )
        # First cut eco compartments to create the interior spaces
        compartments = feat.make_eco_compartments(obj, layout, compartments_solid)
        inside_wall_negative = cut_outside_shape(obj, inside_wall_solid_full_height)
        compartments = compartments.cut(inside_wall_negative)
        fuse_total = fuse_total.cut(compartments)

        # Now add scoop, but only where eco compartments exist (reversed logic)
        if obj.Scoop:
            scoop = feat.make_scoop(obj, usable_height=obj.TotalHeight - obj.BaseWallThickness)
            # Only add scoop where compartments exist - use intersection to constrain
            scoop_constrained = scoop.common(compartments)
            fuse_total = fuse_total.fuse(scoop_constrained)

        if obj.LabelShelfStyle != "Off":
            label_shelf = feat.make_label_shelf(obj, "eco")
            label_shelf = label_shelf.cut(inside_wall_negative)
            fuse_total = fuse_total.fuse(label_shelf)

        if obj.ScrewHoles or obj.MagnetHoles:
            holes = self.bin_bottom_holes.make(obj, layout)
            fuse_total = Part.Shape.cut(fuse_total, holes)
        if obj.StackingLip:
            fuse_total = fuse_total.fuse(
                custom_shape_stacking_lip(obj, solid_shape, layout),
            )

        return fuse_total.removeSplitter()

    def dumps(self) -> dict:
        """Needed for JSON Serialization when saving a file containing gridfinity object."""
        return {"layout": self.layout}

    def loads(self, state: dict) -> None:
        """Needed for JSON Serialization when opening a file containing gridfinity object."""
        self.layout = state["layout"]


class CustomStorageBin(FoundationGridfinity):
    """Gridfinity CustomStorageBin object."""

    def __init__(self, obj: fc.DocumentObject, layout: list[list[bool]]) -> None:
        super().__init__(obj)
        self.layout = layout

        grid_initial_layout.custom_shape_layout_properties(obj, baseplate_default=False)
        feat.bin_solid_mid_section_properties(
            obj,
            default_height_units=const.HEIGHT_UNITS,
            default_wall_thickness=const.WALL_THICKNESS,
        )
        feat.stacking_lip_properties(obj, stacking_lip_default=const.STACKING_LIP)
        feat.bin_bottom_holes_properties(obj, magnet_holes_default=const.MAGNET_HOLES)
        feat.bin_base_values_properties(obj)
        feat.compartments_properties(obj, x_div_default=0, y_div_default=0)
        feat.label_shelf_properties(obj, label_style_default="Off")
        feat.scoop_properties(obj, scoop_default=False)

        obj.setExpression("UsableHeight", "TotalHeight - HeightUnitValue")

        obj.Proxy = self

    def generate_gridfinity_shape(self, obj: fc.DocumentObject) -> Part.Shape:
        """Generate StorageBin Shape."""
        ## calculated here
        if obj.NonStandardHeight:
            obj.TotalHeight = obj.CustomHeight

        else:
            obj.TotalHeight = obj.HeightUnits * obj.HeightUnitValue

        obj.BaseProfileHeight = (
            obj.BaseProfileLowerChamferSize
            + obj.BaseProfileMainHeight
            + obj.BaseProfileMainHalfWidth
        )

        obj.StackingLipTopChamfer = (
            obj.BaseProfileMainHalfWidth - obj.Clearance - obj.StackingLipTopLedge
        )

        ## calculated values over
        layout = clean_up_layout(self.layout)
        grid_initial_layout.make_custom_shape_layout(obj, layout)
        solid_shape = custom_shape_solid(obj, layout, obj.TotalHeight - obj.BaseProfileHeight)
        outside_trim = custom_shape_trim(obj, layout, obj.Clearance, obj.Clearance)
        fuse_total = solid_shape.cut(outside_trim)
        fuse_total = fuse_total.removeSplitter()
        fuse_total = vertical_edge_fillet(fuse_total, obj.BinOuterRadius)
        fuse_total = fuse_total.fuse(feat.make_complex_bin_base(obj, layout))

        compartments_solid = custom_shape_solid(obj, layout, obj.UsableHeight)
        compartment_trim = custom_shape_trim(
            obj,
            layout,
            obj.Clearance + obj.WallThickness,
            obj.Clearance + obj.WallThickness,
        )
        compartments_solid = compartments_solid.cut(compartment_trim)
        compartments_solid = compartments_solid.removeSplitter()
        compartments_solid = vertical_edge_fillet_with_concave_edges(
            compartments_solid,
            obj.BinOuterRadius - obj.WallThickness,
            obj.BinOuterRadius + obj.WallThickness,
        )
        compartments = feat.make_compartments(obj, compartments_solid)

        fuse_total = fuse_total.cut(compartments)

        if obj.ScrewHoles or obj.MagnetHoles:
            holes = feat.make_bin_bottom_holes(obj, layout)
            fuse_total = Part.Shape.cut(fuse_total, holes)
        if obj.StackingLip:
            fuse_total = fuse_total.fuse(
                custom_shape_stacking_lip(obj, solid_shape, layout),
            )
        outside_bin_solid = cut_outside_shape(obj, compartments_solid)

        if obj.LabelShelfStyle != "Off":
            label_shelf = feat.make_label_shelf(obj, "standard")
            label_shelf = label_shelf.cut(outside_bin_solid)
            fuse_total = fuse_total.fuse(label_shelf)

        if obj.Scoop:
            scoop = feat.make_scoop(obj)
            scoop = scoop.cut(outside_bin_solid)
            fuse_total = fuse_total.fuse(scoop)

        return fuse_total.removeSplitter()

    def dumps(self) -> dict:
        """Needed for JSON Serialization when saving a file containing gridfinity object."""
        return {"layout": self.layout}

    def loads(self, state: dict) -> None:
        """Needed for JSON Serialization when opening a file containing gridfinity object."""
        self.layout = state["layout"]


class StandaloneLabelShelf:
    def __init__(
        self,
        obj: fc.DocumentObject,
        target_obj: fc.DocumentObject,
        face: Part.Face,
    ) -> None:
        obj.addProperty(
            "App::PropertyString",
            "version",
            "version",
            "Gridfinity Workbench Version",
        ).version = __version__

        obj.addProperty(
            "App::PropertyLength",
            "Width",
            "GridfinityNonStandard",
            "Width of the Label Shelf, how far it sticks out from the wall"
            " <br> <br> default = 12 mm",
        ).Width = const.LABEL_SHELF_WIDTH
        obj.addProperty(
            "App::PropertyLength",
            "Length",
            "GridfinityNonStandard",
            "Length of the Label Shelf, how long it is <br> <br> default = 42 mm",
        ).Length = const.LABEL_SHELF_LENGTH
        obj.addProperty(
            "App::PropertyAngle",
            "Angle",
            "GridfinityNonStandard",
            "Angle of the bottom part of the Label Shelf <br> <br> default = 45",
        ).Angle = const.LABEL_SHELF_ANGLE
        obj.addProperty(
            "App::PropertyLength",
            "LabelShelfVerticalThickness",
            "zzExpertOnly",
            "Vertical Thickness of the Label Shelf <br> <br> default = 2 mm",
        ).LabelShelfVerticalThickness = const.LABEL_SHELF_VERTICAL_THICKNESS

        obj.addProperty(
            "App::PropertyLink",
            "Attachment",
            "Base",
            "Object this label shelf is attached to.",
        ).Attachment = target_obj

        normal = face.normalAt(*face.Surface.parameter(face.CenterOfMass))
        rotation = fc.Rotation(fc.Vector(1, 0, 0), normal)

        points = [v.Point for v in face.Vertexes]
        height = max([p.z for p in points])
        [p1, p2] = [p for p in points if p.z > height - 1e-4]
        translation = (p1 + p2) / 2  # type: ignore[operator]

        placement = fc.Placement(translation, rotation)

        obj.Placement = placement
        obj.setExpression(
            "Placement.Base.z",
            "Attachment.StackingLip == 1 ? -Attachment.LabelShelfStackingOffset : 0mm",
        )

        obj.Proxy = self

    def execute(self, obj: Part.Feature) -> None:
        width = obj.Width
        stacking_lip_offset = feat.calc_stacking_lip_offset(obj.Attachment)
        # Check if the shelf is covered by a stacking lip
        check_point = obj.Placement.Base + obj.Placement.Rotation.multVec(
            fc.Vector(stacking_lip_offset / 2),
        )
        if obj.Attachment.StackingLip and obj.Attachment.Shape.isInside(check_point, 1e-6, False):  # noqa: FBT003
            width += stacking_lip_offset

        shape = label_shelf.from_angle(
            length=obj.Length,
            width=width,
            thickness=obj.LabelShelfVerticalThickness,
            angle=obj.Angle,
            center=True,
        )

        obj.Shape = shape

    def dumps(self) -> None:
        return

    def loads(self, state: tuple) -> None:  # noqa: ARG002
        return


class ConnectingClip(FoundationGridfinity):
    def __init__(self, obj: fc.DocumentObject, params: CombinedConnectingClipsParams) -> None:
        super().__init__(obj)

        # Use the generic parameter-driven property addition
        params.add_all_properties_to_object(obj)

    def generate_gridfinity_shape(self, obj: fc.DocumentObject) -> Part.Shape:
        params = CombinedConnectingClipsParams().from_obj(obj)
        return clip_profiles.build_connecting_clip_shape(params.data())
