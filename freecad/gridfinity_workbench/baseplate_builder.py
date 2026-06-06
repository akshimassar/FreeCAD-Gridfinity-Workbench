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


def _layout_dims(layout: GridfinityLayout, params: CombinedBaseplateParamsData) -> tuple[int, int]:
    nx = len(layout)
    if nx == 0:
        return 0, max(0, int(params.baseplate_size.y_grid_count))
    return nx, len(layout[0])


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


def replicate_layout(
    shape: Part.Shape,
    params: CombinedBaseplateParamsData,
    layout: GridfinityLayout,
) -> Part.Shape:
    """Replicate a single cell shape across the layout grid."""
    base_cell = shape.copy()
    base_cell.translate(
        fc.Vector(
            params.fundamentals.grid_size / 2,
            params.fundamentals.grid_size / 2,
            0,
        ),
    )
    return utils.copy_in_layout(
        base_cell,
        layout,
        params.fundamentals.grid_size,
        params.fundamentals.grid_size,
    )


def add_filler_strips(
    shape: Part.Shape,
    params: CombinedBaseplateParamsData,
    layout: GridfinityLayout,
    *,
    preview: bool = False,
) -> tuple[Part.Shape, GridfinityLayoutGeometry]:
    """Add filler strips around the core layout."""
    expanded = baseplate_full_layout.build_full_layout(
        params,
        layout,
        include_spring_masks=(not preview and params.click_springs.enabled),
    )
    nx, ny = _layout_dims(layout, params)
    expanded_nx, expanded_ny = expanded.size()
    has_fillers = expanded_nx != nx or expanded_ny != ny
    if not has_fillers:
        return shape, expanded

    if not shape.isNull():
        left_w = params.baseplate_size.filler_left_width
        left_on = params.baseplate_size.filler_left_enabled and float(left_w) > 0
        x_core_shift = left_w if left_on else 0 * params.fundamentals.grid_size

        bottom_w = params.baseplate_size.filler_bottom_width
        bottom_on = params.baseplate_size.filler_bottom_enabled and float(bottom_w) > 0
        y_core_shift = bottom_w if bottom_on else 0 * params.fundamentals.grid_size
        shape.translate(fc.Vector(float(x_core_shift), float(y_core_shift), 0))

    filler_shape = _build_filler_ring_shape(params, expanded, preview=preview)
    if shape.isNull():
        return filler_shape, expanded
    combined = shape.fuse(filler_shape)
    return combined, expanded


def _build_filler_cell_shape(
    params: CombinedBaseplateParamsData,
    target_cell_width: float,
    target_cell_height: float,
    *,
    preview: bool = False,
) -> CoreCellBuildResult:
    return build_single_cell_baseplate_core_cached(
        params,
        preview=preview,
        x_size_override=target_cell_width,
        y_size_override=target_cell_height,
    )


def _build_filler_ring_shape(  # noqa: C901, PLR0912, PLR0915
    params: CombinedBaseplateParamsData,
    geometry: GridfinityLayoutGeometry,
    *,
    preview: bool = False,
) -> Part.Shape:
    timing_on = _timing_enabled()
    t_total = time.perf_counter() if timing_on else 0.0

    nx_exp, ny_exp = geometry.size()
    nx = nx_exp - 2
    ny = ny_exp - 2

    f = params.baseplate_size
    left_on = f.filler_left_enabled and float(f.filler_left_width) > 0
    right_on = f.filler_right_enabled and float(f.filler_right_width) > 0
    bottom_on = f.filler_bottom_enabled and float(f.filler_bottom_width) > 0
    top_on = f.filler_top_enabled and float(f.filler_top_width) > 0

    negative_slots: click_springs.SpringShapeSlots | None = None
    positive_slots: click_springs.SpringShapeSlots | None = None
    if not preview and params.click_springs.enabled:
        negative_slots = click_springs.make_click_spring_prototype_negative(
            params.fundamentals,
            params.click_springs,
        )
        positive_slots = click_springs.make_click_spring_prototype_positive(
            params.fundamentals,
            params.click_springs,
        )

    def proto(
        width: float,
        height: float,
        *,
        cell_meta: baseplate_full_layout.FullLayoutCell,
    ) -> CoreCellBuildResult:
        filler_result = _build_filler_cell_shape(
            params,
            width,
            height,
            preview=preview,
        )
        cell = filler_result.shape
        mask = cell_meta.get_mask()
        if negative_slots is not None and positive_slots is not None and mask is not None:
            align_shift = fc.Vector(cell_meta.spring_shift_x, cell_meta.spring_shift_y, 0)
            cell.translate(align_shift)
            cell = click_springs.apply_click_spring_slots_to_cell(
                cell,
                params.fundamentals,
                params.baseplate_core,
                params.click_springs,
                negative_slots,
                positive_slots,
                mask,
            )
            cell.translate(fc.Vector(-align_shift.x, -align_shift.y, 0))
        cell = baseplate_cell_top_crop(
            cell,
            params,
            x_size_override=width,
            y_size_override=height,
        )
        return CoreCellBuildResult(shape=cell, is_tiny=filler_result.is_tiny)

    def center(ix: int, iy: int) -> fc.Vector:
        x, y = geometry.cell_center(ix, iy)
        return fc.Vector(x, y, 0)

    pieces: list[Part.Shape] = []
    t_sides = 0.0
    t_corners = 0.0
    t_proto = 0.0
    t_translate = 0.0

    side_specs = [
        {
            "enabled": left_on,
            "width": geometry.cells[0][1].width,
            "height": geometry.cells[0][1].height,
            "flags": (True, False, False, False),
            "vectors": [center(0, iy) for iy in range(1, ny + 1)],
            "indices": [(0, iy) for iy in range(1, ny + 1)],
        },
        {
            "enabled": right_on,
            "width": geometry.cells[nx + 1][1].width,
            "height": geometry.cells[nx + 1][1].height,
            "flags": (False, True, False, False),
            "vectors": [center(nx + 1, iy) for iy in range(1, ny + 1)],
            "indices": [(nx + 1, iy) for iy in range(1, ny + 1)],
        },
        {
            "enabled": bottom_on,
            "width": geometry.cells[1][0].width,
            "height": geometry.cells[1][0].height,
            "flags": (False, False, True, False),
            "vectors": [center(ix, 0) for ix in range(1, nx + 1)],
            "indices": [(ix, 0) for ix in range(1, nx + 1)],
        },
        {
            "enabled": top_on,
            "width": geometry.cells[1][ny + 1].width,
            "height": geometry.cells[1][ny + 1].height,
            "flags": (False, False, False, True),
            "vectors": [center(ix, ny + 1) for ix in range(1, nx + 1)],
            "indices": [(ix, ny + 1) for ix in range(1, nx + 1)],
        },
    ]

    for spec in side_specs:
        if not spec["enabled"]:
            continue
        t_side = time.perf_counter() if timing_on else 0.0
        if not spec["indices"]:
            continue
        for (ix, iy), vec in zip(spec["indices"], spec["vectors"], strict=False):
            t0 = time.perf_counter() if timing_on else 0.0
            side_result = proto(
                float(spec["width"]),  # type: ignore[arg-type]
                float(spec["height"]),  # type: ignore[arg-type]
                cell_meta=geometry.cells[ix][iy],
            )
            if timing_on:
                t_proto += time.perf_counter() - t0
                t1 = time.perf_counter()
            side = side_result.shape.copy()
            side.translate(vec)
            pieces.append(side)
            if timing_on:
                t_translate += time.perf_counter() - t1
            geometry.cells[ix][iy].is_tiny = side_result.is_tiny
        if timing_on:
            t_sides += time.perf_counter() - t_side

    corner_specs = [
        {
            "enabled": left_on and bottom_on,
            "ix": 0,
            "iy": 0,
            "width": geometry.cells[0][0].width,
            "height": geometry.cells[0][0].height,
            "flags": (True, False, True, False),
        },
        {
            "enabled": left_on and top_on,
            "ix": 0,
            "iy": ny + 1,
            "width": geometry.cells[0][ny + 1].width,
            "height": geometry.cells[0][ny + 1].height,
            "flags": (True, False, False, True),
        },
        {
            "enabled": right_on and bottom_on,
            "ix": nx + 1,
            "iy": 0,
            "width": geometry.cells[nx + 1][0].width,
            "height": geometry.cells[nx + 1][0].height,
            "flags": (False, True, True, False),
        },
        {
            "enabled": right_on and top_on,
            "ix": nx + 1,
            "iy": ny + 1,
            "width": geometry.cells[nx + 1][ny + 1].width,
            "height": geometry.cells[nx + 1][ny + 1].height,
            "flags": (False, True, False, True),
        },
    ]

    for spec in corner_specs:
        if not spec["enabled"]:
            continue
        t_corner = time.perf_counter() if timing_on else 0.0
        leftmost, rightmost, bottommost, topmost = spec["flags"]  # type: ignore[misc]
        t0 = time.perf_counter() if timing_on else 0.0
        corner_result = proto(
            float(spec["width"]),  # type: ignore[arg-type]
            float(spec["height"]),  # type: ignore[arg-type]
            cell_meta=geometry.cells[spec["ix"]][spec["iy"]],  # type: ignore[index]
        )
        if timing_on:
            t_proto += time.perf_counter() - t0
        corner = corner_result.shape.copy()
        t1 = time.perf_counter() if timing_on else 0.0
        corner.translate(center(int(spec["ix"]), int(spec["iy"])))
        if timing_on:
            t_translate += time.perf_counter() - t1
            t_corners += time.perf_counter() - t_corner
        pieces.append(corner)
        geometry.cells[spec["ix"]][spec["iy"]].is_tiny = corner_result.is_tiny

    if not pieces:
        raise ValueError("No filler pieces generated")
    t_fuse = time.perf_counter() if timing_on else 0.0
    out = utils.multi_fuse(pieces)
    if timing_on:
        _timing_print("filler_strips.proto_total", t_proto)
        _timing_print("filler_strips.translate_total", t_translate)
        _timing_print("filler_strips.sides_total", t_sides)
        _timing_print("filler_strips.corners_total", t_corners)
        _timing_print("filler_strips.fuse_total", time.perf_counter() - t_fuse)
        _timing_print("filler_strips.total", time.perf_counter() - t_total)
    return out


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


def apply_snap_springs(
    shape: Part.Shape,
    params: CombinedBaseplateParamsData,
) -> Part.Shape:
    """Apply snap spring slots to the baseplate shape."""
    if not params.click_springs.enabled:
        return shape
    negative_slots = click_springs.make_click_spring_prototype_negative(
        params.fundamentals,
        params.click_springs,
    )
    positive_slots = click_springs.make_click_spring_prototype_positive(
        params.fundamentals,
        params.click_springs,
    )
    return click_springs.apply_click_spring_slots_to_cell(
        shape,
        params.fundamentals,
        params.baseplate_core,
        params.click_springs,
        negative_slots,
        positive_slots,
        click_springs.SpringSlotMask.all_true(),
    )


def build_simple_baseplate_from_params_cached(
    params: CombinedBaseplateParamsData,
    *,
    preview: bool = False,
) -> Part.Shape:
    """Build a simple baseplate from params with caching."""
    if _BASEPLATE_SHAPE_CACHE_MAX <= 0:
        return build_simple_baseplate_from_params(params, preview=preview)

    key = _baseplate_cache_key(params, preview=preview)
    cached_shape = _BASEPLATE_SHAPE_CACHE.get(key)
    if cached_shape is not None:
        _BASEPLATE_SHAPE_CACHE.move_to_end(key)
        return cached_shape.copy()
    shape = build_simple_baseplate_from_params(params, preview=preview)
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


def build_simple_baseplate_from_params(  # noqa: C901, PLR0912, PLR0915
    params: CombinedBaseplateParamsData,
    *,
    preview: bool = False,
) -> Part.Shape:
    """Build a simple baseplate from params."""
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

    if nx == 0 or ny == 0:
        empty_shape = Part.Shape()
        t_fill_only = time.perf_counter() if timing_on else 0.0
        shape, geometry = add_filler_strips(empty_shape, params, layout, preview=preview)
        if timing_on:
            _timing_print(
                "baseplate.filler_only.add_filler_strips",
                time.perf_counter() - t_fill_only,
            )
        if shape.isNull():
            raise ValueError("No core cells and no fillers to build")
        if not preview:
            t_crop = time.perf_counter() if timing_on else 0.0
            shape = baseplate_cell_top_crop(shape, params)
            if timing_on:
                _timing_print("baseplate.filler_only.top_crop", time.perf_counter() - t_crop)
            t_round = time.perf_counter() if timing_on else 0.0
            shape = _apply_layout_corner_roundover(
                shape,
                params,
                geometry,
            )
            if timing_on:
                _timing_print("baseplate.filler_only.roundover", time.perf_counter() - t_round)
        if timing_on:
            _timing_print("baseplate.total", time.perf_counter() - t_total)
        return shape

    t_core = time.perf_counter() if timing_on else 0.0
    core_result = build_single_cell_baseplate_core_cached(params, preview=preview)
    if timing_on:
        _timing_print("baseplate.core_build", time.perf_counter() - t_core)
    shape = core_result.shape
    if not preview and not core_result.is_tiny:
        t_springs = time.perf_counter() if timing_on else 0.0
        shape = apply_snap_springs(shape, params)
        if timing_on:
            _timing_print("baseplate.snap_springs", time.perf_counter() - t_springs)
    if not preview:
        t_crop = time.perf_counter() if timing_on else 0.0
        shape = baseplate_cell_top_crop(shape, params)
        if timing_on:
            _timing_print("baseplate.top_crop", time.perf_counter() - t_crop)

    t_repl = time.perf_counter() if timing_on else 0.0
    shape = replicate_layout(shape, params, layout)
    if timing_on:
        _timing_print("baseplate.replicate_layout", time.perf_counter() - t_repl)

    t_fill = time.perf_counter() if timing_on else 0.0
    shape, geometry = add_filler_strips(shape, params, layout, preview=preview)
    if timing_on:
        _timing_print("baseplate.add_filler_strips", time.perf_counter() - t_fill)
    geometry_nx, geometry_ny = geometry.size()
    x_offset = 1 if geometry_nx == nx + 2 else 0
    y_offset = 1 if geometry_ny == ny + 2 else 0
    for ix in range(nx):
        for iy in range(ny):
            gx = ix + x_offset
            gy = iy + y_offset
            if geometry.cells[gx][gy].exists:
                geometry.cells[gx][gy].is_tiny = core_result.is_tiny

    if not preview:
        t_round = time.perf_counter() if timing_on else 0.0
        shape = _apply_layout_corner_roundover(
            shape,
            params,
            geometry,
        )
        if timing_on:
            _timing_print("baseplate.roundover", time.perf_counter() - t_round)
    if preview:
        # Translate shape so bounding box starts at origin (0, 0)
        # Must bake translation into geometry (not just Placement)
        min_x, min_y = _layout_min_indices(layout)
        if min_x > 0 or min_y > 0:
            grid_size = float(params.fundamentals.grid_size)
            shape.translate(fc.Vector(-min_x * grid_size, -min_y * grid_size, 0))
            # Bake Placement: reset first, then transformGeometry to avoid double-apply
            placement = shape.Placement
            shape.Placement = fc.Placement()
            shape = shape.transformGeometry(placement.toMatrix())
        if timing_on:
            _timing_print("baseplate.total", time.perf_counter() - t_total)
        return shape
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
    # Must bake translation into geometry (not just Placement)
    # because fp.Shape assignment strips Placement
    min_x, min_y = _layout_min_indices(layout)
    if min_x > 0 or min_y > 0:
        grid_size = float(params.fundamentals.grid_size)
        shape.translate(fc.Vector(-min_x * grid_size, -min_y * grid_size, 0))
        # Bake Placement: reset first, then transformGeometry to avoid double-apply
        placement = shape.Placement
        shape.Placement = fc.Placement()
        shape = shape.transformGeometry(placement.toMatrix())

    if timing_on:
        _timing_print("baseplate.total", time.perf_counter() - t_total)

    return shape
