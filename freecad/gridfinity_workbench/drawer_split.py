"""Single-axis drawer splitting helpers."""

from __future__ import annotations


def arrange_piece_sizes(total: int, pieces: int) -> list[int]:
    """Split total into near-uniform piece sizes (max diff 1).

    Returns a list with deterministic ordering that prefers symmetry by placing
    the even-count bucket first when possible.
    """
    if pieces < 1:
        raise ValueError("pieces must be >= 1")
    if total < 0:
        raise ValueError("total must be >= 0")

    q, r = divmod(total, pieces)
    a_count = pieces - r  # q
    b_count = r  # q+1

    if b_count == 0:
        return [q] * pieces

    low = [q] * a_count
    high = [q + 1] * b_count

    if a_count % 2 == 0 and b_count % 2 != 0:
        return low + high
    if b_count % 2 == 0 and a_count % 2 != 0:
        return high + low
    return low + high


def plan_axis_simulated_pieces(
    *,
    cell_count: int,
    bed_cells_capacity: int,
    low_filler_slot: bool,
    high_filler_slot: bool,
    start_from_high: bool = True,
) -> list[list[str]]:
    """Plan axis split using simulated cells and alternating side bites.

    Token legend:
    - "C": real grid cell
    - "F": filler-overhead slot
    """
    if cell_count < 0:
        raise ValueError("cell_count must be >= 0")
    if bed_cells_capacity < 1:
        raise ValueError("bed_cells_capacity must be >= 1")
    if cell_count > 0 and bed_cells_capacity < 1:
        raise ValueError("bed too small for one cell")

    simulated_total = cell_count + int(low_filler_slot) + int(high_filler_slot)
    if simulated_total == 0:
        return []

    pieces = (simulated_total + bed_cells_capacity - 1) // bed_cells_capacity
    sizes = arrange_piece_sizes(simulated_total, pieces)

    tokens = ["C"] * cell_count
    if low_filler_slot:
        tokens.insert(0, "F")
    if high_filler_slot:
        tokens.append("F")

    out: list[list[str] | None] = [None] * len(sizes)
    left_idx = 0
    right_idx = len(sizes) - 1
    take_high = start_from_high
    for size in sizes:
        if size > len(tokens):
            raise ValueError("internal split error: size exceeds remaining tokens")
        if take_high:
            chunk = tokens[-size:]
            del tokens[-size:]
            out[right_idx] = chunk
            right_idx -= 1
        else:
            chunk = tokens[:size]
            del tokens[:size]
            out[left_idx] = chunk
            left_idx += 1
        take_high = not take_high

    if tokens:
        raise ValueError("internal split error: tokens left over")
    return [chunk for chunk in out if chunk is not None]
