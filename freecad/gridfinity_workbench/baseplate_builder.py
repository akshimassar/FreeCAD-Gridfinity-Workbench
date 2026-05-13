"""Build pipeline for simple baseplate geometry."""

from __future__ import annotations

import time
from dataclasses import dataclass

import FreeCAD as fc  # noqa: N813
import Part

from . import baseplate_feature_construction as baseplate_feat
from . import feature_construction as feat
from . import utils
from .utils import GridfinityLayout, GridfinityLayoutGeometry


@dataclass
class BaseplateBuildOptions:
    include_junction_screws: bool = True
    include_clip_cutouts: bool = True
    include_snap_springs: bool = True


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


def build_single_cell_baseplate_core(
    obj: fc.DocumentObject, options: BaseplateBuildOptions
) -> Part.Shape:
    baseplate_outside_shape = _create_rectangle_wire(obj.xGridSize, obj.yGridSize)

    solid_shape = baseplate_feat.make_solid_shape(
        obj,
        baseplate_outside_shape,
        baseplate_type="standard",
    )

    cutout = feat.make_complex_bin_base_single(obj, for_cutout=True)
    cutout.translate(fc.Vector(0, 0, obj.TotalHeight))
    return solid_shape.cut(cutout)


def replicate_layout(
    shape: Part.Shape, obj: fc.DocumentObject, layout: GridfinityLayout
) -> Part.Shape:
    nx = len(layout)
    ny = len(layout[0])
    x_lines = _build_grid_lines([obj.xGridSize] * nx)
    y_lines = _build_grid_lines([obj.yGridSize] * ny)
    replicated = _replicate_layout_variable(shape, layout, x_lines, y_lines)
    replicated = replicated.translate(fc.Vector(-obj.xLocationOffset, -obj.yLocationOffset, 0))
    return replicated


def add_filler_strips(
    shape: Part.Shape,
    obj: fc.DocumentObject,
    layout: GridfinityLayout,
    options: BaseplateBuildOptions,
) -> tuple[Part.Shape, GridfinityLayoutGeometry]:
    expanded = _build_expanded_layout_with_fillers(obj, layout)
    has_fillers = len(expanded.layout) != len(layout) or len(expanded.layout[0]) != len(layout[0])
    if not has_fillers:
        return shape, expanded

    nx = len(expanded.layout)
    ny = len(expanded.layout[0])
    ring_only: GridfinityLayout = [[False for _ in range(ny)] for _ in range(nx)]
    for ix in range(nx):
        for iy in range(ny):
            if not expanded.layout[ix][iy]:
                continue
            if ix == 0 or iy == 0 or ix == nx - 1 or iy == ny - 1:
                ring_only[ix][iy] = True

    filler_shape = _replicate_layout_variable_generated(
        obj,
        ring_only,
        expanded.x_lines,
        expanded.y_lines,
        options,
        include_springs=False,
    )
    filler_shape = filler_shape.translate(fc.Vector(-obj.xLocationOffset, -obj.yLocationOffset, 0))
    combined = shape.fuse(filler_shape).removeSplitter()
    return combined, expanded


def _build_expanded_layout_with_fillers(
    obj: fc.DocumentObject,
    layout: GridfinityLayout,
) -> GridfinityLayoutGeometry:
    nx = len(layout)
    ny = len(layout[0])

    left_w = (
        obj.FillerLeftWidth if bool(getattr(obj, "FillerLeftEnabled", False)) else 0 * obj.xGridSize
    )
    right_w = (
        obj.FillerRightWidth
        if bool(getattr(obj, "FillerRightEnabled", False))
        else 0 * obj.xGridSize
    )
    bottom_w = (
        obj.FillerBottomWidth
        if bool(getattr(obj, "FillerBottomEnabled", False))
        else 0 * obj.yGridSize
    )
    top_w = (
        obj.FillerTopWidth if bool(getattr(obj, "FillerTopEnabled", False)) else 0 * obj.yGridSize
    )

    use_fillers = any(float(v) > 0 for v in (left_w, right_w, bottom_w, top_w))
    if not use_fillers:
        return GridfinityLayoutGeometry(
            layout=[[bool(layout[ix][iy]) for iy in range(ny)] for ix in range(nx)],
            x_lines=_build_grid_lines([obj.xGridSize] * nx),
            y_lines=_build_grid_lines([obj.yGridSize] * ny),
        )

    x_sizes: list[fc.Units.Quantity] = [left_w] + [obj.xGridSize] * nx + [right_w]
    y_sizes: list[fc.Units.Quantity] = [bottom_w] + [obj.yGridSize] * ny + [top_w]

    expanded: GridfinityLayout = [[False for _ in range(ny + 2)] for _ in range(nx + 2)]

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
        x_lines=_build_grid_lines(x_sizes),
        y_lines=_build_grid_lines(y_sizes),
    )


def _build_grid_lines(sizes: list[fc.Units.Quantity]) -> list[float]:
    lines = [0.0]
    total = 0.0
    for size in sizes:
        total += float(size)
        lines.append(total)
    return lines


def _replicate_layout_variable(
    base_shape: Part.Shape,
    layout: GridfinityLayout,
    x_lines: list[float],
    y_lines: list[float],
) -> Part.Shape:
    nx = len(layout)
    ny = len(layout[0])
    pieces: list[Part.Shape] = []
    if len(x_lines) < 2 or len(y_lines) < 2:
        raise ValueError("Invalid grid lines")
    base_w = x_lines[1] - x_lines[0]
    base_h = y_lines[1] - y_lines[0]
    for ix in range(nx):
        cell_w = x_lines[ix + 1] - x_lines[ix]
        cx = x_lines[ix] + cell_w / 2
        for iy in range(ny):
            if not layout[ix][iy]:
                continue
            cell_h = y_lines[iy + 1] - y_lines[iy]
            cy = y_lines[iy] + cell_h / 2
            scale = fc.Matrix()
            scale.scale(cell_w / base_w, cell_h / base_h, 1)
            cell_shape = base_shape.transformGeometry(scale)
            cell_shape.translate(fc.Vector(cx, cy, 0))
            pieces.append(cell_shape)

    if not pieces:
        raise ValueError("Layout is empty")
    return pieces[0].multiFuse(pieces[1:]) if len(pieces) > 1 else pieces[0]


def _build_cell_shape_for_size(
    obj: fc.DocumentObject,
    x_size: float,
    y_size: float,
    options: BaseplateBuildOptions,
    *,
    include_springs: bool,
) -> Part.Shape:
    old_x = obj.xGridSize
    old_y = obj.yGridSize
    try:
        obj.xGridSize = x_size
        obj.yGridSize = y_size
        cell = build_single_cell_baseplate_core(obj, options)
        if include_springs:
            cell = apply_snap_springs(cell, obj, options)
        return cell
    finally:
        obj.xGridSize = old_x
        obj.yGridSize = old_y


def _replicate_layout_variable_generated(
    obj: fc.DocumentObject,
    layout: GridfinityLayout,
    x_lines: list[float],
    y_lines: list[float],
    options: BaseplateBuildOptions,
    *,
    include_springs: bool,
) -> Part.Shape:
    nx = len(layout)
    ny = len(layout[0])
    pieces: list[Part.Shape] = []
    cache: dict[tuple[float, float, bool], Part.Shape] = {}

    for ix in range(nx):
        cell_w = x_lines[ix + 1] - x_lines[ix]
        cx = x_lines[ix] + cell_w / 2
        for iy in range(ny):
            if not layout[ix][iy]:
                continue
            cell_h = y_lines[iy + 1] - y_lines[iy]
            cy = y_lines[iy] + cell_h / 2

            key = (round(cell_w, 6), round(cell_h, 6), include_springs)
            if key not in cache:
                cache[key] = _build_cell_shape_for_size(
                    obj,
                    cell_w,
                    cell_h,
                    options,
                    include_springs=include_springs,
                )

            cell_shape = cache[key].copy()
            cell_shape.translate(fc.Vector(cx, cy, 0))
            pieces.append(cell_shape)

    if not pieces:
        raise ValueError("Layout is empty")
    return pieces[0].multiFuse(pieces[1:]) if len(pieces) > 1 else pieces[0]


def _apply_layout_corner_roundover(
    shape: Part.Shape,
    obj: fc.DocumentObject,
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
            x = x_lines[ix] - float(obj.xLocationOffset)
            y = y_lines[iy] - float(obj.yLocationOffset)
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
        rounded = rounded.makeFillet(obj.BinOuterRadius, edges_pop1)
    t3 = time.perf_counter()
    if edges_pop3:
        rounded = rounded.makeFillet(obj.BinOuterRadius / 4, edges_pop3)
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
    obj: fc.DocumentObject,
    geometry: GridfinityLayoutGeometry,
    options: BaseplateBuildOptions,
) -> Part.Shape | None:
    cutters: list[Part.Shape] = []

    if options.include_junction_screws:
        junction_holes = baseplate_feat.make_junction_screw_holes(
            obj,
            geometry.layout,
            geometry=geometry,
        )
        if junction_holes is not None:
            cutters.append(junction_holes)

    if options.include_clip_cutouts:
        clip_cutouts = baseplate_feat.make_clip_cutouts(
            obj,
            geometry.layout,
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
    obj: fc.DocumentObject,
    options: BaseplateBuildOptions,
) -> Part.Shape:
    if not options.include_snap_springs:
        return shape
    spring_cutouts = feat.add_click_spring_notches_to_base_cutout_single(
        obj,
        feat.make_complex_bin_base_single(obj, for_cutout=True),
    )
    spring_cutouts.translate(fc.Vector(0, 0, obj.TotalHeight))
    shape = shape.cut(spring_cutouts)
    springs = feat.make_click_springs_two_sides_single(obj)
    springs = feat.trim_click_springs_to_top_crop(obj, springs)
    return shape.fuse(springs).removeSplitter()


def build_simple_baseplate(
    obj: fc.DocumentObject,
    layout: GridfinityLayout,
    options: BaseplateBuildOptions,
) -> Part.Shape:
    total_start = time.perf_counter()

    t0 = time.perf_counter()
    shape = build_single_cell_baseplate_core(obj, options)
    t1 = time.perf_counter()

    shape = apply_snap_springs(shape, obj, options)
    t2 = time.perf_counter()

    shape = replicate_layout(shape, obj, layout)
    t3 = time.perf_counter()

    shape, geometry = add_filler_strips(shape, obj, layout, options)
    t3a = time.perf_counter()

    shape = _apply_layout_corner_roundover(
        shape,
        obj,
        geometry.layout,
        geometry.x_lines,
        geometry.y_lines,
    )
    t3b = time.perf_counter()

    t4 = time.perf_counter()
    post_cutter = make_post_replication_cutter(obj, geometry, options)
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
