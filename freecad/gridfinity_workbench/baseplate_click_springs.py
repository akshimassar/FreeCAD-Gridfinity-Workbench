"""Shared click spring geometry for baseplate and baseplate support generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import FreeCAD as fc  # noqa: N813
import Part

from . import utils
from .baseplate_full_layout import BoolMatrix2x2, ShapeMatrix2x2, expand_seed_to_shape_matrix

if TYPE_CHECKING:
    from .param import BaseplateCoreParamsData, ClickSpringParamsData, FundamentalsParamsData

unitmm = fc.Units.Quantity("1 mm")

_MATRIX_2X2_SIZE = 2


def _assert_2x2_shape_matrix(name: str, matrix: ShapeMatrix2x2) -> None:
    if len(matrix) != _MATRIX_2X2_SIZE or any(len(col) != _MATRIX_2X2_SIZE for col in matrix):
        raise ValueError(f"{name} must be a 2x2 shape matrix")


@dataclass(frozen=True)
class SpringSlotMask:
    """Selection mask for vertical/horizontal spring slots with X-first indexing."""

    vertical_slots: BoolMatrix2x2
    horizontal_slots: BoolMatrix2x2

    @classmethod
    def all_true(cls) -> SpringSlotMask:
        """Create a mask with all slots enabled."""
        return cls(
            vertical_slots=BoolMatrix2x2([[True, True], [True, True]]),
            horizontal_slots=BoolMatrix2x2([[True, True], [True, True]]),
        )

    def with_vertical_disabled(self, disable: BoolMatrix2x2) -> SpringSlotMask:
        """Return a new mask with specified vertical slots disabled."""
        matrix = BoolMatrix2x2(
            [
                [self.vertical_slots[x][y] and (not disable[x][y]) for y in range(2)]
                for x in range(2)
            ],
        )
        return SpringSlotMask(vertical_slots=matrix, horizontal_slots=self.horizontal_slots)

    def with_horizontal_disabled(self, disable: BoolMatrix2x2) -> SpringSlotMask:
        """Return a new mask with specified horizontal slots disabled."""
        matrix = BoolMatrix2x2(
            [
                [self.horizontal_slots[x][y] and (not disable[x][y]) for y in range(2)]
                for x in range(2)
            ],
        )
        return SpringSlotMask(vertical_slots=self.vertical_slots, horizontal_slots=matrix)

    def with_all_vertical_disabled(self) -> SpringSlotMask:
        """Return a new mask with all vertical slots disabled."""
        return SpringSlotMask(
            vertical_slots=BoolMatrix2x2([[False, False], [False, False]]),
            horizontal_slots=self.horizontal_slots,
        )

    def with_all_horizontal_disabled(self) -> SpringSlotMask:
        """Return a new mask with all horizontal slots disabled."""
        return SpringSlotMask(
            vertical_slots=self.vertical_slots,
            horizontal_slots=BoolMatrix2x2([[False, False], [False, False]]),
        )


@dataclass(frozen=True)
class SpringShapeSlots:
    """Prebuilt slot library for a single semantic variant (8 shapes total)."""

    vertical: ShapeMatrix2x2
    horizontal: ShapeMatrix2x2

    def __post_init__(self) -> None:
        """Validate the matrix dimensions."""
        _assert_2x2_shape_matrix("vertical", self.vertical)
        _assert_2x2_shape_matrix("horizontal", self.horizontal)

    def fused(self, mask: SpringSlotMask) -> Part.Shape | None:
        """Fuse selected slots into a single shape."""
        shapes: list[Part.Shape] = []
        shapes.extend(
            self.vertical[x][y].copy()
            for x in range(2)
            for y in range(2)
            if mask.vertical_slots[x][y]
        )
        shapes.extend(
            self.horizontal[x][y].copy()
            for x in range(2)
            for y in range(2)
            if mask.horizontal_slots[x][y]
        )
        if not shapes:
            return None
        return utils.multi_fuse(shapes)

    def fused_all(self) -> Part.Shape | None:
        """Fuse all slots into a single shape."""
        return self.fused(SpringSlotMask.all_true())


def make_click_spring_seed_positive(
    fundamentals: FundamentalsParamsData,
    click_springs: ClickSpringParamsData,
) -> Part.Shape:
    """Build the positive seed shape for a click spring."""
    x_vert_width = fundamentals.grid_size - 2 * fundamentals.main_half_width
    click_length = click_springs.click_length
    click_center_y = fundamentals.grid_size / 4
    click_top_y = click_center_y + click_length / 2

    step = click_length / 3
    x0 = x_vert_width / 2
    x1 = x0 - click_springs.click_offset
    x2 = x1
    x3 = x2 + click_springs.click_offset
    y0 = click_top_y
    y1 = y0 - step
    y2 = y1 - step
    y3 = y2 - step

    z_mid = 0 * unitmm
    path_points = [
        fc.Vector(x0, y0, z_mid),
        fc.Vector(x1, y1, z_mid),
        fc.Vector(x2, y2, z_mid),
        fc.Vector(x3, y3, z_mid),
    ]
    spine = Part.Wire(Part.makePolygon(path_points))

    z1 = fundamentals.main_height
    x2 = x0 + click_springs.click_thickness
    z2 = z1 + click_springs.click_thickness
    profile_points = [
        fc.Vector(x0, y0, z_mid),
        fc.Vector(x0, y0, z1),
        fc.Vector(x2, y0, z2),
        fc.Vector(x2, y0, z_mid),
        fc.Vector(x0, y0, z_mid),
    ]
    profile = Part.Wire(Part.makePolygon(profile_points))
    return spine.makePipeShell([profile], True, False).removeSplitter()  # noqa: FBT003


def make_click_spring_seed_negative(
    fundamentals: FundamentalsParamsData,
    click_springs: ClickSpringParamsData,
) -> Part.Shape:
    """Build the negative seed shape for a click spring."""
    total_height = float(fundamentals.main_height + fundamentals.main_half_width)
    x_vert_width = float(fundamentals.grid_size - 2 * fundamentals.main_half_width)
    x0 = x_vert_width / 2
    click_offset = float(click_springs.click_offset)
    x_min = x0 - click_offset
    click_width_x = click_offset + float(click_springs.click_thickness)
    click_length = float(click_springs.click_length)
    click_center_y = float(fundamentals.grid_size) / 4
    return Part.makeBox(
        click_width_x,
        click_length,
        total_height,
        fc.Vector(x_min, click_center_y - click_length / 2, 0),
        fc.Vector(0, 0, 1),
    )


def make_click_spring_prototypes_from_seed(seed: Part.Shape) -> SpringShapeSlots:
    """Build all spring slot prototypes from a single seed shape."""

    def rot90_clockwise(shape: Part.Shape) -> Part.Shape:
        out = shape.copy()
        out.rotate(fc.Vector(0, 0, 0), fc.Vector(0, 0, 1), -90)
        return out

    def rotate_matrix_clockwise(matrix: ShapeMatrix2x2) -> ShapeMatrix2x2:
        out: list[list[Part.Shape]] = [
            [matrix[0][0].copy(), matrix[0][0].copy()],
            [matrix[0][0].copy(), matrix[0][0].copy()],
        ]
        for x in range(2):
            for y in range(2):
                x_new = 1 - y
                y_new = x
                out[x_new][y_new] = matrix[x][y]
        return ShapeMatrix2x2(out)

    def rotate_shapes_clockwise(matrix: ShapeMatrix2x2) -> ShapeMatrix2x2:
        return ShapeMatrix2x2([[rot90_clockwise(matrix[x][y]) for y in range(2)] for x in range(2)])

    vertical = expand_seed_to_shape_matrix(seed)
    vertical_rot = rotate_shapes_clockwise(vertical)
    horizontal = rotate_matrix_clockwise(vertical_rot)
    return SpringShapeSlots(vertical=vertical, horizontal=horizontal)


def _validate_click_spring_geometry(
    fundamentals: FundamentalsParamsData,
    click_springs: ClickSpringParamsData,
) -> None:
    if click_springs.click_thickness >= fundamentals.main_half_width:
        raise ValueError(
            f"Invalid click spring geometry: ClickThickness "
            f"({click_springs.click_thickness}) must be smaller than "
            f"BaseProfileMainHalfWidth ({fundamentals.main_half_width})",
        )

    half_len = click_springs.click_length / 2
    bin_vertical_radius = fundamentals.outer_radius - fundamentals.main_half_width
    x_limit = fundamentals.grid_size / 4 - bin_vertical_radius
    y_limit = fundamentals.grid_size / 4 - bin_vertical_radius

    if half_len >= x_limit or half_len >= y_limit:
        raise ValueError(
            f"Invalid click spring geometry: ClickLength/2 ({half_len}) must be smaller than "
            f"cell_size/4 - main_round_radius in both axes (x={x_limit}, y={y_limit})",
        )


def make_click_spring_prototype_positive(
    fundamentals: FundamentalsParamsData,
    click_springs: ClickSpringParamsData,
) -> SpringShapeSlots:
    """Build positive spring slot prototypes."""
    _validate_click_spring_geometry(fundamentals, click_springs)
    seed = make_click_spring_seed_positive(fundamentals, click_springs)
    return make_click_spring_prototypes_from_seed(seed)


def make_click_spring_prototype_negative(
    fundamentals: FundamentalsParamsData,
    click_springs: ClickSpringParamsData,
) -> SpringShapeSlots:
    """Build negative spring slot prototypes."""
    _validate_click_spring_geometry(fundamentals, click_springs)
    seed = make_click_spring_seed_negative(fundamentals, click_springs)
    return make_click_spring_prototypes_from_seed(seed)


def apply_click_spring_slots_to_cell(
    shape: Part.Shape,
    _fundamentals: FundamentalsParamsData,
    _core: BaseplateCoreParamsData,
    _click_springs: ClickSpringParamsData,
    negative_slots: SpringShapeSlots,
    positive_slots: SpringShapeSlots,
    mask: SpringSlotMask,
) -> Part.Shape:
    """Apply click spring slot cutouts and additions to a cell shape."""
    negative = negative_slots.fused(mask)
    if negative is not None:
        shape = shape.cut(negative)

    positive = positive_slots.fused(mask)
    if positive is not None:
        shape = shape.fuse(positive)
    return shape


def make_support_click_spring_seed(
    *,
    cell_inner_width: float,
    cell_height: float,
    click_offset: float,
    click_length: float,
) -> Part.Shape:
    """Build click spring seed for support profile carving."""
    step = click_length / 3
    x0 = cell_inner_width / 2
    x1 = x0 - click_offset
    x2 = x1
    x3 = x2 + click_offset
    y0 = cell_height / 4 + click_length / 2
    y1 = y0 - step
    y2 = y1 - step
    y3 = y2 - step
    points = [
        fc.Vector(x0, y0, 0),
        fc.Vector(x1, y1, 0),
        fc.Vector(x2, y2, 0),
        fc.Vector(x3, y3, 0),
        fc.Vector(x0, y0, 0),
    ]
    wire = Part.Wire(Part.makePolygon(points))
    if not wire.isClosed():
        raise ValueError("Support click spring profile wire is not closed")
    return Part.Face(wire)


def carve_support_profile_with_click_springs(
    profile_a_face: Part.Face,
    *,
    support_seed: Part.Shape,
    mask: SpringSlotMask | None,
    shift_x: float,
    shift_y: float,
) -> Part.Face:
    """Carve click spring notches from a support A-profile face."""
    if mask is None:
        return profile_a_face
    seed = support_seed.copy()
    if shift_x != 0 or shift_y != 0:
        seed.translate(fc.Vector(shift_x, shift_y, 0))
    support_profiles = make_click_spring_prototypes_from_seed(seed).fused(mask)
    if support_profiles is None:
        return profile_a_face
    cut = profile_a_face.cut(support_profiles)
    if not cut.Faces:
        raise ValueError(
            "Support A-profile generation failed after click spring support profile cut",
        )
    return max(cut.Faces, key=lambda f: f.Area)
