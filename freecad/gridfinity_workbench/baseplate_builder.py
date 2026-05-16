"""Build pipeline for simple baseplate geometry."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace

import FreeCAD as fc  # noqa: N813
import Part

from . import baseplate_feature_construction as baseplate_feat
from . import feature_construction as feat
from . import utils
from .baseplate_params import BaseplateParams, params_from_obj
from .utils import GridfinityLayout, GridfinityLayoutGeometry


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
    use_preview_core: bool = False


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


def build_preview_single_cell_baseplate_core(
    params: BaseplateParams,
) -> CoreCellBuildResult:
    margin = 0.1
    x_grid_size = float(params.fundamentals.x_grid_size)
    y_grid_size = float(params.fundamentals.y_grid_size)
    main_height = float(params.fundamentals.base_profile_main_height)
    main_half_width = float(params.fundamentals.base_profile_main_half_width)

    outer = _make_centered_box(x_grid_size, y_grid_size, main_height)
    inner = _make_centered_box(
        x_grid_size - main_half_width,
        y_grid_size - main_half_width,
        main_height + (2 * margin),
        z_min=-margin,
    )
    return CoreCellBuildResult(shape=outer.cut(inner), is_tiny=False)


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
) -> tuple[Part.Shape, GridfinityLayoutGeometry]:
    expanded = _build_expanded_layout_with_fillers(params, layout)
    nx, ny = _layout_dims(layout, params)
    has_fillers = len(expanded.layout) != nx or len(expanded.layout[0]) != ny
    if not has_fillers:
        return shape, expanded

    filler_shape = _build_filler_ring_shape(params, expanded, options)
    if shape.isNull():
        return filler_shape, expanded
    combined = shape.fuse(filler_shape).removeSplitter()
    return combined, expanded


def _build_expanded_layout_with_fillers(
    params: BaseplateParams,
    layout: GridfinityLayout,
) -> GridfinityLayoutGeometry:
    nx, ny = _layout_dims(layout, params)

    left_w = (
        params.fillers.left_width
        if params.fillers.left_enabled
        else 0 * params.fundamentals.x_grid_size
    )
    right_w = (
        params.fillers.right_width
        if params.fillers.right_enabled
        else 0 * params.fundamentals.x_grid_size
    )
    bottom_w = (
        params.fillers.bottom_width
        if params.fillers.bottom_enabled
        else 0 * params.fundamentals.y_grid_size
    )
    top_w = (
        params.fillers.top_width
        if params.fillers.top_enabled
        else 0 * params.fundamentals.y_grid_size
    )

    use_fillers = any(float(v) > 0 for v in (left_w, right_w, bottom_w, top_w))
    if not use_fillers:
        return GridfinityLayoutGeometry(
            layout=[[bool(layout[ix][iy]) for iy in range(ny)] for ix in range(nx)]
            if nx > 0
            else [],
            tiny=[[False for _ in range(ny)] for _ in range(nx)] if nx > 0 else [],
            x_lines=_build_grid_lines([params.fundamentals.x_grid_size] * nx),
            y_lines=_build_grid_lines([params.fundamentals.y_grid_size] * ny),
        )

    x_sizes: list[fc.Units.Quantity] = [left_w] + [params.fundamentals.x_grid_size] * nx + [right_w]
    y_sizes: list[fc.Units.Quantity] = [bottom_w] + [params.fundamentals.y_grid_size] * ny + [top_w]

    expanded: GridfinityLayout = [[False for _ in range(ny + 2)] for _ in range(nx + 2)]
    tiny: GridfinityLayout = [[False for _ in range(ny + 2)] for _ in range(nx + 2)]

    for ix in range(nx):
        for iy in range(ny):
            expanded[ix + 1][iy + 1] = bool(layout[ix][iy])

    if float(left_w) > 0:
        for iy in range(1, ny + 1):
            expanded[0][iy] = True
    if float(right_w) > 0:
        for iy in range(1, ny + 1):
            expanded[nx + 1][iy] = True
    if float(bottom_w) > 0:
        for ix in range(1, nx + 1):
            expanded[ix][0] = True
    if float(top_w) > 0:
        for ix in range(1, nx + 1):
            expanded[ix][ny + 1] = True

    if float(left_w) > 0 and float(bottom_w) > 0:
        expanded[0][0] = True
    if float(left_w) > 0 and float(top_w) > 0:
        expanded[0][ny + 1] = True
    if float(right_w) > 0 and float(bottom_w) > 0:
        expanded[nx + 1][0] = True
    if float(right_w) > 0 and float(top_w) > 0:
        expanded[nx + 1][ny + 1] = True

    return GridfinityLayoutGeometry(
        layout=expanded,
        tiny=tiny,
        x_lines=[x - float(left_w) for x in _build_grid_lines(x_sizes)],
        y_lines=[y - float(bottom_w) for y in _build_grid_lines(y_sizes)],
    )


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
    if options.use_preview_core:
        return build_preview_single_cell_baseplate_core(filler_params)
    return build_single_cell_baseplate_core(filler_params, options)


def _filler_spring_mask(
    params: BaseplateParams,
    *,
    leftmost: bool,
    rightmost: bool,
    bottommost: bool,
    topmost: bool,
    target_cell_width: float,
    target_cell_height: float,
) -> feat.SpringSlotMask:
    mask = feat.SpringSlotMask.all_true()

    # X-first matrix indexing with y=0 as top row:
    # left  -> x=0 column, right -> x=1 column, top -> y=0 row, bottom -> y=1 row.
    side_masks = [
        (leftmost, [[True, True], [False, False]]),
        (rightmost, [[False, False], [True, True]]),
        (topmost, [[True, False], [True, False]]),
        (bottommost, [[False, True], [False, True]]),
    ]
    for enabled, side_mask in side_masks:
        if not enabled:
            continue
        mask = mask.with_vertical_disabled(side_mask)
        mask = mask.with_horizontal_disabled(side_mask)

    if (
        target_cell_width < float(params.fundamentals.x_grid_size) / 2
        or target_cell_height < float(params.fundamentals.y_grid_size) / 2
    ):
        mask = mask.with_all_horizontal_disabled()
        mask = mask.with_all_vertical_disabled()

    return mask


def _filler_alignment_shift(
    params: BaseplateParams,
    *,
    leftmost: bool,
    rightmost: bool,
    bottommost: bool,
    topmost: bool,
    target_cell_width: float,
    target_cell_height: float,
) -> fc.Vector:
    sx = -1 if leftmost else (1 if rightmost else 0)
    sy = -1 if bottommost else (1 if topmost else 0)

    grid_half_x = float(params.fundamentals.x_grid_size) / 2
    grid_half_y = float(params.fundamentals.y_grid_size) / 2
    cell_half_x = target_cell_width / 2
    cell_half_y = target_cell_height / 2

    shift_x = sx * (cell_half_x - grid_half_x)
    shift_y = sy * (cell_half_y - grid_half_y)
    return fc.Vector(shift_x, shift_y, 0)


def _build_filler_ring_shape(
    params: BaseplateParams,
    geometry: GridfinityLayoutGeometry,
    options: BaseplateBuildOptions,
) -> Part.Shape:
    nx_exp = len(geometry.layout)
    ny_exp = len(geometry.layout[0])
    nx = nx_exp - 2
    ny = ny_exp - 2

    left_on = params.fillers.left_enabled and float(params.fillers.left_width) > 0
    right_on = params.fillers.right_enabled and float(params.fillers.right_width) > 0
    bottom_on = params.fillers.bottom_enabled and float(params.fillers.bottom_width) > 0
    top_on = params.fillers.top_enabled and float(params.fillers.top_width) > 0

    cache: dict[tuple[float, float, bool, bool, bool, bool], CoreCellBuildResult] = {}
    spring_slots = None
    if options.include_snap_springs and params.click_springs.enabled:
        spring_slots = feat.make_click_spring_shape_slots(
            params.fundamentals,
            params.click_springs,
        )

    def proto(
        width: float,
        height: float,
        *,
        leftmost: bool,
        rightmost: bool,
        bottommost: bool,
        topmost: bool,
    ) -> CoreCellBuildResult:
        key = (
            round(width, 6),
            round(height, 6),
            leftmost,
            rightmost,
            bottommost,
            topmost,
        )
        if key not in cache:
            filler_result = _build_filler_cell_shape(
                params,
                width,
                height,
                options,
            )
            cell = filler_result.shape
            if spring_slots is not None and not filler_result.is_tiny:
                align_shift = _filler_alignment_shift(
                    params,
                    leftmost=leftmost,
                    rightmost=rightmost,
                    bottommost=bottommost,
                    topmost=topmost,
                    target_cell_width=width,
                    target_cell_height=height,
                )
                cell.translate(align_shift)
                mask = _filler_spring_mask(
                    params,
                    leftmost=leftmost,
                    rightmost=rightmost,
                    bottommost=bottommost,
                    topmost=topmost,
                    target_cell_width=width,
                    target_cell_height=height,
                )
                cell = feat.apply_click_spring_slots_to_cell(
                    cell,
                    params.fundamentals,
                    params.core,
                    params.click_springs,
                    spring_slots,
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
            cache[key] = CoreCellBuildResult(shape=cell, is_tiny=filler_result.is_tiny)
        return cache[key]

    def center(ix: int, iy: int) -> fc.Vector:
        x = geometry.x_lines[ix] + (geometry.x_lines[ix + 1] - geometry.x_lines[ix]) / 2
        y = geometry.y_lines[iy] + (geometry.y_lines[iy + 1] - geometry.y_lines[iy]) / 2
        return fc.Vector(x, y, 0)

    pieces: list[Part.Shape] = []

    side_specs = [
        {
            "enabled": left_on,
            "width": geometry.x_lines[1] - geometry.x_lines[0],
            "height": geometry.y_lines[2] - geometry.y_lines[1],
            "flags": (True, False, False, False),
            "vectors": [center(0, iy) for iy in range(1, ny + 1)],
            "indices": [(0, iy) for iy in range(1, ny + 1)],
        },
        {
            "enabled": right_on,
            "width": geometry.x_lines[nx + 2] - geometry.x_lines[nx + 1],
            "height": geometry.y_lines[2] - geometry.y_lines[1],
            "flags": (False, True, False, False),
            "vectors": [center(nx + 1, iy) for iy in range(1, ny + 1)],
            "indices": [(nx + 1, iy) for iy in range(1, ny + 1)],
        },
        {
            "enabled": bottom_on,
            "width": geometry.x_lines[2] - geometry.x_lines[1],
            "height": geometry.y_lines[1] - geometry.y_lines[0],
            "flags": (False, False, True, False),
            "vectors": [center(ix, 0) for ix in range(1, nx + 1)],
            "indices": [(ix, 0) for ix in range(1, nx + 1)],
        },
        {
            "enabled": top_on,
            "width": geometry.x_lines[2] - geometry.x_lines[1],
            "height": geometry.y_lines[ny + 2] - geometry.y_lines[ny + 1],
            "flags": (False, False, False, True),
            "vectors": [center(ix, ny + 1) for ix in range(1, nx + 1)],
            "indices": [(ix, ny + 1) for ix in range(1, nx + 1)],
        },
    ]

    for spec in side_specs:
        if not spec["enabled"]:
            continue
        leftmost, rightmost, bottommost, topmost = spec["flags"]
        side_result = proto(
            spec["width"],
            spec["height"],
            leftmost=leftmost,
            rightmost=rightmost,
            bottommost=bottommost,
            topmost=topmost,
        )
        pieces.append(utils.copy_and_translate(side_result.shape, spec["vectors"]))
        for ix, iy in spec["indices"]:
            geometry.tiny[ix][iy] = side_result.is_tiny

    corner_specs = [
        {
            "enabled": left_on and bottom_on,
            "ix": 0,
            "iy": 0,
            "width": geometry.x_lines[1] - geometry.x_lines[0],
            "height": geometry.y_lines[1] - geometry.y_lines[0],
            "flags": (True, False, True, False),
        },
        {
            "enabled": left_on and top_on,
            "ix": 0,
            "iy": ny + 1,
            "width": geometry.x_lines[1] - geometry.x_lines[0],
            "height": geometry.y_lines[ny + 2] - geometry.y_lines[ny + 1],
            "flags": (True, False, False, True),
        },
        {
            "enabled": right_on and bottom_on,
            "ix": nx + 1,
            "iy": 0,
            "width": geometry.x_lines[nx + 2] - geometry.x_lines[nx + 1],
            "height": geometry.y_lines[1] - geometry.y_lines[0],
            "flags": (False, True, True, False),
        },
        {
            "enabled": right_on and top_on,
            "ix": nx + 1,
            "iy": ny + 1,
            "width": geometry.x_lines[nx + 2] - geometry.x_lines[nx + 1],
            "height": geometry.y_lines[ny + 2] - geometry.y_lines[ny + 1],
            "flags": (False, True, False, True),
        },
    ]

    for spec in corner_specs:
        if not spec["enabled"]:
            continue
        leftmost, rightmost, bottommost, topmost = spec["flags"]
        corner_result = proto(
            spec["width"],
            spec["height"],
            leftmost=leftmost,
            rightmost=rightmost,
            bottommost=bottommost,
            topmost=topmost,
        )
        corner = corner_result.shape.copy()
        corner.translate(center(spec["ix"], spec["iy"]))
        pieces.append(corner)
        geometry.tiny[spec["ix"]][spec["iy"]] = corner_result.is_tiny

    if not pieces:
        raise ValueError("No filler pieces generated")
    return utils.multi_fuse(pieces)


def _apply_layout_corner_roundover(
    shape: Part.Shape,
    params: BaseplateParams,
    layout: GridfinityLayout,
    x_lines: list[float],
    y_lines: list[float],
) -> Part.Shape:
    t0 = time.perf_counter()
    nx = len(layout)
    ny = len(layout[0])
    tol = 1e-6

    def cell(x: int, y: int) -> bool:
        if 0 <= x < nx and 0 <= y < ny:
            return bool(layout[x][y])
        return False

    corner_points: dict[tuple[float, float], int] = {}
    for ix in range(nx + 1):
        for iy in range(ny + 1):
            sw = cell(ix - 1, iy - 1)
            se = cell(ix, iy - 1)
            nw = cell(ix - 1, iy)
            ne = cell(ix, iy)
            populated = sw + se + nw + ne
            if populated not in (1, 3):
                continue
            x = x_lines[ix]
            y = y_lines[iy]
            corner_points[(x, y)] = populated
    t1 = time.perf_counter()

    if not corner_points:
        return shape

    def key_for(x: float, y: float) -> tuple[int, int]:
        return (int(round(x / tol)), int(round(y / tol)))

    target_keys = {key_for(x, y): populated for (x, y), populated in corner_points.items()}

    vertical_edges_by_key: dict[tuple[int, int], list[Part.Edge]] = {}
    for edge in shape.Edges:
        v0 = edge.Vertexes[0]
        v1 = edge.Vertexes[1]
        if abs(v0.Z - v1.Z) <= tol:
            continue
        if abs(v0.X - v1.X) > tol or abs(v0.Y - v1.Y) > tol:
            continue
        key = key_for(v0.X, v0.Y)
        if key in target_keys:
            vertical_edges_by_key.setdefault(key, []).append(edge)
    t2 = time.perf_counter()

    edges_pop1: list[Part.Edge] = []
    edges_pop3: list[Part.Edge] = []
    for key, populated in target_keys.items():
        edges = vertical_edges_by_key.get(key, [])
        if populated == 1:
            edges_pop1.extend(edges)
        else:
            edges_pop3.extend(edges)

    if not edges_pop1 and not edges_pop3:
        return shape

    rounded = shape
    if edges_pop1:
        try:
            rounded = rounded.makeFillet(params.fundamentals.bin_outer_radius, edges_pop1)
        except Part.OCCError:
            fc.Console.PrintError(
                "[Gridfinity] Baseplate corners roundover failed. Returning shape before roundover.\n"
            )
            return shape
    t3 = time.perf_counter()
    if edges_pop3:
        try:
            rounded = rounded.makeFillet(params.fundamentals.bin_outer_radius / 4, edges_pop3)
        except Part.OCCError:
            fc.Console.PrintError(
                "[Gridfinity] Baseplate corners roundover failed. Returning shape before roundover.\n"
            )
            return shape
    t4 = time.perf_counter()
    fc.Console.PrintMessage(
        "[Gridfinity Timing] roundover "
        f"corner_scan={t1 - t0:.3f}s "
        f"edge_match={t2 - t1:.3f}s "
        f"fillet_pop1={t3 - t2:.3f}s "
        f"fillet_pop3={t4 - t3:.3f}s "
        f"corners={len(corner_points)} "
        f"edges_pop1={len(edges_pop1)} "
        f"edges_pop3={len(edges_pop3)}\n"
    )
    return rounded


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
            geometry.layout,
            geometry.tiny,
            top_z,
            geometry=geometry,
        )
        if junction_holes is not None:
            cutters.append(junction_holes)

    if options.include_clip_cutouts:
        clip_cutouts = baseplate_feat.make_clip_cutouts_from_params(
            params.fundamentals,
            params.clip_cutouts,
            geometry.layout,
            geometry.tiny,
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
    spring_slots = feat.make_click_spring_shape_slots(
        params.fundamentals,
        params.click_springs,
    )
    return feat.apply_click_spring_slots_to_cell(
        shape,
        params.fundamentals,
        params.core,
        params.click_springs,
        spring_slots,
        feat.SpringSlotMask.all_true(),
    )


def build_simple_baseplate(
    obj: fc.DocumentObject,
    layout: GridfinityLayout,
    options: BaseplateBuildOptions,
) -> Part.Shape:
    params = params_from_obj(obj)
    return build_simple_baseplate_from_params(params, layout, options)


def build_simple_baseplate_from_params(
    params: BaseplateParams,
    layout: GridfinityLayout,
    options: BaseplateBuildOptions,
) -> Part.Shape:
    total_start = time.perf_counter()

    t0 = time.perf_counter()
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
        shape, geometry = add_filler_strips(empty_shape, params, layout, options)
        if shape.isNull():
            raise ValueError("No core cells and no fillers to build")
        if not options.use_preview_core:
            shape = baseplate_cell_top_crop(shape, params)
            shape = _apply_layout_corner_roundover(
                shape,
                params,
                geometry.layout,
                geometry.x_lines,
                geometry.y_lines,
            )
        return shape

    core_result = (
        build_preview_single_cell_baseplate_core(params)
        if options.use_preview_core
        else build_single_cell_baseplate_core(params, options)
    )
    shape = core_result.shape
    t1 = time.perf_counter()

    if not options.use_preview_core and not core_result.is_tiny:
        shape = apply_snap_springs(shape, params, options)
    if not options.use_preview_core:
        shape = baseplate_cell_top_crop(shape, params)
    t2 = time.perf_counter()

    shape = replicate_layout(shape, params, layout)
    t3 = time.perf_counter()

    shape, geometry = add_filler_strips(shape, params, layout, options)
    x_offset = 1 if len(geometry.layout) == nx + 2 else 0
    y_offset = 1 if len(geometry.layout[0]) == ny + 2 else 0
    for ix in range(nx):
        for iy in range(ny):
            gx = ix + x_offset
            gy = iy + y_offset
            if geometry.layout[gx][gy]:
                geometry.tiny[gx][gy] = core_result.is_tiny
    t3a = time.perf_counter()

    if not options.use_preview_core:
        shape = _apply_layout_corner_roundover(
            shape,
            params,
            geometry.layout,
            geometry.x_lines,
            geometry.y_lines,
        )
    t3b = time.perf_counter()

    t4 = time.perf_counter()
    if options.use_preview_core:
        t5 = t4
        t6 = t4
    else:
        top_z = (
            max(v.Z for v in shape.Vertexes) * fc.Units.Quantity("1 mm")
            if shape.Vertexes
            else 0 * fc.Units.Quantity("1 mm")
        )
        post_cutter = make_post_replication_cutter(params, geometry, options, top_z)
        t5 = time.perf_counter()
        if post_cutter is not None:
            shape = shape.cut(post_cutter)
        t6 = time.perf_counter()

    fc.Console.PrintMessage(
        "[Gridfinity Timing] baseplate "
        f"core={t1 - t0:.3f}s "
        f"springs={t2 - t1:.3f}s "
        f"replicate={t3 - t2:.3f}s "
        f"filler={t3a - t3:.3f}s "
        f"roundover={t3b - t3a:.3f}s "
        f"build_cutter={t5 - t4:.3f}s "
        f"post_cut={t6 - t5:.3f}s "
        f"total={t6 - total_start:.3f}s\n"
    )
    return shape
