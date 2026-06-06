import os
import sys
import unittest
from io import StringIO
from pathlib import Path
from tempfile import gettempdir
from typing import Any

import FreeCAD as fc  # noqa: N813
import FreeCADGui as fcg  # noqa: N813

TEMPDIR = Path(gettempdir())
DOC_NAME = "GridfinityDocument"

# Enable FreeCAD console output to stderr so test failures are visible
fc.Console.SetStatus("Console", "Log", True)  # noqa: FBT003
fc.Console.SetStatus("Console", "Msg", True)  # noqa: FBT003
fc.Console.SetStatus("Console", "Wrn", True)  # noqa: FBT003
fc.Console.SetStatus("Console", "Err", True)  # noqa: FBT003

# FreeCAD console warning patterns (same as integration tests)
FREECAD_WARNING_PATTERNS = ("<Wrn>", "<Err>", "<App>", "<Gui>")


def setUpModule() -> None:
    """Reset Gridfinity settings to factory defaults before all tests."""
    from .param_system import default_resolver

    default_resolver.reset_to_factory_defaults()


def tearDownModule() -> None:
    """Reset Gridfinity settings to factory defaults after all tests."""
    from .param_system import default_resolver

    default_resolver.reset_to_factory_defaults()


class TestWithDocument(unittest.TestCase):
    """Base class for test that do everything on an open document.

    If a test fails, the file can be found in temporary directory (/tmp on Linux).
    Captures stdout/stderr to detect tracebacks during test execution.
    Also checks FreeCAD console output log for warnings (via FREECAD_GUI_OUTPUT_LOG).
    """

    _original_stderr: Any = None
    _original_stdout: Any = None
    _captured_stderr: StringIO | None = None
    _debug_log: list[str]
    _log_start_pos: int = 0

    def log(self, msg: str) -> None:
        """Log debug message that will be shown on test failure."""
        self._debug_log.append(msg)
        # Also print to original stderr so it's visible in real-time
        if self._original_stderr:
            print(f"[DEBUG] {msg}", file=self._original_stderr)

    def get_debug_log(self) -> str:
        """Get all debug messages as a single string."""
        return "\n".join(self._debug_log)

    _captured_stdout: StringIO | None = None

    def _get_log_file_path(self) -> Path | None:
        """Get path to FreeCAD GUI output log file."""
        log_path = os.environ.get("FREECAD_GUI_OUTPUT_LOG")
        if log_path:
            return Path(log_path)
        return None

    def _get_new_log_content(self) -> str:
        """Get log content added since setUp."""
        log_file = self._get_log_file_path()
        if not log_file or not log_file.exists():
            return ""
        with log_file.open(encoding="utf-8", errors="replace") as f:
            f.seek(self._log_start_pos)
            return f.read()

    def setUp(self) -> None:
        # Initialize debug log
        self._debug_log = []

        # Record log file position for warning detection
        log_file = self._get_log_file_path()
        if log_file and log_file.exists():
            self._log_start_pos = log_file.stat().st_size
        else:
            self._log_start_pos = 0

        # Capture stdout/stderr to detect tracebacks
        self._original_stderr = sys.stderr
        self._original_stdout = sys.stdout
        self._captured_stderr = StringIO()
        self._captured_stdout = StringIO()
        sys.stderr = self._captured_stderr
        sys.stdout = self._captured_stdout

        # Ensure no active dialog from previous tests
        fcg.Control.closeDialog()

        fcg.activateWorkbench("GridfinityWorkbench")
        self.doc = fc.newDocument(DOC_NAME)
        self.filepath = f"{TEMPDIR / self.__class__.__name__!s}_{self._testMethodName}.FCStd"

    def tearDown(self) -> None:
        self.doc.saveAs(str(self.filepath))
        fc.closeDocument(DOC_NAME)

        # Restore stdout/stderr and check for tracebacks
        sys.stderr = self._original_stderr
        sys.stdout = self._original_stdout
        captured_err = self._captured_stderr.getvalue() if self._captured_stderr else ""
        captured_out = self._captured_stdout.getvalue() if self._captured_stdout else ""
        captured = captured_err + captured_out

        # Also get FreeCAD console output from log file
        log_content = self._get_new_log_content()
        all_output = captured + log_content

        # Check for traceback indicators
        if "Traceback (most recent call last):" in all_output:
            self.fail(f"Traceback detected during test execution:\n{all_output}")

        # Check for FreeCAD warnings and errors
        warning_lines = [
            line
            for line in all_output.splitlines()
            if any(pattern in line for pattern in FREECAD_WARNING_PATTERNS)
        ]
        if warning_lines:
            self.fail("FreeCAD warnings/errors detected:\n" + "\n".join(warning_lines))


class TestConnectingClipTaskPanel(TestWithDocument):
    """Test creating a connecting clip through the task panel dialog."""

    def test_create_connecting_clip_via_dialog(self) -> None:
        from .commands import ICONDIR, CreateConnectingClipTaskPanel

        # Open the task panel dialog
        panel = CreateConnectingClipTaskPanel(ICONDIR / "connecting-clip.svg")
        fcg.Control.showDialog(panel)

        # Accept the dialog to create the object
        panel.accept()

        # Verify object was created
        self.assertEqual(len(self.doc.Objects), 1)
        obj = self.doc.Objects[0]
        self.assertEqual(obj.Label, "ConnectingClip")

        # Verify shape is valid
        self.assertTrue(obj.Shape.isValid())
        self.assertGreater(obj.Shape.Volume, 0)


class TestBaseplateTaskPanel(TestWithDocument):
    """Test creating a baseplate through the task panel dialog."""

    def test_create_simple_baseplate_via_dialog(self) -> None:
        from .commands import ICONDIR, CreateBaseplateTaskPanel

        # Open the task panel dialog
        panel = CreateBaseplateTaskPanel(ICONDIR / "baseplate-obj.svg")
        fcg.Control.showDialog(panel)

        # Accept the dialog to create the object (simulates OK button press)
        panel.accept()

        # Verify object was created
        self.assertEqual(len(self.doc.Objects), 1)
        obj = self.doc.Objects[0]
        self.assertIn("Baseplate", obj.Label)

        # Verify shape is valid
        self.assertTrue(obj.Shape.isValid())
        self.assertGreater(obj.Shape.Volume, 0)


class TestBaseplateLayoutTaskPanel(TestWithDocument):
    """Test baseplate layout parameter changes through dialog simulation."""

    def test_baseplate_layout_dialog_workflow(self) -> None:
        """Test dialog workflow with layout changes and volume measurements.

        Steps:
        1. Open dialog, disable snap springs -> verify body, measure volume
        2. Edit, disable connecting clips and junction screws -> measure volume (reference)
        3. Set L-shape layout (3 cells) -> measure ~3/4 of reference volume
        4. Enable top filler, disable layout -> measure increased volume
        5. Lock exact volumes at the end
        """
        import json

        from .commands import ICONDIR, CreateBaseplateTaskPanel

        # Step 1: Create baseplate with snap springs disabled (uses default 2x2 grid)
        panel = CreateBaseplateTaskPanel(ICONDIR / "baseplate-obj.svg")
        fcg.Control.showDialog(panel)
        panel.click_springs__enabled.setChecked(False)
        panel.accept()

        # Verify object created and valid
        self.assertEqual(len(self.doc.Objects), 1)
        obj = self.doc.Objects[0]
        self.assertTrue(obj.Shape.isValid())
        self.assertEqual(len(obj.Shape.Solids), 1)
        volume_with_clips = obj.Shape.Volume
        self.assertGreater(volume_with_clips, 0)

        # Step 2: Edit dialog - disable connecting clips and junction screws
        panel2 = CreateBaseplateTaskPanel(ICONDIR / "baseplate-obj.svg", target_obj=obj)
        fcg.Control.showDialog(panel2)
        panel2.connecting_clips__enabled.setChecked(False)
        panel2.junction_screws__enabled.setChecked(False)
        panel2.accept()

        self.doc.recompute()
        self.assertTrue(obj.Shape.isValid())
        self.assertEqual(len(obj.Shape.Solids), 1)
        volume_reference = obj.Shape.Volume
        # Volume should increase slightly when disabling clips/screws (less material removed)
        self.assertGreater(volume_reference, volume_with_clips)

        # Step 3: Set 3-cell L-shape custom layout
        # L-shape: [[True, True], [True, False]] = 3 cells out of 4
        l_shape_layout = [[True, True], [True, False]]
        obj.baseplate_size__custom_layout_enabled = True
        obj.baseplate_size__custom_layout = json.dumps(l_shape_layout)

        self.doc.recompute()
        self.assertTrue(obj.Shape.isValid())
        self.assertEqual(len(obj.Shape.Solids), 1)
        volume_l_shape = obj.Shape.Volume
        # 3 cells out of 4 = approximately 75% of reference volume
        ratio = volume_l_shape / volume_reference
        self.assertAlmostEqual(ratio, 0.75, places=1)

        # Step 4: Enable top filler (uses default width), disable layout
        obj.baseplate_size__filler_top_enabled = True
        obj.baseplate_size__custom_layout_enabled = False

        self.doc.recompute()
        self.assertTrue(obj.Shape.isValid())
        self.assertEqual(len(obj.Shape.Solids), 1)
        volume_with_filler = obj.Shape.Volume
        # Volume should increase with filler compared to reference
        filler_ratio = volume_with_filler / volume_reference
        self.assertGreater(filler_ratio, 1.05)

        # Step 5: Lock exact volumes (2 decimal places)
        # LOCKED INVARIANT: These volumes are regression locks
        self.assertAlmostEqual(volume_with_clips, 4581.61, places=2)
        self.assertAlmostEqual(volume_reference, 4721.70, places=2)
        self.assertAlmostEqual(volume_l_shape, 3515.67, places=2)
        self.assertAlmostEqual(volume_with_filler, 6755.42, places=2)

    def test_baseplate_origin_2x2_vs_1x1(self) -> None:
        """Test that 2x2 and 1x1 baseplates both start at origin (0,0).

        This is a regression test for a bug where small baseplates had
        incorrect BBox positioning.
        """
        from .commands import ICONDIR, CreateBaseplateTaskPanel

        # Create 2x2 baseplate with springs disabled
        panel_2x2 = CreateBaseplateTaskPanel(ICONDIR / "baseplate-obj.svg")
        fcg.Control.showDialog(panel_2x2)
        panel_2x2.click_springs__enabled.setChecked(False)
        panel_2x2.accept()

        obj_2x2 = self.doc.Objects[0]
        self.doc.recompute()
        bbox_2x2 = obj_2x2.Shape.BoundBox

        # Create 1x1 baseplate with springs disabled
        panel_1x1 = CreateBaseplateTaskPanel(ICONDIR / "baseplate-obj.svg")
        fcg.Control.showDialog(panel_1x1)
        panel_1x1.click_springs__enabled.setChecked(False)
        panel_1x1.baseplate_size__x_grid_count.setValue(1)
        panel_1x1.baseplate_size__y_grid_count.setValue(1)
        panel_1x1.accept()

        obj_1x1 = self.doc.Objects[1]
        self.doc.recompute()
        bbox_1x1 = obj_1x1.Shape.BoundBox

        # Both should start at origin (0, 0)
        self.assertAlmostEqual(bbox_2x2.XMin, 0.0, places=2, msg="2x2 XMin should be 0")
        self.assertAlmostEqual(bbox_2x2.YMin, 0.0, places=2, msg="2x2 YMin should be 0")
        self.assertAlmostEqual(bbox_1x1.XMin, 0.0, places=2, msg="1x1 XMin should be 0")
        self.assertAlmostEqual(bbox_1x1.YMin, 0.0, places=2, msg="1x1 YMin should be 0")

    def test_custom_layout_origin_and_placement(self) -> None:
        """Test that custom layouts have correct origin AND Placement stays at (0,0,0).

        Regression test for bug where shape.translate() was used to move custom layouts
        to origin, but translate() only modifies Placement rather than transforming
        geometry. When fp.Shape is assigned, FreeCAD strips the Placement, leaving
        the shape at wrong coordinates.

        Fix: Use shape.transformGeometry() instead of shape.translate().
        """
        import json

        from . import features

        # Test case 1: Single cell at (4,5) in 10x10 grid
        layout_single = [[False] * 10 for _ in range(10)]
        layout_single[4][5] = True

        obj_single = self.doc.addObject("Part::FeaturePython", "SingleCellLayout")
        features.Baseplate(obj_single)
        obj_single.baseplate_size__x_grid_count = 10
        obj_single.baseplate_size__y_grid_count = 10
        obj_single.baseplate_size__custom_layout_enabled = True
        obj_single.baseplate_size__custom_layout = json.dumps(layout_single)
        obj_single.click_springs__enabled = False

        # Test case 2: 2x1 L-shape at positions (3,5) and (4,5)
        layout_2x1 = [[False] * 10 for _ in range(10)]
        layout_2x1[3][5] = True
        layout_2x1[4][5] = True

        obj_2x1 = self.doc.addObject("Part::FeaturePython", "TwoCellLayout")
        features.Baseplate(obj_2x1)
        obj_2x1.baseplate_size__x_grid_count = 10
        obj_2x1.baseplate_size__y_grid_count = 10
        obj_2x1.baseplate_size__custom_layout_enabled = True
        obj_2x1.baseplate_size__custom_layout = json.dumps(layout_2x1)
        obj_2x1.click_springs__enabled = False

        self.doc.recompute()

        # Check single cell - shape should start at origin with no Placement offset
        bbox_single = obj_single.Shape.BoundBox
        placement_single = obj_single.Placement
        self.assertAlmostEqual(placement_single.Base.x, 0.0, places=2)
        self.assertAlmostEqual(placement_single.Base.y, 0.0, places=2)
        self.assertAlmostEqual(bbox_single.XMin, 0.0, places=2)
        self.assertAlmostEqual(bbox_single.YMin, 0.0, places=2)

        # Check 2x1 layout - shape should start at origin with no Placement offset
        bbox_2x1 = obj_2x1.Shape.BoundBox
        placement_2x1 = obj_2x1.Placement
        self.assertAlmostEqual(placement_2x1.Base.x, 0.0, places=2)
        self.assertAlmostEqual(placement_2x1.Base.y, 0.0, places=2)
        self.assertAlmostEqual(bbox_2x1.XMin, 0.0, places=2)
        self.assertAlmostEqual(bbox_2x1.YMin, 0.0, places=2)


class TestBaseplateDialogFields(TestWithDocument):
    """Test that dialog fields match parameter definitions - no unexpected/duplicate fields."""

    def setUp(self) -> None:
        super().setUp()
        # Ensure no active dialog
        fcg.Control.closeDialog()

    def _extract_dialog_control_names(self, panel: object) -> set[str]:
        """Extract all control names (with '__') from a task panel."""
        from PySide.QtWidgets import QWidget

        control_names = set()
        for key, value in vars(panel).items():
            if "__" in key and isinstance(value, QWidget):
                control_names.add(key)
        return control_names

    def _collect_expected_controls(self, group: object, prefix: str, expected: set[str]) -> None:
        """Recursively collect expected control names from a parameter group."""
        # Get expanded param names from compound params (these are NOT individual controls)
        expanded_from_compound: set[str] = set()
        for cp in group._compound_params.values():  # noqa: SLF001
            expanded_from_compound.update(cp.expanded_names())
        # Add individual params that are NOT from compound params
        for param_name in group._parameters:  # noqa: SLF001
            if param_name not in expanded_from_compound:
                expected.add(f"{prefix}{param_name}")
        # Add compound params (which render as single UI controls)
        for cp_name in group._compound_params:  # noqa: SLF001
            expected.add(f"{prefix}{cp_name}")
        # Recursively handle child groups
        for child_key, child_group in group._child_groups.items():  # noqa: SLF001
            child_prefix = f"{prefix}{child_key}__"
            self._collect_expected_controls(child_group, child_prefix, expected)

    def test_baseplate_dialog_fields_match_params(self) -> None:
        """Verify CreateBaseplateTaskPanel has no unexpected or missing fields."""
        from .commands import ICONDIR, CreateBaseplateTaskPanel
        from .param import CombinedBaseplateParams

        # Create panel
        panel = CreateBaseplateTaskPanel(ICONDIR / "baseplate-obj.svg")
        fcg.Control.showDialog(panel)

        # Extract control names from panel
        dialog_controls = self._extract_dialog_control_names(panel)

        # Extract expected param names from CombinedBaseplateParams
        # Prefixes now match group names exactly (derived from class names)
        params = CombinedBaseplateParams()
        expected_controls: set[str] = set()
        for group_name, group in params._param_groups.items():  # noqa: SLF001
            prefix = f"{group_name}__"
            self._collect_expected_controls(group, prefix, expected_controls)

        # Find unexpected controls (in dialog but not in params)
        unexpected = dialog_controls - expected_controls
        # Find missing controls (in params but not in dialog)
        missing = expected_controls - dialog_controls

        # Report any discrepancies
        if unexpected:
            self.fail(f"Unexpected dialog controls not in params: {sorted(unexpected)}")
        if missing:
            self.fail(f"Missing dialog controls expected from params: {sorted(missing)}")

        panel.reject()


class TestDrawerBaseplateTaskPanel(TestWithDocument):
    """Test creating drawer baseplates through the task panel dialog."""

    def test_create_drawer_baseplate_via_dialog(self) -> None:
        """Test creating drawer baseplates with default settings."""
        from .commands import (
            ICONDIR,
            PREVIEW_SHAPE_COLOR,
            PREVIEW_TRANSPARENCY,
            CreateDrawerBaseplateTaskPanel,
        )

        # Open the task panel dialog
        panel = CreateDrawerBaseplateTaskPanel(ICONDIR / "drawer-baseplate.svg")
        fcg.Control.showDialog(panel)

        # Verify group exists (but no children during preview - uses separate preview object)
        group = panel._target_obj  # noqa: SLF001
        self.assertIsNotNone(group, "Preview group should exist")

        # Verify preview object exists and has valid shape
        preview_obj = panel._preview_obj  # noqa: SLF001
        self.assertIsNotNone(preview_obj, "Preview object should exist")
        self.assertTrue(preview_obj.Shape.isValid(), "Preview shape should be valid")
        self.assertGreater(preview_obj.Shape.Volume, 0, "Preview shape should have non-zero volume")

        # Verify preview visuals are applied to preview object
        view = preview_obj.ViewObject
        self.assertIsNotNone(view, "Preview object should have ViewObject")
        actual_rgb = view.ShapeColor[:3]
        for i, (actual, expected) in enumerate(zip(actual_rgb, PREVIEW_SHAPE_COLOR, strict=True)):
            self.assertAlmostEqual(
                actual,
                expected,
                places=4,
                msg=f"Preview object color[{i}] mismatch",
            )
        self.assertEqual(
            view.Transparency,
            PREVIEW_TRANSPARENCY,
            "Preview object should have preview transparency",
        )

        # Accept the dialog to create the object
        panel.accept()

        # Verify group and children were created
        group = self.doc.getObject("DrawerBaseplates")
        self.assertIsNotNone(group)
        self.assertIn("Drawer Baseplates", group.Label)

        # Group should have children (pieces created on accept)
        children = group.Children
        self.assertGreater(len(children), 0, "Children should be created on accept")

        # Each child should have a valid shape
        for child in children:
            self.assertTrue(child.Shape.isValid())
            self.assertGreater(child.Shape.Volume, 0)
            self.assertGreater(len(child.Shape.Solids), 0)

        # Verify pieces are positioned on tile grid (not all at origin)
        placements = [child.Placement.Base for child in children]
        x_positions = sorted({p.x for p in placements})
        y_positions = sorted({p.y for p in placements})
        # Should have multiple distinct X and Y positions for a 3x3 grid
        self.assertGreater(len(x_positions), 1, "All pieces at same X position")
        self.assertGreater(len(y_positions), 1, "All pieces at same Y position")

    def test_drawer_baseplate_volumes_reproducible(self) -> None:
        """Test drawer baseplate volumes are identical when created twice with defaults.

        Steps:
        1. Create drawer baseplates with defaults, preview, accept
        2. Verify bottom-left 2x2 pieces total volume matches expected
        3. Delete the group
        4. Create again with same defaults, preview, accept
        5. Compare volumes - should be identical
        """
        from .commands import ICONDIR, CreateDrawerBaseplateTaskPanel

        # Bottom-left 2x2 pieces: row 1-2, col 0-1
        # (row 0 is top, row 2 is bottom; col 0 is left)
        bottom_left_pieces = {"Piece_1_0", "Piece_1_1", "Piece_2_0", "Piece_2_1"}
        expected_volume = 28343.04

        def get_bottom_left_volumes(group: fc.DocumentObject) -> dict[str, float]:
            """Get volumes of bottom-left 2x2 pieces."""
            return {
                child.Name: child.Shape.Volume
                for child in group.Children
                if child.Name in bottom_left_pieces
            }

        # Step 1: Create drawer baseplates with defaults
        panel = CreateDrawerBaseplateTaskPanel(ICONDIR / "drawer-baseplate.svg")
        fcg.Control.showDialog(panel)
        panel._preview_timer.stop()  # noqa: SLF001
        panel.accept()

        # Step 2: Verify each bottom-left piece volume matches expected
        group = self.doc.getObject("DrawerBaseplates")
        self.assertIsNotNone(group, "DrawerBaseplates group should exist")
        assert group is not None
        first_volumes = get_bottom_left_volumes(group)
        self.assertEqual(len(first_volumes), 4, "Should have 4 bottom-left pieces")
        self.log(f"First creation volumes: {first_volumes}")
        for piece_name, volume in first_volumes.items():
            self.assertAlmostEqual(
                volume,
                expected_volume,
                places=2,
                msg=f"{piece_name} volume should be {expected_volume}",
            )

        # Step 3: Delete group and children
        for child in list(group.Children):
            self.doc.removeObject(child.Name)
        self.doc.removeObject(group.Name)
        self.doc.recompute()

        # Step 4: Create again with same defaults
        panel2 = CreateDrawerBaseplateTaskPanel(ICONDIR / "drawer-baseplate.svg")
        fcg.Control.showDialog(panel2)
        panel2._update_preview()  # noqa: SLF001
        panel2._preview_timer.stop()  # noqa: SLF001
        panel2.accept()

        # Step 5: Compare volumes
        group2 = self.doc.getObject("DrawerBaseplates001")
        if group2 is None:
            group2 = self.doc.getObject("DrawerBaseplates")
        self.assertIsNotNone(group2, "Second DrawerBaseplates group should exist")
        assert group2 is not None
        second_volumes = get_bottom_left_volumes(group2)
        self.log(f"Second creation volumes: {second_volumes}")

        self.assertEqual(
            first_volumes,
            second_volumes,
            "Volumes should be identical when creating drawer baseplates twice",
        )

    def test_drawer_baseplate_width_change_updates_rightmost_column(self) -> None:
        """Test that changing drawer width updates rightmost column but not left columns.

        With greedy algorithm and right filler alignment:
        - Left columns should keep same volume when width changes
        - Rightmost column should update (different filler)

        Steps:
        1. Create drawer baseplates with greedy algorithm, accept
        2. Record all piece volumes
        3. Edit, change width to 550, accept
        4. Left columns (col 0, 1) should have same volumes
        5. Rightmost column (col 2) should have different volumes
        """
        from .commands import ICONDIR, CreateDrawerBaseplateTaskPanel

        def get_all_volumes(group: fc.DocumentObject) -> dict[str, float]:
            """Get volumes of all pieces."""
            return {child.Name: child.Shape.Volume for child in group.Children}

        def get_column_volumes(volumes: dict[str, float], col: int) -> dict[str, float]:
            """Get volumes for pieces in a specific column."""
            return {k: v for k, v in volumes.items() if k.endswith(f"_{col}")}

        # Expected volume for 5x6 baseplate with greedy algorithm
        expected_5x6_volume = 33983.14

        # Step 1: Create drawer baseplates with greedy algorithm
        panel = CreateDrawerBaseplateTaskPanel(ICONDIR / "drawer-baseplate.svg")
        fcg.Control.showDialog(panel)
        panel.drawer__split_algorithm.setCurrentText("Greedy")
        panel._preview_timer.stop()  # noqa: SLF001
        panel.accept()

        # Step 2: Record original volumes and verify 5x6 pieces
        group = self.doc.getObject("DrawerBaseplates")
        self.assertIsNotNone(group, "DrawerBaseplates group should exist")
        assert group is not None
        original_volumes = get_all_volumes(group)
        self.log(f"Original volumes: {original_volumes}")

        original_col0 = get_column_volumes(original_volumes, 0)
        original_col1 = get_column_volumes(original_volumes, 1)
        original_col2 = get_column_volumes(original_volumes, 2)
        self.assertGreater(len(original_col0), 0, "Should have col 0 pieces")
        self.assertGreater(len(original_col2), 0, "Should have col 2 pieces")

        # Verify bottom-left 2x2 pieces (rows 1-2, cols 0-1) are 5x6 plates
        # with expected volume (greedy produces 4 identical 5x6 plates here)
        bottom_left_5x6 = {"Piece_1_0", "Piece_1_1", "Piece_2_0", "Piece_2_1"}
        for piece_name in bottom_left_5x6:
            self.assertAlmostEqual(
                original_volumes[piece_name],
                expected_5x6_volume,
                places=2,
                msg=f"{piece_name} should be 5x6 plate with volume {expected_5x6_volume}",
            )

        # Step 3: Edit, change width to 550
        panel2 = CreateDrawerBaseplateTaskPanel(ICONDIR / "drawer-baseplate.svg", target_obj=group)
        fcg.Control.showDialog(panel2)
        panel2.drawer__drawer_width.setValue(550)
        panel2._preview_timer.stop()  # noqa: SLF001
        panel2.accept()

        # Get updated volumes
        group = self.doc.getObject("DrawerBaseplates")
        assert group is not None
        new_volumes = get_all_volumes(group)
        self.log(f"New volumes after width=550: {new_volumes}")

        new_col0 = get_column_volumes(new_volumes, 0)
        new_col1 = get_column_volumes(new_volumes, 1)
        new_col2 = get_column_volumes(new_volumes, 2)

        # Step 4: Left columns should have same volumes
        self.assertEqual(
            original_col0,
            new_col0,
            "Column 0 volumes should be unchanged after width change",
        )
        self.assertEqual(
            original_col1,
            new_col1,
            "Column 1 volumes should be unchanged after width change",
        )

        # Step 5: Rightmost column should have different volumes
        self.assertNotEqual(
            original_col2,
            new_col2,
            "Column 2 volumes should change after width change",
        )

    def test_drawer_group_no_dependency_on_child_change(self) -> None:
        """Test that DrawerBaseplateGroup does NOT recompute when children change.

        This verifies the PropertyLinkListHidden architecture works correctly:
        - Group stores children without creating recompute dependency
        - Modifying a child should NOT trigger group recompute
        """
        from .commands import ICONDIR, CreateDrawerBaseplateTaskPanel
        from .features import DrawerBaseplateGroup

        # Create drawer baseplates
        panel = CreateDrawerBaseplateTaskPanel(ICONDIR / "drawer-baseplate.svg")
        fcg.Control.showDialog(panel)
        panel._preview_timer.stop()  # noqa: SLF001
        panel.accept()

        group = self.doc.getObject("DrawerBaseplates")
        self.assertIsNotNone(group)
        assert group is not None
        self.assertIsInstance(group.Proxy, DrawerBaseplateGroup)

        children = group.Children
        self.assertGreater(len(children), 0)
        child = children[0]

        # Track if group.execute() is called
        original_execute = group.Proxy.execute
        execute_count = [0]

        def counting_execute(obj: fc.DocumentObject) -> None:
            execute_count[0] += 1
            original_execute(obj)

        group.Proxy.execute = counting_execute

        # Initial recompute to establish baseline
        self.doc.recompute()
        initial_count = execute_count[0]

        # Purge touched state
        group.purgeTouched()

        # Modify child (change placement)
        child.Placement.Base.x += 1.0
        child.touch()

        # Recompute
        self.doc.recompute()
        final_count = execute_count[0]

        self.log(f"Group execute count: initial={initial_count}, final={final_count}")

        # Key assertion: group should NOT recompute when child changes
        self.assertEqual(
            final_count,
            initial_count,
            "DrawerBaseplateGroup should NOT recompute when child changes",
        )


class TestStackedBaseplatesTaskPanel(TestWithDocument):
    """Test creating stacked baseplates through the task panel dialog."""

    def test_create_stacked_baseplates_via_dialog(self) -> None:
        """Test creating stacked baseplates with stacking enabled.

        When stacking is enabled, two objects are created: base and support companion.
        """
        from .commands import ICONDIR, CreateBaseplateTaskPanel

        # Open the task panel dialog
        panel = CreateBaseplateTaskPanel(ICONDIR / "baseplate-std.svg")
        fcg.Control.showDialog(panel)

        # Enable stacking
        panel.stacking__enabled.setChecked(True)

        # Accept the dialog to create the objects
        panel.accept()

        # Verify two objects were created (base + support companion)
        self.assertEqual(len(self.doc.Objects), 2)

        # Find base and support objects
        base_obj = None
        support_obj = None
        for obj in self.doc.Objects:
            if "Support" in obj.Label:
                support_obj = obj
            else:
                base_obj = obj

        self.assertIsNotNone(base_obj)
        self.assertIsNotNone(support_obj)
        self.assertIn("Stacked Baseplates", base_obj.Label)
        self.assertIn("Support", support_obj.Label)

        # Verify base shape is valid
        self.assertTrue(base_obj.Shape.isValid())
        self.assertGreater(base_obj.Shape.Volume, 0)

        # Verify support shape is valid
        self.assertTrue(support_obj.Shape.isValid())
        self.assertGreater(support_obj.Shape.Volume, 0)

        # Verify support references the base
        self.assertEqual(support_obj.SourceBaseplate, base_obj)

    def test_stacking_screw_stubs_volume_difference(self) -> None:
        """Test volume difference when enabling screw stubs on stacked baseplate.

        Steps:
        1. Create baseplate with stacking enabled -> measure support volume
        2. Edit, enable screw stubs -> measure support volume again
        3. Lock volume difference to half-percent precision
        """
        from .commands import ICONDIR, CreateBaseplateTaskPanel

        # Step 1: Create stacked baseplate (stacking enabled, screw_stubs disabled)
        panel = CreateBaseplateTaskPanel(ICONDIR / "baseplate-std.svg")
        fcg.Control.showDialog(panel)
        # Explicitly set grid to 2x2 to isolate from MEM defaults
        panel.baseplate_size__x_grid_count.setValue(2)
        panel.baseplate_size__y_grid_count.setValue(2)
        panel.stacking__enabled.setChecked(True)
        # Explicitly disable screw_stubs to isolate from MEM defaults
        panel.stacking__screw_stubs__enabled.setChecked(False)
        panel.accept()

        # Find the support object
        support_obj = None
        base_obj = None
        for obj in self.doc.Objects:
            if "Support" in obj.Label:
                support_obj = obj
            else:
                base_obj = obj

        self.assertIsNotNone(support_obj)
        self.assertIsNotNone(base_obj)
        self.doc.recompute()

        volume_without_stubs = support_obj.Shape.Volume
        self.assertGreater(volume_without_stubs, 0)

        # Step 2: Edit and enable screw stubs
        panel2 = CreateBaseplateTaskPanel(ICONDIR / "baseplate-std.svg", target_obj=base_obj)
        fcg.Control.showDialog(panel2)
        panel2.stacking__screw_stubs__enabled.setChecked(True)
        panel2.accept()

        self.doc.recompute()
        # Support companion needs explicit touch since it depends on base params
        support_obj.touch()
        self.doc.recompute()
        volume_with_stubs = support_obj.Shape.Volume

        # Volume should increase when screw stubs are enabled (more material)
        self.assertGreater(volume_with_stubs, volume_without_stubs)

        # Lock volume increase ratio to one percent precision
        # Screw stubs should increase volume by ~3.8%
        volume_increase_ratio = (volume_with_stubs - volume_without_stubs) / volume_without_stubs
        # LOCKED INVARIANT: screw stubs add ~3.8% volume
        self.assertAlmostEqual(volume_increase_ratio, 0.0381, delta=0.01)


class TestZZGridfinitySettingsTaskPanel(TestWithDocument):
    """Test the Gridfinity default settings dialog.

    NOTE: Class name starts with 'ZZ' to ensure it runs LAST alphabetically.
    These tests modify saved plugin defaults (e.g., grid_size) which persist
    across tests and would affect volume calculations in other tests.
    """

    def test_grid_size_change_persists(self) -> None:
        """Test that changing grid_size in settings dialog persists after reopen."""
        from .commands import GridfinitySettingsTaskPanel

        # Open settings dialog and change grid_size to 44
        panel = GridfinitySettingsTaskPanel()
        fcg.Control.showDialog(panel)
        grid_size_control = panel._group_controls["fundamentals"]["grid_size"]  # noqa: SLF001
        grid_size_control.setValue(44.0)
        panel.accept()

        # Reopen dialog and verify the value persisted
        panel2 = GridfinitySettingsTaskPanel()
        fcg.Control.showDialog(panel2)
        grid_size_control2 = panel2._group_controls["fundamentals"]["grid_size"]  # noqa: SLF001
        self.assertAlmostEqual(grid_size_control2.value(), 44.0, places=1)
        panel2.reject()

    def test_restart_warning_shown_immediately(self) -> None:
        """Test that restart warning for add_to_part_design is shown on dialog open."""
        from .commands import GridfinitySettingsTaskPanel

        panel = GridfinitySettingsTaskPanel()
        fcg.Control.showDialog(panel)

        # Find the plugin_settings group and check warning display
        plugin_group = None
        for group in panel._groups:  # noqa: SLF001
            if group._group_name == "plugin_settings":  # noqa: SLF001
                plugin_group = group
                break

        self.assertIsNotNone(plugin_group, "plugin_settings group not found")
        warning_displays = getattr(plugin_group, "_warning_displays", {})
        self.assertIn("add_to_part_design", warning_displays)

        # Check that warning label text contains restart message
        # Note: isVisible() may return False in headless test environment
        # even when widget is correctly configured, so we check text content
        warning_display = warning_displays["add_to_part_design"]
        warning_text = warning_display.warning_label.text()
        self.assertIn(
            "restart",
            warning_text.lower(),
            f"Warning label should contain restart message, got: '{warning_text}'",
        )

        panel.reject()

    def test_validation_error_shown_for_invalid_outer_radius(self) -> None:
        """Test that validation error is shown when outer_radius <= main_half_width."""
        from .commands import GridfinitySettingsTaskPanel

        panel = GridfinitySettingsTaskPanel()
        fcg.Control.showDialog(panel)

        # Set outer_radius to 1.0mm (less than default main_half_width of 2.15mm)
        outer_radius_control = panel._group_controls["fundamentals"]["outer_radius"]  # noqa: SLF001
        outer_radius_control.setValue(1.0)

        # Trigger update (simulates user changing value)
        panel._on_control_changed()  # noqa: SLF001

        # Find fundamentals group and check error display
        fundamentals_group = None
        for group in panel._groups:  # noqa: SLF001
            if group._group_name == "fundamentals":  # noqa: SLF001
                fundamentals_group = group
                break

        self.assertIsNotNone(fundamentals_group)
        error_displays = getattr(fundamentals_group, "_error_displays", {})
        self.assertIn("outer_radius", error_displays)

        # Check that error label shows actual error (not just warning)
        # - Error text should mention the validation issue
        # - Error styling is red (#ff4d4d), warning styling is amber (#ffaa00)
        error_display = error_displays["outer_radius"]
        label = error_display.error_label
        error_text = label.text()
        style = label.styleSheet()

        # Verify it's an error (red color) not a warning (amber)
        self.assertIn(
            "#ff4d4d",
            style.lower(),
            f"Expected red error styling, got style: '{style}', text: '{error_text}'",
        )
        # Verify error message content
        self.assertIn(
            "must be greater than",
            error_text.lower(),
            f"Expected validation error message, got: '{error_text}'",
        )

        panel.reject()


class TestGroupDependencyBehavior(TestWithDocument):
    """Isolated test for FreeCAD group dependency behavior.

    This test demonstrates how standard App::DocumentObjectGroupPython creates
    dependencies between parent and children, causing parent to recompute when
    children change.
    """

    def test_standard_group_dependency(self) -> None:
        """Test that standard group creates parent->child dependency.

        When a child object changes, the parent group gets marked as touched
        and will be recomputed. This test documents this behavior.
        """
        # Create a standard group
        group = self.doc.addObject("App::DocumentObjectGroupPython", "TestGroup")

        # Track execute calls on the group
        execute_count = [0]

        class GroupProxy:
            def __init__(self, obj: fc.DocumentObject) -> None:
                obj.Proxy = self

            def execute(self, obj: fc.DocumentObject) -> None:  # noqa: ARG002
                execute_count[0] += 1

        GroupProxy(group)

        # Create a child Part::Box and add to group
        child = self.doc.addObject("Part::Box", "TestChild")
        group.addObject(child)

        # Initial recompute
        self.doc.recompute()
        initial_count = execute_count[0]

        # Check if group is touched after child modification
        group.purgeTouched()
        self.assertFalse(
            group.State == ["Touched"], "Group should not be touched before child change"
        )

        # Modify child
        child.Length = 20.0

        # Check group state BEFORE recompute
        group_touched_after_child_change = "Touched" in group.State

        # Recompute
        self.doc.recompute()
        final_count = execute_count[0]

        # Log results for analysis
        self.log(f"Group touched after child change: {group_touched_after_child_change}")
        self.log(f"Group execute count: initial={initial_count}, final={final_count}")
        self.log(f"Group recomputed due to child change: {final_count > initial_count}")

        # Document actual behavior (this test is for observation, not assertion)
        # The key question: does parent recompute when child changes?
        if final_count > initial_count:
            self.log("CONFIRMED: Standard group DOES recompute when child changes")
        else:
            self.log("OBSERVATION: Standard group does NOT recompute when child changes")

    def test_group_inlist_discovery(self) -> None:
        """Test that getInList() can discover parent from child."""
        # Create a standard group
        group = self.doc.addObject("App::DocumentObjectGroupPython", "TestGroup")

        # Create a child Part::Feature (not Part::Box which is a primitive)
        child = self.doc.addObject("Part::Feature", "TestChild")
        group.addObject(child)

        self.doc.recompute()

        # Test getInList() - should find the group
        # Note: getInList() may not be available on all object types
        if hasattr(child, "getInList"):
            in_list = child.getInList()
            self.log(f"Child getInList(): {[obj.Name for obj in in_list]}")
            self.assertIn(group, in_list, "Group should be in child's InList")
        else:
            # Alternative: check Group property on parent
            self.log("getInList() not available, checking Group property instead")
            self.assertIn(child, group.Group, "Child should be in group.Group")

    def test_property_link_list_hidden_no_dependency(self) -> None:
        """Test that PropertyLinkListHidden creates visual nesting without dependency.

        This is the key test: using PropertyLinkListHidden should allow us to
        store children without creating recompute dependencies.
        """
        # Create a container using Part::FeaturePython (not a group)
        container = self.doc.addObject("Part::FeaturePython", "TestContainer")

        # Track execute calls
        execute_count = [0]

        class ContainerProxy:
            def __init__(self, obj: fc.DocumentObject) -> None:
                # Try to add PropertyLinkListHidden
                obj.addProperty(
                    "App::PropertyLinkListHidden",
                    "Children",
                    "Base",
                    "Children stored without dependency",
                )
                obj.Proxy = self

            def execute(self, obj: fc.DocumentObject) -> None:  # noqa: ARG002
                execute_count[0] += 1

        ContainerProxy(container)

        # Create a child
        child = self.doc.addObject("Part::Box", "TestChild")

        # Add child to container's Children property
        container.Children = [child]

        # Initial recompute
        self.doc.recompute()
        initial_count = execute_count[0]
        self.log(f"Initial execute count: {initial_count}")

        # Purge touched state
        container.purgeTouched()

        # Modify child
        child.Length = 20.0

        # Check container state BEFORE recompute
        container_touched = "Touched" in container.State
        self.log(f"Container touched after child change: {container_touched}")

        # Recompute
        self.doc.recompute()
        final_count = execute_count[0]

        self.log(f"Final execute count: {final_count}")
        self.log(f"Container recomputed due to child change: {final_count > initial_count}")

        # The key assertion: container should NOT recompute when child changes
        if final_count > initial_count:
            self.log("PROBLEM: Container DOES recompute when child changes (dependency exists)")
        else:
            self.log("SUCCESS: Container does NOT recompute when child changes (no dependency)")

        # Assert no dependency - this is what we want
        self.assertEqual(
            final_count,
            initial_count,
            "PropertyLinkListHidden should not create dependency - container should not recompute",
        )

    def test_claim_children_visual_nesting(self) -> None:
        """Test that claimChildren() creates visual nesting with PropertyLinkListHidden.

        This verifies the full solution: PropertyLinkListHidden for storage,
        claimChildren() in ViewProvider for visual nesting, no recompute dependency.
        """
        # Create container
        container = self.doc.addObject("Part::FeaturePython", "TestContainer")

        execute_count = [0]

        class ContainerProxy:
            def __init__(self, obj: fc.DocumentObject) -> None:
                obj.addProperty(
                    "App::PropertyLinkListHidden",
                    "Children",
                    "Base",
                    "Children stored without dependency",
                )
                obj.Proxy = self

            def execute(self, obj: fc.DocumentObject) -> None:  # noqa: ARG002
                execute_count[0] += 1

        class ContainerViewProvider:
            def __init__(self, vobj: Any) -> None:  # noqa: ANN401
                vobj.Proxy = self
                self.Object = vobj.Object

            def claimChildren(self) -> list:  # noqa: N802
                """Return children for visual nesting in tree."""
                return self.Object.Children if hasattr(self.Object, "Children") else []

            def attach(self, vobj: Any) -> None:  # noqa: ANN401
                self.Object = vobj.Object

            def __getstate__(self) -> None:
                return None

            def __setstate__(self, state: Any) -> None:  # noqa: ANN401
                pass

        ContainerProxy(container)
        if fc.GuiUp:
            ContainerViewProvider(container.ViewObject)

        # Create children
        child1 = self.doc.addObject("Part::Box", "Child1")
        child2 = self.doc.addObject("Part::Box", "Child2")

        # Add children
        container.Children = [child1, child2]

        self.doc.recompute()
        initial_count = execute_count[0]

        # Verify claimChildren returns the children
        if fc.GuiUp and hasattr(container.ViewObject.Proxy, "claimChildren"):
            claimed = container.ViewObject.Proxy.claimChildren()
            self.log(f"claimChildren() returns: {[obj.Name for obj in claimed]}")
            self.assertEqual(len(claimed), 2)
            self.assertIn(child1, claimed)
            self.assertIn(child2, claimed)

        # Verify no dependency when child changes
        container.purgeTouched()
        child1.Length = 30.0
        self.doc.recompute()
        final_count = execute_count[0]

        self.log(f"Execute count: initial={initial_count}, final={final_count}")
        self.assertEqual(
            final_count, initial_count, "Container should not recompute when child changes"
        )
