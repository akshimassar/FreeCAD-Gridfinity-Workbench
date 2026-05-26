# This import needs to be first as it set some library paths to use the Freecad python API
import freecad  # noqa: I001,F401

import unittest

from freecad.gridfinity_workbench.param_system import OptionalLayoutParam


class OptionalLayoutParamTest(unittest.TestCase):
    """Tests for OptionalLayoutParam compound parameter."""

    def test_expand_returns_enabled_and_layout_params(self) -> None:
        """Verify expand() returns both enabled boolean and layout params."""
        param = OptionalLayoutParam("custom_layout", "Custom Layout")
        expanded = param.expand()

        self.assertEqual(len(expanded), 2)
        self.assertEqual(expanded[0].name, "custom_layout_enabled")
        self.assertEqual(expanded[1].name, "custom_layout")

    def test_expanded_names_returns_correct_names(self) -> None:
        """Verify expanded_names() returns both param names."""
        param = OptionalLayoutParam("custom_layout", "Custom Layout")
        names = param.expanded_names()

        self.assertIn("custom_layout_enabled", names)
        self.assertIn("custom_layout", names)

    def test_build_control_creates_widget_with_checkbox_and_button(self) -> None:
        """Verify build_control creates widget with checkbox and button children."""
        from PySide.QtWidgets import QApplication, QCheckBox, QPushButton

        # Ensure QApplication exists
        if QApplication.instance() is None:
            QApplication([])

        param = OptionalLayoutParam("custom_layout", "Custom Layout")
        widget = param.build_control({"custom_layout_enabled": False, "custom_layout": None})

        # Find children by type
        checkbox = None
        button = None
        for child in widget.children():
            if isinstance(child, QCheckBox):
                checkbox = child
            elif isinstance(child, QPushButton):
                button = child

        self.assertIsNotNone(checkbox, "Widget should have QCheckBox child")
        self.assertIsNotNone(button, "Widget should have QPushButton child")
        self.assertEqual(button.objectName(), "layout_button")

    def test_connect_signals_sets_callback_on_button(self) -> None:
        """Verify connect_signals stores callback on button."""
        from PySide.QtWidgets import QApplication, QPushButton

        if QApplication.instance() is None:
            QApplication([])

        param = OptionalLayoutParam("custom_layout", "Custom Layout")
        widget = param.build_control({"custom_layout_enabled": False, "custom_layout": None})

        callback_called = [False]

        def test_callback() -> None:
            callback_called[0] = True

        param.connect_signals(widget, test_callback)

        # Find button and verify callback is set
        button = None
        for child in widget.children():
            if isinstance(child, QPushButton):
                button = child
                break

        self.assertIsNotNone(button)
        self.assertTrue(
            hasattr(button, "_layout_changed_callback"),
            "Button should have _layout_changed_callback attribute",
        )
        self.assertEqual(button._layout_changed_callback, test_callback)  # noqa: SLF001

    def test_callback_is_invoked_when_layout_changes(self) -> None:
        """Verify callback is invoked when layout value changes."""
        from PySide.QtWidgets import QApplication, QPushButton

        if QApplication.instance() is None:
            QApplication([])

        param = OptionalLayoutParam("custom_layout", "Custom Layout")
        widget = param.build_control({"custom_layout_enabled": False, "custom_layout": None})

        callback_called = [False]

        def test_callback() -> None:
            callback_called[0] = True

        param.connect_signals(widget, test_callback)

        # Find button
        button = None
        for child in widget.children():
            if isinstance(child, QPushButton):
                button = child
                break

        self.assertIsNotNone(button)

        # Simulate what happens after layout dialog returns:
        # The on_click handler sets layout_value and calls the callback
        button.setProperty("layout_value", [[True, False], [False, True]])
        if button._layout_changed_callback is not None:  # noqa: SLF001
            button._layout_changed_callback()  # noqa: SLF001

        self.assertTrue(
            callback_called[0],
            "Callback should have been called when layout changes",
        )

    def test_read_control_extracts_values(self) -> None:
        """Verify read_control extracts enabled and layout values."""
        from PySide.QtWidgets import QApplication

        if QApplication.instance() is None:
            QApplication([])

        param = OptionalLayoutParam("custom_layout", "Custom Layout")
        widget = param.build_control({"custom_layout_enabled": True, "custom_layout": [[True]]})

        values = param.read_control(widget)

        self.assertIn("custom_layout_enabled", values)
        self.assertIn("custom_layout", values)


if __name__ == "__main__":
    unittest.main()
