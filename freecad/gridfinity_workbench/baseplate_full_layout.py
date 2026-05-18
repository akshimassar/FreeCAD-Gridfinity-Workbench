"""Build Full Layout metadata for baseplate and baseplate support."""

from __future__ import annotations

from dataclasses import dataclass

from . import baseplate_click_springs as click_springs
from .baseplate_params import BaseplateParams
from .utils import GridfinityLayout, GridfinityLayoutGeometry


@dataclass
class FullLayoutCell:
    exists: bool
    kind: str
    is_tiny: bool
    width: float
    height: float
    spring_mask: click_springs.SpringSlotMask | None
    spring_shift_x: float
    spring_shift_y: float

    def get_mask(self) -> click_springs.SpringSlotMask | None:
        return self.spring_mask


def build_full_layout(
    params: BaseplateParams,
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
        tiny = [[False for _ in range(ny)] for _ in range(nx)] if nx > 0 else []
        x_lines = _build_grid_lines([params.fundamentals.x_grid_size] * nx)
        y_lines = _build_grid_lines([params.fundamentals.y_grid_size] * ny)
        return GridfinityLayoutGeometry(
            layout=base,
            tiny=tiny,
            x_lines=x_lines,
            y_lines=y_lines,
            cells=_build_cells(base, tiny, x_lines, y_lines, include_spring_masks, params),
        )

    x_sizes = [left_w] + [params.fundamentals.x_grid_size] * nx + [right_w]
    y_sizes = [bottom_w] + [params.fundamentals.y_grid_size] * ny + [top_w]

    expanded: GridfinityLayout = [[False for _ in range(ny + 2)] for _ in range(nx + 2)]
    tiny: GridfinityLayout = [[False for _ in range(ny + 2)] for _ in range(nx + 2)]

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

    x_lines = [x - float(left_w) for x in _build_grid_lines(x_sizes)]
    y_lines = [y - float(bottom_w) for y in _build_grid_lines(y_sizes)]
    return GridfinityLayoutGeometry(
        layout=expanded,
        tiny=tiny,
        x_lines=x_lines,
        y_lines=y_lines,
        cells=_build_cells(expanded, tiny, x_lines, y_lines, include_spring_masks, params),
    )


def _build_grid_lines(sizes: list) -> list[float]:
    lines = [0.0]
    total = 0.0
    for size in sizes:
        total += float(size)
        lines.append(total)
    return lines


def _build_cells(
    layout: GridfinityLayout,
    tiny: GridfinityLayout,
    x_lines: list[float],
    y_lines: list[float],
    include_spring_masks: bool,
    params: BaseplateParams,
) -> list[list[FullLayoutCell]]:
    cells: list[list[FullLayoutCell]] = []
    nx = len(layout)
    ny = len(layout[0]) if nx > 0 else 0
    for ix in range(nx):
        col: list[FullLayoutCell] = []
        for iy in range(ny):
            exists = bool(layout[ix][iy])
            width = x_lines[ix + 1] - x_lines[ix]
            height = y_lines[iy + 1] - y_lines[iy]
            is_tiny = (
                width < float(params.fundamentals.x_grid_size) / 2
                or height < float(params.fundamentals.y_grid_size) / 2
            )
            tiny[ix][iy] = is_tiny
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
    params: BaseplateParams,
    *,
    leftmost: bool,
    rightmost: bool,
    bottommost: bool,
    topmost: bool,
    target_cell_width: float,
    target_cell_height: float,
) -> click_springs.SpringSlotMask:
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
    params: BaseplateParams,
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
