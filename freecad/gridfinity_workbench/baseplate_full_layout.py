"""Build Full Layout metadata for baseplate and baseplate support."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from typing import TYPE_CHECKING

import Part
import FreeCAD as fc  # noqa: N813

from .param import CombinedBaseplateParamsData

if TYPE_CHECKING:
    from . import baseplate_click_springs as click_springs


GridfinityLayout = list[list[bool]]


@dataclass(frozen=True)
class ShapeMatrix2x2:
    values: list[list[Part.Shape]]

    def __post_init__(self) -> None:
        if len(self.values) != 2 or any(len(col) != 2 for col in self.values):
            raise ValueError("ShapeMatrix2x2 must be a 2x2 shape matrix")

    def __getitem__(self, index: int) -> list[Part.Shape]:
        return self.values[index]

    def __iter__(self):
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def select_single(self, mask: "BoolMatrix2x2") -> Part.Shape | None:
        if mask.count_true() != 1:
            return None
        if mask[0][0]:
            return self.values[0][0].copy()
        if mask[0][1]:
            return self.values[0][1].copy()
        if mask[1][0]:
            return self.values[1][0].copy()
        if mask[1][1]:
            return self.values[1][1].copy()
        return None


def expand_seed_to_shape_matrix(seed: Part.Shape) -> ShapeMatrix2x2:
    def mirror_x(shape: Part.Shape) -> Part.Shape:
        return shape.mirror(fc.Vector(0, 0, 0), fc.Vector(1, 0, 0))

    def mirror_y(shape: Part.Shape) -> Part.Shape:
        return shape.mirror(fc.Vector(0, 0, 0), fc.Vector(0, 1, 0))

    matrix: list[list[Part.Shape]] = [[seed.copy(), seed.copy()], [seed.copy(), seed.copy()]]
    matrix[1][0] = seed
    matrix[0][0] = mirror_x(matrix[1][0])
    matrix[0][1] = mirror_y(matrix[0][0])
    matrix[1][1] = mirror_y(matrix[1][0])
    return ShapeMatrix2x2(matrix)


@dataclass(frozen=True)
class BoolMatrix2x2:
    values: list[list[bool]]

    def __post_init__(self) -> None:
        if len(self.values) != 2 or any(len(col) != 2 for col in self.values):
            raise ValueError("BoolMatrix2x2 must be a 2x2 bool matrix")
        for col in self.values:
            for value in col:
                if not isinstance(value, bool):
                    raise ValueError("BoolMatrix2x2 must contain only bool values")

    def __getitem__(self, index: int) -> list[bool]:
        return self.values[index]

    def __iter__(self):
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def count_true(self) -> int:
        return sum(1 for x in range(2) for y in range(2) if self.values[x][y])

    def flatten(self) -> list[bool]:
        return [self.values[x][y] for x in range(2) for y in range(2)]

    def negated(self) -> BoolMatrix2x2:
        return BoolMatrix2x2([[not self.values[x][y] for y in range(2)] for x in range(2)])

    def is_side(self) -> Literal["horizontal", "vertical"] | None:
        if self.count_true() != 2:
            return None
        has_horizontal_pair = (self.values[0][0] and self.values[1][0]) or (
            self.values[0][1] and self.values[1][1]
        )
        has_vertical_pair = (self.values[0][0] and self.values[0][1]) or (
            self.values[1][0] and self.values[1][1]
        )
        if has_horizontal_pair:
            return "horizontal"
        if has_vertical_pair:
            return "vertical"
        return None


@dataclass
class GridfinityLayoutGeometry:
    """Layout occupancy plus variable grid-line coordinates."""

    cells: list[list["FullLayoutCell"]]

    def size(self) -> tuple[int, int]:
        nx = len(self.cells)
        if nx == 0:
            return 0, 0
        return nx, len(self.cells[0])

    def line_x(self, ix: int) -> float:
        nx, _ = self.size()
        if not (0 <= ix <= nx):
            raise IndexError(f"X line index out of bounds: {ix} for nx={nx}")
        return sum(self.cells[x][0].width for x in range(ix))

    def line_y(self, iy: int) -> float:
        _, ny = self.size()
        if not (0 <= iy <= ny):
            raise IndexError(f"Y line index out of bounds: {iy} for ny={ny}")
        return sum(self.cells[0][y].height for y in range(iy))

    def cell_center(self, ix: int, iy: int) -> tuple[float, float]:
        nx, ny = self.size()
        if not (0 <= ix < nx and 0 <= iy < ny):
            raise IndexError(f"Cell index out of bounds: ({ix}, {iy}) for size ({nx}, {ny})")
        return self.line_x(ix) + self.cells[ix][iy].width / 2, self.line_y(iy) + self.cells[ix][
            iy
        ].height / 2

    def junction_neighbours(self, ix: int, iy: int) -> "FullCellNeighbours2x2":
        def at(x: int, y: int) -> FullLayoutCell:
            nx, ny = self.size()
            if 0 <= x < nx and 0 <= y < ny:
                return self.cells[x][y]
            return FullLayoutCell.empty()
        
        # this is kinda tricky because neighbours expect Y axis inverted
        return FullCellNeighbours2x2(
            [
                [at(ix - 1, iy), at(ix - 1, iy - 1)],
                [at(ix, iy), at(ix, iy - 1)],
            ]
        )


@dataclass
class FullLayoutCell:
    exists: bool
    kind: str
    is_tiny: bool
    width: float
    height: float
    spring_mask: "click_springs.SpringSlotMask" | None
    spring_shift_x: float
    spring_shift_y: float

    def get_mask(self) -> "click_springs.SpringSlotMask" | None:
        return self.spring_mask

    @classmethod
    def empty(cls) -> "FullLayoutCell":
        return cls(
            exists=False,
            kind="Empty",
            is_tiny=False,
            width=0.0,
            height=0.0,
            spring_mask=None,
            spring_shift_x=0.0,
            spring_shift_y=0.0,
        )


@dataclass(frozen=True)
class FullCellNeighbours2x2:
    values: list[list[FullLayoutCell]]

    def __post_init__(self) -> None:
        if len(self.values) != 2 or any(len(col) != 2 for col in self.values):
            raise ValueError("FullCellNeighbours2x2 must be a 2x2 full-cell matrix")

    def count_true(self) -> int:
        return sum(1 for x in range(2) for y in range(2) if self.values[x][y].exists)

    def exists(self) -> BoolMatrix2x2:
        return BoolMatrix2x2([[self.values[x][y].exists for y in range(2)] for x in range(2)])

    def is_tiny(self) -> BoolMatrix2x2:
        return BoolMatrix2x2([[self.values[x][y].is_tiny for y in range(2)] for x in range(2)])

    def has_tiny(self) -> bool:
        return any(
            self.values[x][y].exists and self.values[x][y].is_tiny
            for x in range(2)
            for y in range(2)
        )

    def is_side(self) -> Literal["horizontal", "vertical"] | None:
        has_horizontal_pair = (self.values[0][0].exists and self.values[1][0].exists) or (
            self.values[0][1].exists and self.values[1][1].exists
        )
        has_vertical_pair = (self.values[0][0].exists and self.values[0][1].exists) or (
            self.values[1][0].exists and self.values[1][1].exists
        )
        if has_horizontal_pair and not has_vertical_pair:
            return "horizontal"
        if has_vertical_pair and not has_horizontal_pair:
            return "vertical"
        return None


def build_full_layout(
    params: CombinedBaseplateParamsData,
    layout: GridfinityLayout,
    *,
    include_spring_masks: bool,
) -> GridfinityLayoutGeometry:
    nx = len(layout)
    ny = len(layout[0]) if nx > 0 else 0
    if nx == 0:
        nx = int(params.core.x_grid_count)
    if ny == 0:
        ny = int(params.core.y_grid_count)

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
        base = [[bool(layout[ix][iy]) for iy in range(ny)] for ix in range(nx)] if nx > 0 else []
        x_sizes = [float(params.fundamentals.x_grid_size)] * nx
        y_sizes = [float(params.fundamentals.y_grid_size)] * ny
        return GridfinityLayoutGeometry(
            cells=_build_cells(base, x_sizes, y_sizes, include_spring_masks, params),
        )

    x_sizes = [left_w] + [params.fundamentals.x_grid_size] * nx + [right_w]
    y_sizes = [bottom_w] + [params.fundamentals.y_grid_size] * ny + [top_w]

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

    x_sizes = [float(size) for size in x_sizes]
    y_sizes = [float(size) for size in y_sizes]
    return GridfinityLayoutGeometry(
        cells=_build_cells(expanded, x_sizes, y_sizes, include_spring_masks, params),
    )


def _build_cells(
    layout: GridfinityLayout,
    x_sizes: list[float],
    y_sizes: list[float],
    include_spring_masks: bool,
    params: CombinedBaseplateParamsData,
) -> list[list[FullLayoutCell]]:
    from . import baseplate_click_springs as click_springs

    cells: list[list[FullLayoutCell]] = []
    nx = len(layout)
    ny = len(layout[0]) if nx > 0 else 0
    for ix in range(nx):
        col: list[FullLayoutCell] = []
        for iy in range(ny):
            exists = bool(layout[ix][iy])
            width = x_sizes[ix]
            height = y_sizes[iy]
            is_tiny = (
                width < float(params.fundamentals.x_grid_size) / 2
                or height < float(params.fundamentals.y_grid_size) / 2
            )
            kind = "Core"
            if nx > 2 and ny > 2 and (ix in (0, nx - 1) or iy in (0, ny - 1)):
                kind = "Filler"

            leftmost = ix == 0
            rightmost = ix == nx - 1
            bottommost = iy == 0
            topmost = iy == ny - 1
            shift_x, shift_y = _alignment_shift(
                params,
                leftmost=leftmost,
                rightmost=rightmost,
                bottommost=bottommost,
                topmost=topmost,
                target_cell_width=width,
                target_cell_height=height,
            )
            spring_mask = None
            if include_spring_masks and exists and not is_tiny:
                if kind == "Core":
                    spring_mask = click_springs.SpringSlotMask.all_true()
                else:
                    spring_mask = _filler_spring_mask(
                        params,
                        leftmost=leftmost,
                        rightmost=rightmost,
                        bottommost=bottommost,
                        topmost=topmost,
                        target_cell_width=width,
                        target_cell_height=height,
                    )

            col.append(
                FullLayoutCell(
                    exists=exists,
                    kind=kind,
                    is_tiny=is_tiny,
                    width=width,
                    height=height,
                    spring_mask=spring_mask,
                    spring_shift_x=shift_x,
                    spring_shift_y=shift_y,
                )
            )
        cells.append(col)
    return cells


def _filler_spring_mask(
    params: CombinedBaseplateParamsData,
    *,
    leftmost: bool,
    rightmost: bool,
    bottommost: bool,
    topmost: bool,
    target_cell_width: float,
    target_cell_height: float,
) -> "click_springs.SpringSlotMask":
    from . import baseplate_click_springs as click_springs

    mask = click_springs.SpringSlotMask.all_true()
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
        mask = mask.with_all_horizontal_disabled().with_all_vertical_disabled()

    return mask


def _alignment_shift(
    params: CombinedBaseplateParamsData,
    *,
    leftmost: bool,
    rightmost: bool,
    bottommost: bool,
    topmost: bool,
    target_cell_width: float,
    target_cell_height: float,
) -> tuple[float, float]:
    sx = -1 if leftmost else (1 if rightmost else 0)
    sy = -1 if bottommost else (1 if topmost else 0)
    grid_half_x = float(params.fundamentals.x_grid_size) / 2
    grid_half_y = float(params.fundamentals.y_grid_size) / 2
    cell_half_x = target_cell_width / 2
    cell_half_y = target_cell_height / 2
    return sx * (cell_half_x - grid_half_x), sy * (cell_half_y - grid_half_y)
