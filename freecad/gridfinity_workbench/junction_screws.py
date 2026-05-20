"""Unified junction screw selection and shape builders."""

from __future__ import annotations

import FreeCAD as fc  # noqa: N813
import Part

from .baseplate_full_layout import GridfinityLayoutGeometry
from .baseplate_params import JunctionScrewParams, ScrewStubParams


def iter_supported_junctions(geometry: GridfinityLayoutGeometry) -> list[tuple[float, float]]:
    nx, ny = geometry.size()
    points: list[tuple[float, float]] = []
    for ix in range(1, nx):
        for iy in range(1, ny):
            neighbours = geometry.junction_neighbours(ix, iy)
            if neighbours.count_true() != 4:
                continue
            if neighbours.has_tiny():
                continue
            points.append((geometry.line_x(ix), geometry.line_y(iy)))
    return points


def holes_shape(
    junction_screws: JunctionScrewParams,
    top_z: fc.Units.Quantity,
    geometry: GridfinityLayoutGeometry,
) -> Part.Shape | None:
    through_depth = top_z + 0.1 * fc.Units.Quantity("1 mm")
    cutters: list[Part.Shape] = []
    for x, y in iter_supported_junctions(geometry):
        through = Part.makeCylinder(
            junction_screws.screw_diameter / 2,
            through_depth,
            fc.Vector(x, y, top_z),
            fc.Vector(0, 0, -1),
        )
        counterbore = Part.makeCylinder(
            junction_screws.counterbore_diameter / 2,
            junction_screws.counterbore_depth,
            fc.Vector(x, y, top_z),
            fc.Vector(0, 0, -1),
        )
        transition_height = (
            junction_screws.counterbore_diameter - junction_screws.screw_diameter
        ) / 2
        transition = Part.makeCone(
            junction_screws.counterbore_diameter / 2,
            junction_screws.screw_diameter / 2,
            transition_height,
            fc.Vector(x, y, top_z - junction_screws.counterbore_depth),
            fc.Vector(0, 0, -1),
        )
        cutters.extend([through, counterbore, transition])
    if not cutters:
        return None
    return cutters[0].multiFuse(cutters[1:]) if len(cutters) > 1 else cutters[0]


def stubs_shape(
    junction_screws: JunctionScrewParams,
    screw_stubs: ScrewStubParams,
    bottom_z: fc.Units.Quantity,
    geometry: GridfinityLayoutGeometry,
) -> Part.Shape | None:
    stub_diameter = junction_screws.screw_diameter - screw_stubs.clearance
    counterbore_diameter = junction_screws.counterbore_diameter - screw_stubs.clearance
    transition_height = (counterbore_diameter - stub_diameter) / 2
    if (
        float(stub_diameter) <= 0
        or float(counterbore_diameter) <= 0
        or float(transition_height) <= 0
    ):
        return None

    stubs: list[Part.Shape] = []
    for x, y in iter_supported_junctions(geometry):
        counterbore = Part.makeCylinder(
            counterbore_diameter / 2,
            junction_screws.counterbore_depth,
            fc.Vector(x, y, bottom_z),
            fc.Vector(0, 0, -1),
        )
        transition = Part.makeCone(
            counterbore_diameter / 2,
            stub_diameter / 2,
            transition_height,
            fc.Vector(x, y, bottom_z - junction_screws.counterbore_depth),
            fc.Vector(0, 0, -1),
        )
        stubs.extend([counterbore, transition])
    if not stubs:
        return None
    return stubs[0].multiFuse(stubs[1:]) if len(stubs) > 1 else stubs[0]
