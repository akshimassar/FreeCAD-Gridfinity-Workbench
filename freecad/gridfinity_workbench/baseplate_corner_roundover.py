"""Corner roundover profile generation for baseplate layouts."""

from __future__ import annotations

import FreeCAD as fc  # noqa: N813
import Part

from . import utils
from .baseplate_full_layout import (
    BoolMatrix2x2,
    GridfinityLayoutGeometry,
    ShapeMatrix2x2,
    expand_seed_to_shape_matrix,
)


class BaseplateCornerRoundover:
    def __init__(self, outside_radius: float) -> None:
        self.outside_radius = float(outside_radius)
        self.inside_radius = self.outside_radius / 4.0
        self._outside_matrix = self._build_from_seed(self._make_corner_seed(self.outside_radius))
        self._inside_matrix = self._build_from_seed(self._make_corner_seed(self.inside_radius))

    @staticmethod
    def _make_corner_seed(radius: float) -> Part.Shape:
        p0 = fc.Vector(0, 0, 0)
        start = fc.Vector(radius, 0, 0)
        end = fc.Vector(0, radius, 0)
        center = fc.Vector(radius, radius, 0)
        arc = Part.makeCircle(radius, center, fc.Vector(0, 0, 1), 180, 270)
        edges = [
            Part.LineSegment(start, p0).toShape(),
            Part.LineSegment(p0, end).toShape(),
            arc,
        ]
        return Part.Face(Part.Wire(edges))

    @staticmethod
    def _build_from_seed(seed: Part.Shape) -> ShapeMatrix2x2:
        return expand_seed_to_shape_matrix(seed)

    def get_corner_profiles(
        self, populated_2x2: BoolMatrix2x2
    ) -> tuple[Part.Shape | None, Part.Shape | None]:
        if populated_2x2.count_true() == 1:
            return self._outside_matrix.select_single(populated_2x2), None
        if populated_2x2.count_true() == 3:
            return None, self._inside_matrix.select_single(populated_2x2.negated())
        return None, None


def apply_layout_corner_roundover(
    shape: Part.Shape,
    *,
    geometry: GridfinityLayoutGeometry,
    outside_radius: float,
    height: float,
) -> Part.Shape:
    if height <= 0:
        return shape

    nx, ny = geometry.size()

    roundover = BaseplateCornerRoundover(outside_radius)
    negative_profiles: list[Part.Shape] = []
    positive_profiles: list[Part.Shape] = []
    for ix in range(nx + 1):
        for iy in range(ny + 1):
            neighbours = geometry.junction_neighbours(ix, iy)
            populated_2x2 = neighbours.exists()
            negative_profile, positive_profile = roundover.get_corner_profiles(populated_2x2)
            if negative_profile is None and positive_profile is None:
                continue
            translation = fc.Vector(geometry.line_x(ix), geometry.line_y(iy), 0)
            if negative_profile is not None:
                prof = negative_profile.copy()
                prof.translate(translation)
                negative_profiles.append(prof)
            if positive_profile is not None:
                prof = positive_profile.copy()
                prof.translate(translation)
                positive_profiles.append(prof)

    if not negative_profiles and not positive_profiles:
        return shape

    extrude_vec = fc.Vector(0, 0, float(height))
    out = shape
    if negative_profiles:
        negative_solids: list[Part.Shape] = [
            profile.extrude(extrude_vec) for profile in negative_profiles
        ]
        negative_shape = (
            utils.multi_fuse(negative_solids) if len(negative_solids) > 1 else negative_solids[0]
        )
        out = out.cut(negative_shape)
    if positive_profiles:
        positive_solids: list[Part.Shape] = [
            profile.extrude(extrude_vec) for profile in positive_profiles
        ]
        positive_shape = (
            utils.multi_fuse(positive_solids) if len(positive_solids) > 1 else positive_solids[0]
        )
        out = out.fuse(positive_shape)
    return out
