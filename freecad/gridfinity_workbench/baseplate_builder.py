"""Build pipeline for simple baseplate geometry."""

from __future__ import annotations

import os
import time
import json
from collections import OrderedDict
from dataclasses import dataclass, replace
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from typing import Callable

import FreeCAD as fc  # noqa: N813
import Part

from . import baseplate_feature_construction as baseplate_feat
from . import baseplate_click_springs as click_springs
from . import baseplate_cell_cache
from . import baseplate_corner_roundover
from . import baseplate_full_layout
from . import feature_construction as feat
from . import utils
from .baseplate_params import BaseplateParams, params_from_obj
from .baseplate_full_layout import GridfinityLayout, GridfinityLayoutGeometry


def _timing_enabled() -> bool:
    return os.environ.get("GRIDFINITY_DEBUG_TIMING", "").lower() in {"1", "true", "yes", "on"}


def _timing_print(label: str, seconds: float) -> None:
    fc.Console.PrintMessage(f"[Gridfinity Timing] {label}: {seconds:.4f}s\n")


_BASEPLATE_SHAPE_CACHE_MAX = 32
_BASEPLATE_SHAPE_CACHE: OrderedDict[str, Part.Shape] = OrderedDict()


def set_baseplate_shape_cache_max_entries(max_entries: int) -> None:
    global _BASEPLATE_SHAPE_CACHE_MAX
    _BASEPLATE_SHAPE_CACHE_MAX = max(0, int(max_entries))
    if _BASEPLATE_SHAPE_CACHE_MAX == 0:
        _BASEPLATE_SHAPE_CACHE.clear()
        return
    while len(_BASEPLATE_SHAPE_CACHE) > _BASEPLATE_SHAPE_CACHE_MAX:
        _BASEPLATE_SHAPE_CACHE.popitem(last=False)


def set_cell_shape_cache_max_entries(max_entries: int) -> None:
    baseplate_cell_cache.set_cell_cache_max_entries(max_entries)


def _cache_normalize(value: object) -> object:
    if is_dataclass(value):
        return {
            field.name: _cache_normalize(getattr(value, field.name))
            for field in dataclass_fields(value)
        }
    if isinstance(value, dict):
        return {str(k): _cache_normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_cache_normalize(v) for v in value]
    if isinstance(value, (bool, int, str)) or value is None:
        return value
    if isinstance(value, float):
        return round(value, 2)
    if hasattr(value, "Value"):
        try:
            return round(float(value), 2)
        except Exception:
            return str(value)
    return str(value)


def _baseplate_cache_key(
    params: BaseplateParams,
    layout: GridfinityLayout,
    options: BaseplateBuildOptions,
    *,
    preview: bool,
) -> str:
    payload = {
        "kind": "simple_baseplate",
        "params": _cache_normalize(params),
        "layout": _cache_normalize(layout),
        "options": _cache_normalize(options),
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
    obj: fc.DocumentObject,
    layout: GridfinityLayout,
) -> Part.Shape:
    obj_payload = {
        name: _cache_normalize(getattr(obj, name))
        for name in getattr(obj, "PropertiesList", [])
        if name != "Shape"
    }
    key = json.dumps(
        {
            "kind": "support_baseplate",
            "obj": obj_payload,
            "layout": _cache_normalize(layout),
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    def _build() -> Part.Shape:
        shape = feat.make_baseplate_top_support(obj, layout)
        z_start = obj.BaseProfileMainHeight + obj.BaseProfileMainHalfWidth - obj.BaseProfileTopCrop
        z_matrix = fc.Matrix()
        z_matrix.move(fc.Vector(0, 0, z_start.Value))
        try:
            return shape.transformGeometry(z_matrix)
        except Exception:
            shifted_shape = shape.copy()
            try:
                shifted_shape.transformShape(z_matrix, copy=False)
            except TypeError:
                shifted_shape.transformShape(z_matrix, False)
            return shifted_shape

    return _shape_cache_get_or_build(key, _build)


def _layout_dims(layout: GridfinityLayout, params: BaseplateParams) -> tuple[int, int]:
    nx = len(layout)
    if nx == 0:
        return 0, max(0, int(params.core.y_grid_count))
    return nx, len(layout[0])


def _matrix_not(mask: list[list[bool]]) -> list[list[bool]]:
    return [[not mask[x][y] for y in range(2)] for x in range(2)]


@dataclass
class BaseplateBuildOptions:
    include_junction_screws: bool = True
    include_clip_cutouts: bool = True
    include_snap_springs: bool = True


@dataclass
class CoreCellBuildResult:
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


def _base_apex_height(params: BaseplateParams) -> fc.Units.Quantity:
    return (
        params.fundamentals.base_profile_main_height
        + params.fundamentals.base_profile_main_half_width
    )


def baseplate_cell_top_crop(shape: Part.Shape, params: BaseplateParams) -> Part.Shape:
    top_crop = params.core.base_profile_top_crop
    half_width = params.fundamentals.base_profile_main_half_width
    if top_crop >= half_width:
        raise ValueError(
            f"BaseProfileTopCrop ({top_crop}) must be smaller than "
            f"BaseProfileMainHalfWidth ({half_width})"
        )

    apex = _base_apex_height(params)
    margin = 0.1 * fc.Units.Quantity("1 mm")
    crop_slab = _make_centered_box(
        params.fundamentals.x_grid_size + margin,
        params.fundamentals.y_grid_size + margin,
        top_crop + margin,
        z_min=float(apex - top_crop),
    )
    return shape.cut(crop_slab)


def build_single_cell_baseplate_core(
    params: BaseplateParams,
    options: BaseplateBuildOptions,
) -> CoreCellBuildResult:
    baseplate_outside_shape = _create_rectangle_wire(
        params.fundamentals.x_grid_size,
        params.fundamentals.y_grid_size,
    )
    total_height = _base_apex_height(params)
    face = Part.Face(baseplate_outside_shape)
    solid_shape = face.extrude(fc.Vector(0, 0, total_height))
    bin_base_shape = feat.make_complex_bin_base_single_from_params(params.fundamentals, params.core)
    tiny_cell = bin_base_shape.isNull()
    if tiny_cell:
        return CoreCellBuildResult(shape=solid_shape, is_tiny=True)
    bin_base_shape.translate(fc.Vector(0, 0, total_height))
    return CoreCellBuildResult(shape=solid_shape.cut(bin_base_shape), is_tiny=False)


def build_single_cell_baseplate_core_cached(
    params: BaseplateParams,
    options: BaseplateBuildOptions,
) -> CoreCellBuildResult:
    key = baseplate_cell_cache.make_key(
        {
            "kind": "baseplate_core_cell",
            "params": params,
            "options": options,
        }
    )

    def _build() -> Part.Shape:
        return build_single_cell_baseplate_core(params, options).shape

    shape = baseplate_cell_cache.get_or_build(key, _build)
    tiny_cell = feat.make_complex_bin_base_single_from_params(
        params.fundamentals, params.core
    ).isNull()
    return CoreCellBuildResult(shape=shape, is_tiny=tiny_cell)


def build_preview_single_cell_baseplate_core(
    params: BaseplateParams,
) -> CoreCellBuildResult:
    margin = 0.1
    x_grid_size = float(params.fundamentals.x_grid_size)
    y_grid_size = float(params.fundamentals.y_grid_size)
    main_height = float(params.fundamentals.base_profile_main_height)
    main_half_width = float(params.fundamentals.base_profile_main_half_width)

    outer = _make_centered_box(x_grid_size, y_grid_size, main_height)
    if x_grid_size <= main_half_width or y_grid_size <= main_half_width:
        return CoreCellBuildResult(shape=outer, is_tiny=True)
    inner = _make_centered_box(
        x_grid_size - main_half_width,
        y_grid_size - main_half_width,
        main_height + (2 * margin),
        z_min=-margin,
    )
    return CoreCellBuildResult(shape=outer.cut(inner), is_tiny=False)


def build_preview_single_cell_baseplate_core_cached(
    params: BaseplateParams,
) -> CoreCellBuildResult:
    key = baseplate_cell_cache.make_key(
        {
            "kind": "baseplate_preview_core_cell",
            "params": params,
        }
    )

    def _build() -> Part.Shape:
        return build_preview_single_cell_baseplate_core(params).shape

    return CoreCellBuildResult(shape=baseplate_cell_cache.get_or_build(key, _build), is_tiny=False)


def replicate_layout(
    shape: Part.Shape,
    params: BaseplateParams,
    layout: GridfinityLayout,
) -> Part.Shape:
    base_cell = shape.copy()
    base_cell.translate(
        fc.Vector(
            params.fundamentals.x_grid_size / 2,
            params.fundamentals.y_grid_size / 2,
            0,
        )
    )
    return utils.copy_in_layout(
        base_cell,
        layout,
        params.fundamentals.x_grid_size,
        params.fundamentals.y_grid_size,
    )


def add_filler_strips(
    shape: Part.Shape,
    params: BaseplateParams,
    layout: GridfinityLayout,
    options: BaseplateBuildOptions,
    *,
    preview: bool = False,
) -> tuple[Part.Shape, GridfinityLayoutGeometry]:
    expanded = baseplate_full_layout.build_full_layout(
        params,
        layout,
        include_spring_masks=(
            not preview and options.include_snap_springs and params.click_springs.enabled
        ),
    )
    nx, ny = _layout_dims(layout, params)
    expanded_nx, expanded_ny = expanded.size()
    has_fillers = expanded_nx != nx or expanded_ny != ny
    if not has_fillers:
        return shape, expanded

    if not shape.isNull():
        x_core_shift = (
            params.fillers.left_width
            if params.fillers.left_enabled and float(params.fillers.left_width) > 0
            else 0 * params.fundamentals.x_grid_size
        )
        y_core_shift = (
            params.fillers.bottom_width
            if params.fillers.bottom_enabled and float(params.fillers.bottom_width) > 0
            else 0 * params.fundamentals.y_grid_size
        )
        shape.translate(fc.Vector(x_core_shift, y_core_shift, 0))

    filler_shape = _build_filler_ring_shape(params, expanded, options, preview=preview)
    if shape.isNull():
        return filler_shape, expanded
    combined = shape.fuse(filler_shape)
    return combined, expanded


def _build_grid_lines(sizes: list[fc.Units.Quantity]) -> list[float]:
    lines = [0.0]
    total = 0.0
    for size in sizes:
        total += float(size)
        lines.append(total)
    return lines


def _build_filler_cell_shape(
    params: BaseplateParams,
    target_cell_width: float,
    target_cell_height: float,
    options: BaseplateBuildOptions,
    *,
    preview: bool = False,
) -> CoreCellBuildResult:
    unitmm = fc.Units.Quantity("1 mm")
    filler_params = replace(
        params,
        fundamentals=replace(
            params.fundamentals,
            x_grid_size=target_cell_width * unitmm,
            y_grid_size=target_cell_height * unitmm,
        ),
    )
    if preview:
        return build_preview_single_cell_baseplate_core_cached(filler_params)
    return build_single_cell_baseplate_core_cached(filler_params, options)


def _build_filler_ring_shape(
    params: BaseplateParams,
    geometry: GridfinityLayoutGeometry,
    options: BaseplateBuildOptions,
    *,
    preview: bool = False,
) -> Part.Shape:
    timing_on = _timing_enabled()
    t_total = time.perf_counter() if timing_on else 0.0

    nx_exp, ny_exp = geometry.size()
    nx = nx_exp - 2
    ny = ny_exp - 2

    left_on = params.fillers.left_enabled and float(params.fillers.left_width) > 0
    right_on = params.fillers.right_enabled and float(params.fillers.right_width) > 0
    bottom_on = params.fillers.bottom_enabled and float(params.fillers.bottom_width) > 0
    top_on = params.fillers.top_enabled and float(params.fillers.top_width) > 0

    negative_slots: click_springs.SpringShapeSlots | None = None
    positive_slots: click_springs.SpringShapeSlots | None = None
    if not preview and options.include_snap_springs and params.click_springs.enabled:
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
            options,
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
                params.core,
                params.click_springs,
                negative_slots,
                positive_slots,
                mask,
            )
            cell.translate(fc.Vector(-align_shift.x, -align_shift.y, 0))
        unitmm = fc.Units.Quantity("1 mm")
        filler_params = replace(
            params,
            fundamentals=replace(
                params.fundamentals,
                x_grid_size=width * unitmm,
                y_grid_size=height * unitmm,
            ),
        )
        cell = baseplate_cell_top_crop(cell, filler_params)
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
        for (ix, iy), vec in zip(spec["indices"], spec["vectors"]):
            t0 = time.perf_counter() if timing_on else 0.0
            side_result = proto(
                spec["width"],
                spec["height"],
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
        leftmost, rightmost, bottommost, topmost = spec["flags"]
        t0 = time.perf_counter() if timing_on else 0.0
        corner_result = proto(
            spec["width"],
            spec["height"],
            cell_meta=geometry.cells[spec["ix"]][spec["iy"]],
        )
        if timing_on:
            t_proto += time.perf_counter() - t0
        corner = corner_result.shape.copy()
        t1 = time.perf_counter() if timing_on else 0.0
        corner.translate(center(spec["ix"], spec["iy"]))
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
    params: BaseplateParams,
    geometry: GridfinityLayoutGeometry,
) -> Part.Shape:
    apex = float(
        params.fundamentals.base_profile_main_height
        + params.fundamentals.base_profile_main_half_width
    )
    top_crop = float(params.core.base_profile_top_crop)
    roundover_height = apex - top_crop
    return baseplate_corner_roundover.apply_layout_corner_roundover(
        shape,
        geometry=geometry,
        outside_radius=float(params.fundamentals.bin_outer_radius),
        height=roundover_height,
    )


def apply_junction_screws(
    shape: Part.Shape,
    obj: fc.DocumentObject,
    layout: GridfinityLayout,
    options: BaseplateBuildOptions,
) -> Part.Shape:
    if not options.include_junction_screws:
        return shape
    junction_holes = baseplate_feat.make_junction_screw_holes(obj, layout)
    return shape.cut(junction_holes) if junction_holes is not None else shape


def make_post_replication_cutter(
    params: BaseplateParams,
    geometry: GridfinityLayoutGeometry,
    options: BaseplateBuildOptions,
    top_z: fc.Units.Quantity,
) -> Part.Shape | None:
    cutters: list[Part.Shape] = []

    if options.include_junction_screws:
        junction_holes = baseplate_feat.make_junction_screw_holes_from_params(
            params.fundamentals,
            params.junction_screws,
            top_z,
            geometry=geometry,
        )
        if junction_holes is not None:
            cutters.append(junction_holes)

    if options.include_clip_cutouts:
        clip_cutouts = baseplate_feat.make_clip_cutouts_from_params(
            params.fundamentals,
            params.clip_cutouts,
            geometry=geometry,
        )
        if clip_cutouts is not None:
            cutters.append(clip_cutouts)

    if not cutters:
        return None
    return cutters[0].multiFuse(cutters[1:]) if len(cutters) > 1 else cutters[0]


def apply_clip_cutouts(
    shape: Part.Shape,
    obj: fc.DocumentObject,
    layout: GridfinityLayout,
    options: BaseplateBuildOptions,
) -> Part.Shape:
    if not options.include_clip_cutouts:
        return shape
    clip_cutouts = baseplate_feat.make_clip_cutouts(obj, layout)
    return shape.cut(clip_cutouts) if clip_cutouts is not None else shape


def apply_snap_springs(
    shape: Part.Shape,
    params: BaseplateParams,
    options: BaseplateBuildOptions,
) -> Part.Shape:
    if not options.include_snap_springs:
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
        params.core,
        params.click_springs,
        negative_slots,
        positive_slots,
        click_springs.SpringSlotMask.all_true(),
    )


def build_simple_baseplate(
    obj: fc.DocumentObject,
    layout: GridfinityLayout,
    options: BaseplateBuildOptions,
    *,
    preview: bool = False,
) -> Part.Shape:
    params = params_from_obj(obj)
    return build_simple_baseplate_from_params_cached(params, layout, options, preview=preview)


def build_simple_baseplate_from_params_cached(
    params: BaseplateParams,
    layout: GridfinityLayout,
    options: BaseplateBuildOptions,
    *,
    preview: bool = False,
) -> Part.Shape:
    if _BASEPLATE_SHAPE_CACHE_MAX <= 0:
        return build_simple_baseplate_from_params(params, layout, options, preview=preview)

    key = _baseplate_cache_key(params, layout, options, preview=preview)
    cached_shape = _BASEPLATE_SHAPE_CACHE.get(key)
    if cached_shape is not None:
        _BASEPLATE_SHAPE_CACHE.move_to_end(key)
        return cached_shape.copy()
    shape = build_simple_baseplate_from_params(params, layout, options, preview=preview)
    _BASEPLATE_SHAPE_CACHE[key] = shape
    _BASEPLATE_SHAPE_CACHE.move_to_end(key)
    while len(_BASEPLATE_SHAPE_CACHE) > _BASEPLATE_SHAPE_CACHE_MAX:
        _BASEPLATE_SHAPE_CACHE.popitem(last=False)
    return shape.copy()


def build_simple_baseplate_from_params(
    params: BaseplateParams,
    layout: GridfinityLayout,
    options: BaseplateBuildOptions,
    *,
    preview: bool = False,
) -> Part.Shape:
    timing_on = _timing_enabled()
    t_total = time.perf_counter() if timing_on else 0.0
    nx = max(0, int(params.core.x_grid_count))
    ny = max(0, int(params.core.y_grid_count))

    left_fill_present = params.fillers.left_enabled and float(params.fillers.left_width) > 0
    right_fill_present = params.fillers.right_enabled and float(params.fillers.right_width) > 0
    top_fill_present = params.fillers.top_enabled and float(params.fillers.top_width) > 0
    bottom_fill_present = params.fillers.bottom_enabled and float(params.fillers.bottom_width) > 0

    if nx == 0 and ny == 0:
        raise ValueError("X and Y grid units cannot both be 0")
    if nx == 0 and not (left_fill_present or right_fill_present):
        raise ValueError("X grid units = 0 requires Left or Right filler")
    if ny == 0 and not (top_fill_present or bottom_fill_present):
        raise ValueError("Y grid units = 0 requires Top or Bottom filler")

    if nx == 0 or ny == 0:
        empty_shape = Part.Shape()
        t_fill_only = time.perf_counter() if timing_on else 0.0
        shape, geometry = add_filler_strips(empty_shape, params, layout, options, preview=preview)
        if timing_on:
            _timing_print(
                "baseplate.filler_only.add_filler_strips", time.perf_counter() - t_fill_only
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
    core_result = (
        build_preview_single_cell_baseplate_core_cached(params)
        if preview
        else build_single_cell_baseplate_core_cached(params, options)
    )
    if timing_on:
        _timing_print("baseplate.core_build", time.perf_counter() - t_core)
    shape = core_result.shape
    if not preview and not core_result.is_tiny:
        t_springs = time.perf_counter() if timing_on else 0.0
        shape = apply_snap_springs(shape, params, options)
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
    shape, geometry = add_filler_strips(shape, params, layout, options, preview=preview)
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
        if timing_on:
            _timing_print("baseplate.total", time.perf_counter() - t_total)
        return shape
    else:
        t_post = time.perf_counter() if timing_on else 0.0
        top_z = (
            max(v.Z for v in shape.Vertexes) * fc.Units.Quantity("1 mm")
            if shape.Vertexes
            else 0 * fc.Units.Quantity("1 mm")
        )
        post_cutter = make_post_replication_cutter(params, geometry, options, top_z)
        if post_cutter is not None:
            shape = shape.cut(post_cutter)
        if timing_on:
            _timing_print("baseplate.post_cutter", time.perf_counter() - t_post)
            _timing_print("baseplate.total", time.perf_counter() - t_total)

    return shape
