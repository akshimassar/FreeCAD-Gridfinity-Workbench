"""Build pipeline for simple baseplate geometry."""

from __future__ import annotations

import time
from dataclasses import dataclass

import FreeCAD as fc  # noqa: N813
import Part

from . import baseplate_feature_construction as baseplate_feat
from . import feature_construction as feat
from . import utils
from .utils import GridfinityLayout


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
    t0 = time.perf_counter()
    base_cell = shape.copy()
    base_cell.translate(fc.Vector(obj.xGridSize / 2, obj.yGridSize / 2, 0))
    t1 = time.perf_counter()
    replicated = utils.copy_in_layout(base_cell, layout, obj.xGridSize, obj.yGridSize)
    t2 = time.perf_counter()
    # Intentionally skip global refine/removeSplitter here for performance.
    t3 = time.perf_counter()
    replicated = replicated.translate(
        fc.Vector(-obj.xLocationOffset, -obj.yLocationOffset),
    )
    t4 = time.perf_counter()
    rounded = _apply_layout_corner_roundover(replicated, obj, layout)
    t5 = time.perf_counter()
    fc.Console.PrintMessage(
        "[Gridfinity Timing] replicate "
        f"copy={t2 - t1:.3f}s "
        f"cleanup={t3 - t2:.3f}s "
        f"offset={t4 - t3:.3f}s "
        f"roundover={t5 - t4:.3f}s "
        f"total={t5 - t0:.3f}s\n"
    )
    return rounded


def _apply_layout_corner_roundover(
    shape: Part.Shape,
    obj: fc.DocumentObject,
    layout: GridfinityLayout,
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
            x = float(ix * obj.xGridSize - obj.xLocationOffset)
            y = float(iy * obj.yGridSize - obj.yLocationOffset)
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
    layout: GridfinityLayout,
    options: BaseplateBuildOptions,
) -> Part.Shape | None:
    cutters: list[Part.Shape] = []

    if options.include_junction_screws:
        junction_holes = baseplate_feat.make_junction_screw_holes(obj, layout)
        if junction_holes is not None:
            cutters.append(junction_holes)

    if options.include_clip_cutouts:
        clip_cutouts = baseplate_feat.make_clip_cutouts(obj, layout)
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

    t4 = time.perf_counter()
    post_cutter = make_post_replication_cutter(obj, layout, options)
    t5 = time.perf_counter()
    if post_cutter is not None:
        shape = shape.cut(post_cutter)
    t6 = time.perf_counter()

    fc.Console.PrintMessage(
        "[Gridfinity Timing] baseplate "
        f"core={t1 - t0:.3f}s "
        f"springs={t2 - t1:.3f}s "
        f"replicate_round={t3 - t2:.3f}s "
        f"build_cutter={t5 - t4:.3f}s "
        f"post_cut={t6 - t5:.3f}s "
        f"total={t6 - total_start:.3f}s\n"
    )
    return shape
