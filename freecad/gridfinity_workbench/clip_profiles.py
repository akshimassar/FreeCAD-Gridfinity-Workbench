"""Clip and clip-cutout profile builders."""

from __future__ import annotations

import FreeCAD as fc  # noqa: N813
import Part


def _profile_scales(
    half_width: fc.Units.Quantity, height: fc.Units.Quantity
) -> tuple[float, float]:
    scale_y = half_width / (2.15 * fc.Units.Quantity("1 mm"))
    scale_z = height / (2.5 * fc.Units.Quantity("1 mm"))
    return scale_y, scale_z


def _scale_profile_yz(y: float, z: float, scale_y: float, scale_z: float) -> fc.Vector:
    return fc.Vector(0, y * scale_y, z * scale_z)


def build_clip_profile_wire(
    half_width: fc.Units.Quantity,
    height: fc.Units.Quantity,
    tolerance: fc.Units.Quantity,
) -> Part.Wire:
    """Build the arc-based connecting clip profile in YZ plane."""
    scale_y, scale_z = _profile_scales(half_width, height)
    t_world = tolerance / fc.Units.Quantity("1 mm")
    t_ref_y = (t_world / scale_y).Value
    t_ref_z = (t_world / scale_z).Value

    a = _scale_profile_yz(-0.7 - t_ref_y, 2.5, scale_y, scale_z)
    b = _scale_profile_yz(0.7 + t_ref_y, 2.5, scale_y, scale_z)
    d = _scale_profile_yz(0.6 + t_ref_y, 0.0 + t_ref_z, scale_y, scale_z)
    e = _scale_profile_yz(1.9 - t_ref_y, 0.0 + t_ref_z, scale_y, scale_z)
    f = _scale_profile_yz(1.9 - t_ref_y, 2.5, scale_y, scale_z)
    g = _scale_profile_yz(-1.9 + t_ref_y, 2.5, scale_y, scale_z)
    h = _scale_profile_yz(-1.9 + t_ref_y, 0.0 + t_ref_z, scale_y, scale_z)
    i = _scale_profile_yz(-0.6 - t_ref_y, 0.0 + t_ref_z, scale_y, scale_z)

    arc1 = Part.Arc(
        a,
        _scale_profile_yz(0.0, (2.5 + 0.7) + t_ref_z, scale_y, scale_z),
        b,
    ).toShape()
    line1 = Part.LineSegment(b, d).toShape()
    line2 = Part.LineSegment(d, e).toShape()
    line3 = Part.LineSegment(e, f).toShape()
    arc2 = Part.Arc(
        f,
        _scale_profile_yz(0.0, (2.5 + 1.9) - t_ref_z, scale_y, scale_z),
        g,
    ).toShape()
    line4 = Part.LineSegment(g, h).toShape()
    line5 = Part.LineSegment(h, i).toShape()
    line6 = Part.LineSegment(i, a).toShape()

    return Part.Wire([arc1, line1, line2, line3, arc2, line4, line5, line6])


def build_clip_cutout_profile_wire(
    half_width: fc.Units.Quantity,
    height: fc.Units.Quantity,
) -> Part.Wire:
    """Build clip cutout profile wire in YZ plane."""
    scale_y, scale_z = _profile_scales(half_width, height)

    forward = [
        (0.0, 10.0),
        (1.9, 10.0),
        (1.9, 0.0),
        (0.6, 0.0),
        (0.7, 2.4),
        (0.2, 2.9),
        (0.0, 2.9),
    ]
    mirrored = [(-y, z) for y, z in reversed(forward[1:-1])]
    ref_points = forward + mirrored + [forward[0]]
    pts = [_scale_profile_yz(y, z, scale_y, scale_z) for y, z in ref_points]
    return Part.Wire(Part.makePolygon(pts))
