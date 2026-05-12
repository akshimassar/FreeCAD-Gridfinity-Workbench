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


def build_baseplate_core(obj: fc.DocumentObject, layout: GridfinityLayout) -> Part.Shape:
    baseplate_outside_shape = utils.create_rounded_rectangle(
        obj.xTotalWidth,
        obj.yTotalWidth,
        0,
        obj.BinOuterRadius,
    )
    baseplate_outside_shape.translate(fc.Vector(obj.xTotalWidth / 2, obj.yTotalWidth / 2, 0))

    solid_shape = baseplate_feat.make_solid_shape(
        obj,
        baseplate_outside_shape,
        baseplate_type="standard",
    )

    cutout = feat.make_complex_bin_base(obj, layout, for_cutout=True)
    cutout.translate(fc.Vector(0, 0, obj.TotalHeight))
    return solid_shape.cut(cutout)


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
    layout: GridfinityLayout,
    options: BaseplateBuildOptions,
) -> Part.Shape:
    if not options.include_snap_springs:
        return shape
    springs = feat.make_click_springs_two_sides(obj, layout)
    springs = feat.trim_click_springs_to_top_crop(obj, springs)
    return shape.fuse(springs).removeSplitter()


def build_simple_baseplate(
    obj: fc.DocumentObject,
    layout: GridfinityLayout,
    options: BaseplateBuildOptions,
) -> Part.Shape:
    shape = build_baseplate_core(obj, layout)
    shape = apply_junction_screws(shape, obj, layout, options)
    shape = apply_clip_cutouts(shape, obj, layout, options)
    shape = apply_snap_springs(shape, obj, layout, options)
    return shape
