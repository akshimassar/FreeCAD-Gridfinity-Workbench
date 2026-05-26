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


class TestWithDocument(unittest.TestCase):
    """Base class for test that do everything on an open document.

    If a test fails, the file can be found in temporary directory (/tmp on Linux).
    Captures stdout/stderr to detect tracebacks during test execution.
    """

    _original_stderr: Any = None
    _original_stdout: Any = None
    _captured_stderr: StringIO | None = None
    _debug_log: list[str]

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

    def setUp(self) -> None:
        # Initialize debug log
        self._debug_log = []

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

        # Check for traceback indicators
        if "Traceback (most recent call last):" in captured:
            self.fail(f"Traceback detected during test execution:\n{captured}")


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
        obj.baseplate_size_custom_layout_enabled = True
        obj.baseplate_size_custom_layout = json.dumps(l_shape_layout)

        self.doc.recompute()
        self.assertTrue(obj.Shape.isValid())
        self.assertEqual(len(obj.Shape.Solids), 1)
        volume_l_shape = obj.Shape.Volume
        # 3 cells out of 4 = approximately 75% of reference volume
        ratio = volume_l_shape / volume_reference
        self.assertAlmostEqual(ratio, 0.75, places=1)

        # Step 4: Enable top filler (uses default width), disable layout
        obj.baseplate_size_filler_top_enabled = True
        obj.baseplate_size_custom_layout_enabled = False

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
        obj_single.baseplate_size_x_grid_count = 10
        obj_single.baseplate_size_y_grid_count = 10
        obj_single.baseplate_size_custom_layout_enabled = True
        obj_single.baseplate_size_custom_layout = json.dumps(layout_single)
        obj_single.click_springs_enabled = False

        # Test case 2: 2x1 L-shape at positions (3,5) and (4,5)
        layout_2x1 = [[False] * 10 for _ in range(10)]
        layout_2x1[3][5] = True
        layout_2x1[4][5] = True

        obj_2x1 = self.doc.addObject("Part::FeaturePython", "TwoCellLayout")
        features.Baseplate(obj_2x1)
        obj_2x1.baseplate_size_x_grid_count = 10
        obj_2x1.baseplate_size_y_grid_count = 10
        obj_2x1.baseplate_size_custom_layout_enabled = True
        obj_2x1.baseplate_size_custom_layout = json.dumps(layout_2x1)
        obj_2x1.click_springs_enabled = False

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
        expected_controls = set()
        for group_name, group in params._param_groups.items():  # noqa: SLF001
            # Get expanded param names from compound params (these are NOT individual controls)
            expanded_from_compound = set()
            for cp in group._compound_params.values():  # noqa: SLF001
                expanded_from_compound.update(cp.expanded_names())
            # Add individual params that are NOT from compound params
            for param_name in group._parameters:  # noqa: SLF001
                if param_name not in expanded_from_compound:
                    expected_controls.add(f"{group_name}__{param_name}")
            # Add compound params (which render as single UI controls)
            for cp_name in group._compound_params:  # noqa: SLF001
                expected_controls.add(f"{group_name}__{cp_name}")

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

    def test_stacked_baseplates_dialog_fields_match_params(self) -> None:
        """Verify CreateStackedBaseplatesTaskPanel has no unexpected or missing fields."""
        from .commands import ICONDIR, CreateStackedBaseplatesTaskPanel
        from .param import CombinedStackedBaseplatesParams

        # Create panel
        panel = CreateStackedBaseplatesTaskPanel(ICONDIR / "stacked-baseplates.svg")
        fcg.Control.showDialog(panel)

        # Extract control names from panel
        dialog_controls = self._extract_dialog_control_names(panel)

        # Extract expected param names
        # Prefixes now match group names exactly (derived from class names)
        params = CombinedStackedBaseplatesParams()
        expected_controls = set()
        for group_name, group in params._param_groups.items():  # noqa: SLF001
            # Get expanded param names from compound params (these are NOT individual controls)
            expanded_from_compound = set()
            for cp in group._compound_params.values():  # noqa: SLF001
                expanded_from_compound.update(cp.expanded_names())
            # Add individual params that are NOT from compound params
            for param_name in group._parameters:  # noqa: SLF001
                if param_name not in expanded_from_compound:
                    expected_controls.add(f"{group_name}__{param_name}")
            # Add compound params (which render as single UI controls)
            for cp_name in group._compound_params:  # noqa: SLF001
                expected_controls.add(f"{group_name}__{cp_name}")

        # Find discrepancies
        unexpected = dialog_controls - expected_controls
        missing = expected_controls - dialog_controls

        if unexpected:
            self.fail(f"Unexpected dialog controls not in params: {sorted(unexpected)}")
        if missing:
            self.fail(f"Missing dialog controls expected from params: {sorted(missing)}")

        panel.reject()


class TestDrawerBaseplateTaskPanel(TestWithDocument):
    """Test creating drawer baseplates through the task panel dialog."""

    def test_create_drawer_baseplate_via_dialog(self) -> None:
        """Test creating drawer baseplates with default settings."""
        from .commands import ICONDIR, CreateDrawerBaseplateTaskPanel

        # Open the task panel dialog
        panel = CreateDrawerBaseplateTaskPanel(ICONDIR / "drawer-baseplate.svg")
        fcg.Control.showDialog(panel)

        # Accept the dialog to create the object
        panel.accept()

        # Verify object was created
        self.assertEqual(len(self.doc.Objects), 1)
        obj = self.doc.Objects[0]
        self.assertIn("Drawer Baseplates", obj.Label)

        # Verify shape is valid
        self.assertTrue(obj.Shape.isValid())
        self.assertGreater(obj.Shape.Volume, 0)
        # Drawer baseplate is a compound of multiple solids
        self.assertGreater(len(obj.Shape.Solids), 0)


class TestStackedBaseplatesTaskPanel(TestWithDocument):
    """Test creating stacked baseplates through the task panel dialog."""

    def test_create_stacked_baseplates_via_dialog(self) -> None:
        """Test creating stacked baseplates with default settings.

        Stacked baseplates create two objects: base and support companion.
        """
        from .commands import ICONDIR, CreateStackedBaseplatesTaskPanel

        # Open the task panel dialog
        panel = CreateStackedBaseplatesTaskPanel(ICONDIR / "stacked-baseplates.svg")
        fcg.Control.showDialog(panel)

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
        self.assertEqual(support_obj.SourceStackedBaseplates, base_obj)


class TestGridfinitySettingsTaskPanel(TestWithDocument):
    """Test the Gridfinity default settings dialog."""

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
