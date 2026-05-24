import unittest
from pathlib import Path
from tempfile import gettempdir

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
    """

    def setUp(self) -> None:
        fcg.activateWorkbench("GridfinityWorkbench")
        self.doc = fc.newDocument(DOC_NAME)
        self.filepath = f"{TEMPDIR / self.__class__.__name__!s}_{self._testMethodName}.FCStd"

    def tearDown(self) -> None:
        self.doc.saveAs(str(self.filepath))
        fc.closeDocument(DOC_NAME)


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
