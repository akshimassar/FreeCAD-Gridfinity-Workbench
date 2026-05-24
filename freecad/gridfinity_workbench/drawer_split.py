"""Single-axis drawer splitting helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrintableAxisChunk:
    """A single printable chunk along one axis."""

    cells: int
    low_fill_mm: float
    high_fill_mm: float


def _build_balanced_chunk_cell_counts(total: int, pieces: int) -> list[int]:
    if pieces < 1:
        raise ValueError("pieces must be >= 1")
    q, r = divmod(total, pieces)
    a_count = pieces - r
    b_count = r
    if b_count == 0:
        return [q] * pieces
    low = [q] * a_count
    high = [q + 1] * b_count
    if a_count % 2 == 0 and b_count % 2 != 0:
        return low + high
    if b_count % 2 == 0 and a_count % 2 != 0:
        return high + low
    return low + high


def _build_greedy_chunk_cell_counts(total: int, cap_cells: int) -> list[int]:
    if cap_cells < 1:
        raise ValueError("cap_cells must be >= 1")
    if total < 1:
        return []
    sizes: list[int] = []
    remaining = total
    while remaining > 0:
        take = min(cap_cells, remaining)
        sizes.append(take)
        remaining -= take
    return sizes


def split_axis_into_printable_chunks(  # noqa: C901, PLR0912, PLR0915
    *,
    length_mm: float,
    grid_mm: float,
    bed_mm: float,
    alignment: str,
    algorithm: str = "balanced",
) -> list[PrintableAxisChunk]:
    """Split an axis into printable chunks based on bed and grid constraints."""
    if grid_mm <= 0 or bed_mm <= 0 or length_mm <= 0:
        raise ValueError("length, grid and bed must be > 0")
    if bed_mm < grid_mm:
        raise ValueError("Bed too small for one full grid cell")

    cell_count = int(length_mm // grid_mm)
    remainder = max(length_mm - cell_count * grid_mm, 0.0)

    low_fill = 0.0
    high_fill = 0.0
    if alignment == "low":
        low_fill = remainder
    elif alignment == "high":
        high_fill = remainder
    elif alignment == "both":
        low_fill = remainder / 2
        high_fill = remainder - low_fill
    else:
        raise ValueError("alignment must be low/high/both")

    cap_cells = int(bed_mm // grid_mm)
    low_slot = low_fill > 0 and ((cap_cells * grid_mm) + low_fill > bed_mm)
    high_slot = high_fill > 0 and ((cap_cells * grid_mm) + high_fill > bed_mm)
    sim_total = cell_count + int(low_slot) + int(high_slot)
    if sim_total == 0:
        return []

    pieces_n = (sim_total + cap_cells - 1) // cap_cells
    if algorithm == "balanced":
        sizes = sorted(_build_balanced_chunk_cell_counts(sim_total, pieces_n))
    elif algorithm == "greedy":
        sizes = sorted(_build_greedy_chunk_cell_counts(sim_total, cap_cells))
    else:
        raise ValueError("algorithm must be balanced/greedy")

    tokens = ["C"] * cell_count
    if low_slot:
        tokens.insert(0, "F")
    if high_slot:
        tokens.append("F")

    out: list[list[str] | None] = [None] * len(sizes)
    low_idx, high_idx = 0, len(sizes) - 1

    pick_low = low_fill > 0
    pick_high = high_fill > 0
    if not pick_low and not pick_high:
        pick_low = True
        pick_high = True
    take_low = True

    def choose_side() -> str:
        nonlocal take_low
        if pick_low and not pick_high:
            return "low"
        if pick_high and not pick_low:
            return "high"
        side = "low" if take_low else "high"
        take_low = not take_low
        return side

    for size in sizes:
        side = choose_side()
        if side == "high":
            chunk = tokens[-size:]
            del tokens[-size:]
            out[high_idx] = chunk
            high_idx -= 1
        else:
            chunk = tokens[:size]
            del tokens[:size]
            out[low_idx] = chunk
            low_idx += 1
    chunks = [c for c in out if c is not None]

    if chunks and low_fill > 0 and all("F" not in c for c in chunks):
        chunks[0].append("F")
    if chunks and high_fill > 0 and all("F" not in c for c in chunks):
        chunks[-1].append("F")

    pieces: list[PrintableAxisChunk] = []
    for i, chunk in enumerate(chunks):
        p_low = low_fill if i == 0 else 0.0
        p_high = high_fill if i == len(chunks) - 1 else 0.0
        piece = PrintableAxisChunk(cells=chunk.count("C"), low_fill_mm=p_low, high_fill_mm=p_high)
        width = piece.cells * grid_mm + piece.low_fill_mm + piece.high_fill_mm
        if width > bed_mm + 1e-9:
            raise ValueError("Generated piece exceeds bed size")
        pieces.append(piece)

    return pieces


# Backward compatibility aliases.
AxisPiece = PrintableAxisChunk
plan_axis_split = split_axis_into_printable_chunks
