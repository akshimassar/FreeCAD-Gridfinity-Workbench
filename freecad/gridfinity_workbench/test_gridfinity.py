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
    _captured_stdout: StringIO | None = None

    def setUp(self) -> None:
        # Capture stdout/stderr to detect tracebacks
        self._original_stderr = sys.stderr
        self._original_stdout = sys.stdout
        self._captured_stderr = StringIO()
        self._captured_stdout = StringIO()
        sys.stderr = self._captured_stderr
        sys.stdout = self._captured_stdout

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
        panel2.connecting_clip__enabled.setChecked(False)
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
