"""Build pipeline for simple baseplate geometry."""

from __future__ import annotations

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
    base_cell = shape.copy()
    base_cell.translate(fc.Vector(obj.xGridSize / 2, obj.yGridSize / 2, 0))
    replicated = utils.copy_in_layout(base_cell, layout, obj.xGridSize, obj.yGridSize)
    replicated = replicated.removeSplitter()
    replicated = replicated.translate(
        fc.Vector(-obj.xLocationOffset, -obj.yLocationOffset),
    )
    return _apply_layout_corner_roundover(replicated, obj, layout)


def _apply_layout_corner_roundover(
    shape: Part.Shape,
    obj: fc.DocumentObject,
    layout: GridfinityLayout,
) -> Part.Shape:
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

    if not corner_points:
        return shape

    edges_pop1 = []
    edges_pop3 = []
    for edge in shape.Edges:
        v0 = edge.Vertexes[0]
        v1 = edge.Vertexes[1]
        if abs(v0.Z - v1.Z) <= tol:
            continue
        if abs(v0.X - v1.X) > tol or abs(v0.Y - v1.Y) > tol:
            continue
        for (px, py), populated in corner_points.items():
            if abs(v0.X - px) <= tol and abs(v0.Y - py) <= tol:
                if populated == 1:
                    edges_pop1.append(edge)
                else:
                    edges_pop3.append(edge)
                break

    if not edges_pop1 and not edges_pop3:
        return shape

    rounded = shape
    if edges_pop1:
        rounded = rounded.makeFillet(obj.BinOuterRadius, edges_pop1)
    if edges_pop3:
        rounded = rounded.makeFillet(obj.BinOuterRadius / 4, edges_pop3)
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
    shape = build_single_cell_baseplate_core(obj, options)
    shape = apply_snap_springs(shape, obj, options)
    shape = replicate_layout(shape, obj, layout)
    shape = apply_junction_screws(shape, obj, layout, options)
    shape = apply_clip_cutouts(shape, obj, layout, options)
    return shape
