"""Corner roundover profile generation for baseplate layouts."""

from __future__ import annotations

import FreeCAD as fc  # noqa: N813
import Part

from . import utils

ShapeMatrix2x2 = list[list[Part.Shape]]
BoolMatrix2x2 = list[list[bool]]


class BaseplateCornerRoundover:
    def __init__(self, outside_radius: float) -> None:
        self.outside_radius = float(outside_radius)
        self.inside_radius = self.outside_radius / 4.0
        self._outside_matrix = self._build_profile_matrix(
            self._make_corner_seed(self.outside_radius)
        )
        self._inside_matrix = self._build_profile_matrix(self._make_corner_seed(self.inside_radius))

    @staticmethod
    def _make_corner_seed(radius: float) -> Part.Shape:
        start = fc.Vector(radius, 0, 0)
        p0 = fc.Vector(0, 0, 0)
        p1 = fc.Vector(0, radius, 0)
        mid = fc.Vector(radius * 0.2928932188134524, radius * 0.2928932188134524, 0)
        arc = Part.Arc(p1, mid, start).toShape()
        edges = [
            Part.LineSegment(start, p0).toShape(),
            Part.LineSegment(p0, p1).toShape(),
            arc,
        ]
        return Part.Face(Part.Wire(edges))

    @staticmethod
    def _build_profile_matrix(seed: Part.Shape) -> ShapeMatrix2x2:
        def mirror_x(shape: Part.Shape) -> Part.Shape:
            return shape.mirror(fc.Vector(0, 0, 0), fc.Vector(1, 0, 0))

        def mirror_y(shape: Part.Shape) -> Part.Shape:
            return shape.mirror(fc.Vector(0, 0, 0), fc.Vector(0, 1, 0))

        matrix: ShapeMatrix2x2 = [[None, None], [None, None]]  # type: ignore[assignment]
        matrix[1][0] = seed
        matrix[0][0] = mirror_x(matrix[1][0])
        matrix[0][1] = mirror_y(matrix[0][0])
        matrix[1][1] = mirror_y(matrix[1][0])
        return matrix

    @staticmethod
    def _find_single(matrix: BoolMatrix2x2, value: bool) -> tuple[int, int] | None:
        found: tuple[int, int] | None = None
        for x in range(2):
            for y in range(2):
                if matrix[x][y] is value:
                    if found is not None:
                        return None
                    found = (x, y)
        return found

    def get_corner_profiles(
        self, populated_2x2: BoolMatrix2x2
    ) -> tuple[Part.Shape | None, Part.Shape | None]:
        populated_count = sum(1 for x in range(2) for y in range(2) if populated_2x2[x][y])
        if populated_count == 1:
            idx = self._find_single(populated_2x2, True)
            if idx is None:
                return None, None
            x, y = idx
            return self._outside_matrix[x][y].copy(), None
        if populated_count == 3:
            idx = self._find_single(populated_2x2, False)
            if idx is None:
                return None, None
            x, y = idx
            return None, self._inside_matrix[x][y].copy()
        return None, None


def apply_layout_corner_roundover(
    shape: Part.Shape,
    *,
    layout: list[list[bool]],
    x_lines: list[float],
    y_lines: list[float],
    outside_radius: float,
    height: float,
) -> Part.Shape:
    if height <= 0:
        return shape

    nx = len(layout)
    ny = len(layout[0]) if nx > 0 else 0

    def cell(x: int, y: int) -> bool:
        if 0 <= x < nx and 0 <= y < ny:
            return bool(layout[x][y])
        return False

    roundover = BaseplateCornerRoundover(outside_radius)
    negative_profiles: list[Part.Shape] = []
    positive_profiles: list[Part.Shape] = []
    for ix in range(nx + 1):
        for iy in range(ny + 1):
            populated_2x2 = [
                [cell(ix - 1, iy), cell(ix - 1, iy - 1)],
                [cell(ix, iy), cell(ix, iy - 1)],
            ]
            negative_profile, positive_profile = roundover.get_corner_profiles(populated_2x2)
            if negative_profile is None and positive_profile is None:
                continue
            translation = fc.Vector(x_lines[ix], y_lines[iy], 0)
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
        negative_solids = [profile.extrude(extrude_vec) for profile in negative_profiles]
        negative_shape = (
            utils.multi_fuse(negative_solids) if len(negative_solids) > 1 else negative_solids[0]
        )
        out = out.cut(negative_shape)
    if positive_profiles:
        positive_solids = [profile.extrude(extrude_vec) for profile in positive_profiles]
        positive_shape = (
            utils.multi_fuse(positive_solids) if len(positive_solids) > 1 else positive_solids[0]
        )
        out = out.fuse(positive_shape)
    return out
