"""Build pipeline for simple baseplate geometry."""

from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from dataclasses import dataclass, is_dataclass
from dataclasses import fields as dataclass_fields
from typing import TYPE_CHECKING

import FreeCAD as fc  # noqa: N813
import Part

from . import baseplate_cell_cache, baseplate_corner_roundover, baseplate_full_layout, utils
from . import baseplate_click_springs as click_springs
from . import baseplate_feature_construction as baseplate_feat
from . import feature_construction as feat

if TYPE_CHECKING:
    from collections.abc import Callable

    from .baseplate_full_layout import GridfinityLayout, GridfinityLayoutGeometry
    from .param import CombinedBaseplateParamsData, CombinedSupportBaseplateParamsData


def _timing_enabled() -> bool:
    return os.environ.get("GRIDFINITY_DEBUG_TIMING", "").lower() in {"1", "true", "yes", "on"}


def _timing_print(label: str, seconds: float) -> None:
    fc.Console.PrintMessage(f"[Gridfinity Timing] {label}: {seconds:.4f}s\n")


_BASEPLATE_SHAPE_CACHE_MAX = 32
_BASEPLATE_SHAPE_CACHE: OrderedDict[str, Part.Shape] = OrderedDict()


def set_baseplate_shape_cache_max_entries(max_entries: int) -> None:
    """Configure the maximum number of baseplate shapes to cache."""
    global _BASEPLATE_SHAPE_CACHE_MAX  # noqa: PLW0603
    _BASEPLATE_SHAPE_CACHE_MAX = max(0, int(max_entries))
    if _BASEPLATE_SHAPE_CACHE_MAX == 0:
        _BASEPLATE_SHAPE_CACHE.clear()
        return
    while len(_BASEPLATE_SHAPE_CACHE) > _BASEPLATE_SHAPE_CACHE_MAX:
        _BASEPLATE_SHAPE_CACHE.popitem(last=False)


def set_cell_shape_cache_max_entries(max_entries: int) -> None:
    """Configure the maximum number of cell shapes to cache."""
    baseplate_cell_cache.set_cell_cache_max_entries(max_entries)


def _cache_normalize(value: object) -> object:  # noqa: PLR0911
    if is_dataclass(value):
        return {
            field.name: _cache_normalize(getattr(value, field.name))
            for field in dataclass_fields(value)
        }
    if isinstance(value, dict):
        return {str(k): _cache_normalize(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_cache_normalize(v) for v in value]
    if isinstance(value, bool | int | str) or value is None:
        return value
    if isinstance(value, float):
        return round(value, 2)
    if hasattr(value, "Value"):
        try:
            return round(float(value), 2)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            return str(value)
    return str(value)


def _baseplate_cache_key(
    params: CombinedBaseplateParamsData,
    *,
    preview: bool,
) -> str:
    # Layout is derived from params, so params alone determines layout
    payload = {
        "kind": "simple_baseplate",
        "params": _cache_normalize(params),
        "preview": bool(preview),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _shape_cache_get_or_build(key: str, build_fn: Callable[[], Part.Shape]) -> Part.Shape:
    if _BASEPLATE_SHAPE_CACHE_MAX <= 0:
        return build_fn()

    cached_shape = _BASEPLATE_SHAPE_CACHE.get(key)
    if cached_shape is not None:
        _BASEPLATE_SHAPE_CACHE.move_to_end(key)
        return cached_shape.copy()

    shape = build_fn()
    _BASEPLATE_SHAPE_CACHE[key] = shape
    _BASEPLATE_SHAPE_CACHE.move_to_end(key)
    while len(_BASEPLATE_SHAPE_CACHE) > _BASEPLATE_SHAPE_CACHE_MAX:
        _BASEPLATE_SHAPE_CACHE.popitem(last=False)
    return shape.copy()


def build_baseplate_support_cached(
    params: CombinedBaseplateParamsData | CombinedSupportBaseplateParamsData,
) -> Part.Shape:
    """Build baseplate top support with caching."""
    layout = _derive_layout_from_params(params)
    # Create cache key from params data
    params_payload = _cache_normalize(params)
    key = json.dumps(
        {
            "kind": "support_baseplate",
            "params": params_payload,
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    def _build() -> Part.Shape:
        shape = feat.make_baseplate_top_support(params, layout)
        z_start = (
            float(params.fundamentals.main_height)
            + float(params.fundamentals.main_half_width)
            - float(params.baseplate_core.top_crop)
        )
        z_matrix = fc.Matrix()
        z_matrix.move(fc.Vector(0, 0, z_start))
        try:
            return shape.transformGeometry(z_matrix)
        except Exception:  # noqa: BLE001
            shifted_shape = shape.copy()
            try:
                shifted_shape.transformShape(z_matrix, copy=False)  # type: ignore[call-arg]
            except TypeError:
                shifted_shape.transformShape(z_matrix, False)  # noqa: FBT003
            return shifted_shape

    return _shape_cache_get_or_build(key, _build)


def _layout_min_indices(layout: GridfinityLayout) -> tuple[int, int]:
    """Find minimum x and y indices that have True cells in the layout."""
    min_x = None
    min_y = None
    for x, col in enumerate(layout):
        for y, cell in enumerate(col):
            if cell:
                if min_x is None or x < min_x:
                    min_x = x
                if min_y is None or y < min_y:
                    min_y = y
    return (min_x or 0, min_y or 0)


@dataclass
class CoreCellBuildResult:
    """Result of building a single core cell."""

    shape: Part.Shape
    is_tiny: bool


def _create_rectangle_wire(x_width: float, y_width: float, z: float = 0) -> Part.Wire:
    x_half = x_width / 2
    y_half = y_width / 2
    points = [
        fc.Vector(-x_half, -y_half, z),
        fc.Vector(x_half, -y_half, z),
        fc.Vector(x_half, y_half, z),
        fc.Vector(-x_half, y_half, z),
        fc.Vector(-x_half, -y_half, z),
    ]
    return Part.Wire(Part.makePolygon(points))


def _make_centered_box(
    x_size: float,
    y_size: float,
    z_size: float,
    *,
    z_min: float = 0.0,
) -> Part.Shape:
    return utils.make_centered_box(x_size, y_size, z_size, z_min=z_min)


def _base_apex_height(params: CombinedBaseplateParamsData) -> fc.Units.Quantity:
    return params.fundamentals.main_height + params.fundamentals.main_half_width


def compute_stacking_z_step(data: CombinedBaseplateParamsData) -> float:
    """Compute vertical spacing between stacked baseplates from params.

    This computes the z-offset for stacking without building the full support shape.
    The z_step equals the top of the support layer (z_start + loft_height).
    """
    import math

    main_half_width = float(data.fundamentals.main_half_width)
    top_crop = float(data.baseplate_core.top_crop)
    click_offset = float(data.click_springs.click_offset)
    overhang_angle = float(data.stacking.support.overhang_angle)

    # Run is the horizontal distance the support spans
    run = main_half_width + click_offset - top_crop
    if run <= 0:
        msg = "Invalid support geometry: main_half_width + click_offset must be > top_crop"
        raise ValueError(msg)

    # Loft height from overhang angle
    loft_height = run / math.tan(math.radians(overhang_angle))

    # z_start is where support begins (top of baseplate)
    z_start = float(data.fundamentals.main_height) + main_half_width - top_crop

    return z_start + loft_height


def baseplate_cell_top_crop(
    shape: Part.Shape,
    params: CombinedBaseplateParamsData,
    *,
    x_size_override: float | None = None,
    y_size_override: float | None = None,
) -> Part.Shape:
    """Crop the top of a baseplate cell shape."""
    top_crop = params.baseplate_core.top_crop
    half_width = params.fundamentals.main_half_width
    if top_crop >= half_width:
        raise ValueError(
            f"BaseProfileTopCrop ({top_crop}) must be smaller than "
            f"BaseProfileMainHalfWidth ({half_width})",
        )

    grid_size = float(params.fundamentals.grid_size)
    x_size = x_size_override if x_size_override is not None else grid_size
    y_size = y_size_override if y_size_override is not None else grid_size

    apex = _base_apex_height(params)
    margin = 0.1 * fc.Units.Quantity("1 mm")
    crop_slab = _make_centered_box(
        x_size + float(margin),
        y_size + float(margin),
        float(top_crop + margin),
        z_min=float(apex - top_crop),
    )
    return shape.cut(crop_slab)


def build_single_cell_baseplate_core(
    params: CombinedBaseplateParamsData,
    *,
    preview: bool = False,
    x_size_override: float | None = None,
    y_size_override: float | None = None,
) -> CoreCellBuildResult:
    """Build a single core cell for a baseplate.

    Args:
        params: Combined baseplate parameters with fundamentals.grid_size as standard size.
        preview: If True, build simplified geometry for preview.
        x_size_override: Optional override for cell X dimension (for filler cells).
        y_size_override: Optional override for cell Y dimension (for filler cells).

    """
    grid_size = float(params.fundamentals.grid_size)
    x_size = x_size_override if x_size_override is not None else grid_size
    y_size = y_size_override if y_size_override is not None else grid_size
    tiny = feat.is_tiny_cell(params.fundamentals, params.baseplate_core, x_size, y_size)

    if preview:
        main_height = float(params.fundamentals.main_height)
        main_half_width = float(params.fundamentals.main_half_width)
        margin = 0.1
        outer = _make_centered_box(x_size, y_size, main_height)
        if tiny:
            return CoreCellBuildResult(shape=outer, is_tiny=True)
        inner = _make_centered_box(
            x_size - main_half_width,
            y_size - main_half_width,
            main_height + (2 * margin),
            z_min=-margin,
        )
        return CoreCellBuildResult(shape=outer.cut(inner), is_tiny=False)

    baseplate_outside_shape = _create_rectangle_wire(x_size, y_size)
    total_height = _base_apex_height(params)
    face = Part.Face(baseplate_outside_shape)
    solid_shape = face.extrude(fc.Vector(0, 0, total_height))
    bin_base_shape = feat.make_complex_bin_base_single_from_params(
        params.fundamentals,
        params.baseplate_core,
        x_size_override=x_size_override,
        y_size_override=y_size_override,
    )
    if tiny:
        return CoreCellBuildResult(shape=solid_shape, is_tiny=True)
    bin_base_shape.translate(fc.Vector(0, 0, total_height))
    return CoreCellBuildResult(shape=solid_shape.cut(bin_base_shape), is_tiny=False)


def build_single_cell_baseplate_core_cached(
    params: CombinedBaseplateParamsData,
    *,
    preview: bool = False,
    x_size_override: float | None = None,
    y_size_override: float | None = None,
) -> CoreCellBuildResult:
    """Build a single core cell for a baseplate with caching."""
    key = baseplate_cell_cache.make_key(
        {
            "kind": "baseplate_core_cell",
            "params": params,
            "preview": preview,
            "x_size_override": x_size_override,
            "y_size_override": y_size_override,
        },
    )

    def _build() -> Part.Shape:
        return build_single_cell_baseplate_core(
            params,
            preview=preview,
            x_size_override=x_size_override,
            y_size_override=y_size_override,
        ).shape

    shape = baseplate_cell_cache.get_or_build(key, _build)
    grid_size = float(params.fundamentals.grid_size)
    x_size = x_size_override if x_size_override is not None else grid_size
    y_size = y_size_override if y_size_override is not None else grid_size
    tiny_cell = feat.is_tiny_cell(params.fundamentals, params.baseplate_core, x_size, y_size)
    return CoreCellBuildResult(shape=shape, is_tiny=tiny_cell)


def build_complete_cell_cached(
    params: CombinedBaseplateParamsData,
    cell_meta: baseplate_full_layout.FullLayoutCell,
    *,
    preview: bool = False,
) -> CoreCellBuildResult:
    """Build a complete baseplate cell with springs and top crop, using cache.

    The cache key includes cell size, spring mask, shift values, and click_springs.enabled,
    so cells with identical parameters share cached shapes.
    """
    grid_size = float(params.fundamentals.grid_size)
    width = cell_meta.width
    height = cell_meta.height
    x_override = width if width != grid_size else None
    y_override = height if height != grid_size else None
    mask = cell_meta.get_mask()
    shift_x = cell_meta.spring_shift_x if cell_meta.kind == "Filler" else 0.0
    shift_y = cell_meta.spring_shift_y if cell_meta.kind == "Filler" else 0.0

    key = baseplate_cell_cache.make_key(
        {
            "kind": "baseplate_complete_cell",
            "params": params,
            "preview": preview,
            "width": width,
            "height": height,
            "mask": mask,
            "click_springs_enabled": params.click_springs.enabled,
            "shift_x": shift_x,
            "shift_y": shift_y,
        },
    )

    def _build() -> Part.Shape:
        # Build base cell shape
        core_result = build_single_cell_baseplate_core(
            params,
            preview=preview,
            x_size_override=x_override,
            y_size_override=y_override,
        )
        cell = core_result.shape

        if preview:
            return cell  # Preview: no springs, no top crop

        # Apply springs only for non-tiny cells
        if not core_result.is_tiny and params.click_springs.enabled and mask is not None:
            negative_slots = click_springs.make_click_spring_prototype_negative(
                params.fundamentals,
                params.click_springs,
            )
            positive_slots = click_springs.make_click_spring_prototype_positive(
                params.fundamentals,
                params.click_springs,
            )
            # Apply alignment shift for filler cells
            if shift_x != 0.0 or shift_y != 0.0:
                cell.translate(fc.Vector(shift_x, shift_y, 0))
            cell = click_springs.apply_click_spring_slots_to_cell(
                cell,
                params.fundamentals,
                params.baseplate_core,
                params.click_springs,
                negative_slots,
                positive_slots,
                mask,
            )
            if shift_x != 0.0 or shift_y != 0.0:
                cell.translate(fc.Vector(-shift_x, -shift_y, 0))

        # Apply top crop
        cell = baseplate_cell_top_crop(
            cell,
            params,
            x_size_override=x_override,
            y_size_override=y_override,
        )
        return cell

    shape = baseplate_cell_cache.get_or_build(key, _build)
    tiny_cell = feat.is_tiny_cell(params.fundamentals, params.baseplate_core, width, height)
    return CoreCellBuildResult(shape=shape, is_tiny=tiny_cell)


def build_cells_from_geometry(
    params: CombinedBaseplateParamsData,
    geometry: baseplate_full_layout.GridfinityLayoutGeometry,
    *,
    preview: bool = False,
) -> Part.Shape:
    """Build all cells from geometry, placing each at its position.

    Uses build_complete_cell_cached for each cell, which handles springs with masks.
    """
    nx, ny = geometry.size()
    pieces: list[Part.Shape] = []

    for ix in range(nx):
        for iy in range(ny):
            cell_meta = geometry.cells[ix][iy]
            if not cell_meta.exists:
                continue

            cell_result = build_complete_cell_cached(params, cell_meta, preview=preview)
            cell_shape = cell_result.shape.copy()

            # Translate cell to its position
            center_x, center_y = geometry.cell_center(ix, iy)
            cell_shape.translate(fc.Vector(center_x, center_y, 0))
            pieces.append(cell_shape)

    if not pieces:
        return Part.Shape()
    if len(pieces) == 1:
        return pieces[0]
    return utils.multi_fuse(pieces)


def _apply_layout_corner_roundover(
    shape: Part.Shape,
    params: CombinedBaseplateParamsData,
    geometry: GridfinityLayoutGeometry,
) -> Part.Shape:
    apex = float(
        params.fundamentals.main_height + params.fundamentals.main_half_width,
    )
    top_crop = float(params.baseplate_core.top_crop)
    roundover_height = apex - top_crop
    return baseplate_corner_roundover.apply_layout_corner_roundover(
        shape,
        geometry=geometry,
        outside_radius=float(params.fundamentals.outer_radius),
        height=roundover_height,
    )


def make_post_replication_cutter(
    params: CombinedBaseplateParamsData,
    geometry: GridfinityLayoutGeometry,
    top_z: fc.Units.Quantity,
) -> Part.Shape | None:
    """Build a cutter shape for post-replication features."""
    cutters: list[Part.Shape] = []

    if params.junction_screws.enabled:
        junction_holes = baseplate_feat.make_junction_screw_holes_from_params(
            params.fundamentals,
            params.junction_screws,
            top_z,
            geometry=geometry,
        )
        if junction_holes is not None:
            cutters.append(junction_holes)

    if params.connecting_clips.enabled:
        connecting_clip_cutouts = baseplate_feat.make_clip_cutouts_from_params(
            params.fundamentals,
            params.connecting_clips,
            geometry=geometry,
        )
        if connecting_clip_cutouts is not None:
            cutters.append(connecting_clip_cutouts)

    if not cutters:
        return None
    return cutters[0].multiFuse(cutters[1:]) if len(cutters) > 1 else cutters[0]


def build_single_baseplate_from_params_cached(
    params: CombinedBaseplateParamsData,
    *,
    preview: bool = False,
) -> Part.Shape:
    """Build a simple baseplate from params with caching."""
    if _BASEPLATE_SHAPE_CACHE_MAX <= 0:
        return build_single_baseplate_from_params(params, preview=preview)

    key = _baseplate_cache_key(params, preview=preview)
    cached_shape = _BASEPLATE_SHAPE_CACHE.get(key)
    if cached_shape is not None:
        _BASEPLATE_SHAPE_CACHE.move_to_end(key)
        return cached_shape.copy()
    shape = build_single_baseplate_from_params(params, preview=preview)
    _BASEPLATE_SHAPE_CACHE[key] = shape
    _BASEPLATE_SHAPE_CACHE.move_to_end(key)
    while len(_BASEPLATE_SHAPE_CACHE) > _BASEPLATE_SHAPE_CACHE_MAX:
        _BASEPLATE_SHAPE_CACHE.popitem(last=False)
    return shape.copy()


def _derive_layout_from_params(
    params: CombinedBaseplateParamsData | CombinedSupportBaseplateParamsData,
) -> GridfinityLayout:
    """Derive the cell layout from params data.

    Uses custom_layout if enabled and present, otherwise generates
    a rectangular grid from x_grid_count x y_grid_count.
    """
    size = params.baseplate_size
    if size.custom_layout_enabled and size.custom_layout:
        return size.custom_layout
    return [[True] * size.y_grid_count for _ in range(size.x_grid_count)]


def build_single_baseplate_from_params(  # noqa: C901, PLR0912, PLR0915
    params: CombinedBaseplateParamsData,
    *,
    preview: bool = False,
) -> Part.Shape:
    """Build a simple baseplate from params.

    Uses geometry-based building where each cell gets its correct spring mask.
    """
    layout = _derive_layout_from_params(params)
    timing_on = _timing_enabled()
    t_total = time.perf_counter() if timing_on else 0.0
    nx = max(0, int(params.baseplate_size.x_grid_count))
    ny = max(0, int(params.baseplate_size.y_grid_count))

    f = params.baseplate_size
    left_fill_present = f.filler_left_enabled and float(f.filler_left_width) > 0
    right_fill_present = f.filler_right_enabled and float(f.filler_right_width) > 0
    top_fill_present = f.filler_top_enabled and float(f.filler_top_width) > 0
    bottom_fill_present = f.filler_bottom_enabled and float(f.filler_bottom_width) > 0

    if nx == 0 and ny == 0:
        raise ValueError("X and Y grid units cannot both be 0")
    if nx == 0 and not (left_fill_present or right_fill_present):
        raise ValueError("X grid units = 0 requires Left or Right filler")
    if ny == 0 and not (top_fill_present or bottom_fill_present):
        raise ValueError("Y grid units = 0 requires Top or Bottom filler")

    # Build geometry with spring masks
    t_geom = time.perf_counter() if timing_on else 0.0
    geometry = baseplate_full_layout.build_full_layout(
        params,
        layout,
        include_spring_masks=(not preview and params.click_springs.enabled),
    )
    if timing_on:
        _timing_print("baseplate.build_geometry", time.perf_counter() - t_geom)

    # Build all cells from geometry
    t_cells = time.perf_counter() if timing_on else 0.0
    shape = build_cells_from_geometry(params, geometry, preview=preview)
    if timing_on:
        _timing_print("baseplate.build_cells", time.perf_counter() - t_cells)

    if shape.isNull():
        raise ValueError("No cells to build")

    # Apply corner roundover (non-preview only)
    if not preview:
        t_round = time.perf_counter() if timing_on else 0.0
        shape = _apply_layout_corner_roundover(shape, params, geometry)
        if timing_on:
            _timing_print("baseplate.roundover", time.perf_counter() - t_round)

    # Handle preview translation
    if preview:
        min_x, min_y = _layout_min_indices(layout)
        if min_x > 0 or min_y > 0:
            grid_size = float(params.fundamentals.grid_size)
            shape.translate(fc.Vector(-min_x * grid_size, -min_y * grid_size, 0))
            placement = shape.Placement
            shape.Placement = fc.Placement()
            shape = shape.transformGeometry(placement.toMatrix())
        if timing_on:
            _timing_print("baseplate.total", time.perf_counter() - t_total)
        return shape

    # Apply post-replication cutter (junction screws, connecting clips)
    t_post = time.perf_counter() if timing_on else 0.0
    top_z = (
        max(v.Z for v in shape.Vertexes) * fc.Units.Quantity("1 mm")
        if shape.Vertexes
        else 0 * fc.Units.Quantity("1 mm")
    )
    post_cutter = make_post_replication_cutter(params, geometry, top_z)
    if post_cutter is not None:
        shape = shape.cut(post_cutter)
    if timing_on:
        _timing_print("baseplate.post_cutter", time.perf_counter() - t_post)

    # Translate shape so bounding box starts at origin (0, 0)
    min_x, min_y = _layout_min_indices(layout)
    if min_x > 0 or min_y > 0:
        grid_size = float(params.fundamentals.grid_size)
        shape.translate(fc.Vector(-min_x * grid_size, -min_y * grid_size, 0))
        placement = shape.Placement
        shape.Placement = fc.Placement()
        shape = shape.transformGeometry(placement.toMatrix())

    if timing_on:
        _timing_print("baseplate.total", time.perf_counter() - t_total)

    return shape
