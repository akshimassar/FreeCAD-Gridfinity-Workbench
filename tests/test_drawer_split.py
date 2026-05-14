import unittest

from freecad.gridfinity_workbench.drawer_split import (
    arrange_piece_sizes,
    plan_axis_simulated_pieces,
)


class DrawerSplitTest(unittest.TestCase):
    def _assert_axis_split_invariants(
        self,
        *,
        chunks: list[list[str]],
        cell_count: int,
        grid_mm: float,
        bed_mm: float,
        remainder_mm: float,
        low_filler_slot: bool,
        high_filler_slot: bool,
        low_filler_mm: float,
        high_filler_mm: float,
    ) -> tuple[list[float], float]:
        self.assertEqual(sum(chunk.count("C") for chunk in chunks), cell_count)
        expected_fillers = int(low_filler_slot) + int(high_filler_slot)
        self.assertEqual(sum(chunk.count("F") for chunk in chunks), expected_fillers)

        sizes = [len(chunk) for chunk in chunks]
        self.assertLessEqual(max(sizes) - min(sizes), 1)

        # Filler token must be only on axis edges.
        for i, chunk in enumerate(chunks):
            if "F" in chunk:
                self.assertIn(i, {0, len(chunks) - 1})

        widths = [chunk.count("C") * grid_mm for chunk in chunks]
        if widths:
            widths[0] += low_filler_mm
            widths[-1] += high_filler_mm
        for width in widths:
            self.assertLessEqual(width, bed_mm)

        total_requested = cell_count * grid_mm + low_filler_mm + high_filler_mm
        self.assertAlmostEqual(sum(widths), total_requested)
        filler_total = low_filler_mm + high_filler_mm
        return widths, filler_total

    def test_arrange_piece_sizes_uniform(self) -> None:
        sizes = arrange_piece_sizes(13, 4)
        self.assertEqual(sum(sizes), 13)
        self.assertLessEqual(max(sizes) - min(sizes), 1)

    def test_plan_axis_simple_fit(self) -> None:
        chunks = plan_axis_simulated_pieces(
            cell_count=6,
            bed_cells_capacity=8,
            low_filler_slot=False,
            high_filler_slot=False,
        )
        self.assertEqual(chunks, [["C", "C", "C", "C", "C", "C"]])

    def test_plan_axis_with_symmetric_fillers(self) -> None:
        chunks = plan_axis_simulated_pieces(
            cell_count=7,
            bed_cells_capacity=3,
            low_filler_slot=True,
            high_filler_slot=True,
            start_from_high=True,
        )
        self._assert_axis_split_invariants(
            chunks=chunks,
            cell_count=7,
            grid_mm=42.0,
            bed_mm=126.0,
            remainder_mm=0.0,
            low_filler_slot=True,
            high_filler_slot=True,
            low_filler_mm=0.0,
            high_filler_mm=0.0,
        )

    def test_plan_axis_alternating_bites(self) -> None:
        chunks = plan_axis_simulated_pieces(
            cell_count=5,
            bed_cells_capacity=2,
            low_filler_slot=False,
            high_filler_slot=True,
            start_from_high=True,
        )
        # Simulated total is 6 => 3 pieces of size 2.
        self.assertEqual([len(c) for c in chunks], [2, 2, 2])
        self.assertIn("F", chunks[-1])

    def test_real_case_478mm_invariants(self) -> None:
        drawer_mm = 478.0
        grid_mm = 42.0
        bed_mm = 256.0

        cell_count = int(drawer_mm // grid_mm)
        remainder_mm = drawer_mm - cell_count * grid_mm
        bed_cells_capacity = int(bed_mm // grid_mm)

        high_filler_slot = remainder_mm > 0
        chunks = plan_axis_simulated_pieces(
            cell_count=cell_count,
            bed_cells_capacity=bed_cells_capacity,
            low_filler_slot=False,
            high_filler_slot=high_filler_slot,
            start_from_high=True,
        )

        widths, filler_total = self._assert_axis_split_invariants(
            chunks=chunks,
            cell_count=cell_count,
            grid_mm=grid_mm,
            bed_mm=bed_mm,
            remainder_mm=remainder_mm,
            low_filler_slot=False,
            high_filler_slot=high_filler_slot,
            low_filler_mm=0.0,
            high_filler_mm=remainder_mm,
        )
        self.assertEqual(widths, [252.0, 226.0])
        self.assertEqual(filler_total, 16.0)

        # Exact expected split for this scenario.
        self.assertEqual(
            chunks,
            [
                ["C", "C", "C", "C", "C", "C"],
                ["C", "C", "C", "C", "C", "F"],
            ],
        )

    def test_real_case_600mm_240bed_invariants(self) -> None:
        drawer_mm = 600.0
        grid_mm = 42.0
        bed_mm = 240.0

        cell_count = int(drawer_mm // grid_mm)
        remainder_mm = drawer_mm - cell_count * grid_mm
        bed_cells_capacity = int(bed_mm // grid_mm)

        high_filler_slot = remainder_mm > 0
        chunks = plan_axis_simulated_pieces(
            cell_count=cell_count,
            bed_cells_capacity=bed_cells_capacity,
            low_filler_slot=False,
            high_filler_slot=high_filler_slot,
            start_from_high=True,
        )

        widths, filler_total = self._assert_axis_split_invariants(
            chunks=chunks,
            cell_count=cell_count,
            grid_mm=grid_mm,
            bed_mm=bed_mm,
            remainder_mm=remainder_mm,
            low_filler_slot=False,
            high_filler_slot=high_filler_slot,
            low_filler_mm=0.0,
            high_filler_mm=remainder_mm,
        )
        self.assertEqual(widths, [210.0, 210.0, 180.0])
        self.assertEqual(filler_total, 12.0)

        # Exact expected split for this scenario.
        self.assertEqual(
            chunks,
            [
                ["C", "C", "C", "C", "C"],
                ["C", "C", "C", "C", "C"],
                ["C", "C", "C", "C", "F"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
