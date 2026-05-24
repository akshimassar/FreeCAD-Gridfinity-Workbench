import unittest

from freecad.gridfinity_workbench.drawer_split import (
    PrintableChunk,
    split_axis_into_printable_chunks,
)


class DrawerSplitTest(unittest.TestCase):
    def _assert_invariants(  # noqa: PLR0913
        self,
        *,
        pieces: list[PrintableChunk],
        length_mm: float,
        grid_mm: float,
        bed_mm: float,
        low_fill_mm: float,
        high_fill_mm: float,
        assert_balanced: bool = True,
    ) -> None:
        cells_total = sum(p.cells for p in pieces)
        expected_cells = int(length_mm // grid_mm)
        self.assertEqual(cells_total, expected_cells)

        if assert_balanced:
            sim_sizes = [p.cells for p in pieces]
            self.assertLessEqual(max(sim_sizes) - min(sim_sizes), 1)

        for i, p in enumerate(pieces):
            if i not in {0, len(pieces) - 1}:
                self.assertEqual(p.low_fill_mm, 0.0)
                self.assertEqual(p.high_fill_mm, 0.0)
            width = p.cells * grid_mm + p.low_fill_mm + p.high_fill_mm
            self.assertLessEqual(width, bed_mm)

        total = sum(p.cells * grid_mm + p.low_fill_mm + p.high_fill_mm for p in pieces)
        self.assertAlmostEqual(total, length_mm)
        self.assertAlmostEqual(pieces[0].low_fill_mm, low_fill_mm)
        self.assertAlmostEqual(pieces[-1].high_fill_mm, high_fill_mm)

    def test_478_256_high(self) -> None:
        pieces = split_axis_into_printable_chunks(
            length_mm=478.0,
            grid_mm=42.0,
            bed_mm=256.0,
            alignment="high",
        )
        self._assert_invariants(
            pieces=pieces,
            length_mm=478.0,
            grid_mm=42.0,
            bed_mm=256.0,
            low_fill_mm=0.0,
            high_fill_mm=16.0,
        )
        widths = [p.cells * 42.0 + p.low_fill_mm + p.high_fill_mm for p in pieces]
        self.assertEqual(widths, [252.0, 226.0])

    def test_600_240_high(self) -> None:
        pieces = split_axis_into_printable_chunks(
            length_mm=600.0,
            grid_mm=42.0,
            bed_mm=240.0,
            alignment="high",
        )
        self._assert_invariants(
            pieces=pieces,
            length_mm=600.0,
            grid_mm=42.0,
            bed_mm=240.0,
            low_fill_mm=0.0,
            high_fill_mm=12.0,
        )
        widths = [p.cells * 42.0 + p.low_fill_mm + p.high_fill_mm for p in pieces]
        self.assertEqual(widths, [210.0, 210.0, 180.0])

    def test_600_240_high_greedy(self) -> None:
        pieces = split_axis_into_printable_chunks(
            length_mm=600.0,
            grid_mm=42.0,
            bed_mm=240.0,
            alignment="high",
            algorithm="greedy",
        )
        self._assert_invariants(
            pieces=pieces,
            length_mm=600.0,
            grid_mm=42.0,
            bed_mm=240.0,
            low_fill_mm=0.0,
            high_fill_mm=12.0,
            assert_balanced=False,
        )
        widths = [p.cells * 42.0 + p.low_fill_mm + p.high_fill_mm for p in pieces]
        self.assertEqual(widths, [210.0, 210.0, 180.0])

    def test_greedy_differs_from_balanced_distribution(self) -> None:
        balanced = split_axis_into_printable_chunks(
            length_mm=420.0,
            grid_mm=42.0,
            bed_mm=170.0,
            alignment="both",
            algorithm="balanced",
        )
        greedy = split_axis_into_printable_chunks(
            length_mm=420.0,
            grid_mm=42.0,
            bed_mm=170.0,
            alignment="both",
            algorithm="greedy",
        )
        balanced_widths = [p.cells * 42.0 + p.low_fill_mm + p.high_fill_mm for p in balanced]
        greedy_widths = [p.cells * 42.0 + p.low_fill_mm + p.high_fill_mm for p in greedy]
        self.assertEqual(balanced_widths, [126.0, 168.0, 126.0])
        self.assertEqual(greedy_widths, [84.0, 168.0, 168.0])


if __name__ == "__main__":
    unittest.main()
