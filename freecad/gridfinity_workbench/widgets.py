"""Custom Qt widgets for the Gridfinity workbench UI."""

from __future__ import annotations

try:
    from PySide.QtCore import Qt
    from PySide.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
except ImportError:
    # Stubs for non-GUI environments
    QWidget = object
    QLabel = object
    QVBoxLayout = object
    QHBoxLayout = object
    QFrame = object
    Qt = None


class CollapsibleSection(QWidget):
    """A collapsible section with clickable divider header.

    Header shows: ──▶ Options... ────────
    When expanded: ──▼ Options... ────────
    Content is shown/hidden on click. Starts collapsed by default.
    """

    def __init__(self, title: str = "Options...", parent: QWidget | None = None) -> None:
        """Initialize collapsible section with title."""
        super().__init__(parent)

        self._collapsed = True
        self._title = title

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)

        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        # Left line
        self._left_line = QFrame()
        self._left_line.setFrameShape(QFrame.HLine)
        self._left_line.setFrameShadow(QFrame.Sunken)
        self._left_line.setFixedWidth(10)
        header_layout.addWidget(self._left_line)

        # Arrow label
        self._arrow_label = QLabel("▶")
        self._arrow_label.setCursor(Qt.PointingHandCursor)
        self._arrow_label.mousePressEvent = self._on_header_click
        header_layout.addWidget(self._arrow_label)

        # Title label
        self._title_label = QLabel(title)
        self._title_label.setCursor(Qt.PointingHandCursor)
        self._title_label.mousePressEvent = self._on_header_click
        header_layout.addWidget(self._title_label)

        # Right line (expanding)
        self._right_line = QFrame()
        self._right_line.setFrameShape(QFrame.HLine)
        self._right_line.setFrameShadow(QFrame.Sunken)
        header_layout.addWidget(self._right_line, 1)  # stretch factor 1

        layout.addWidget(header_widget)

        # Content container
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content.hide()
        layout.addWidget(self._content)

    def _on_header_click(self, _event: object) -> None:
        """Handle header click to toggle collapse state."""
        self.set_collapsed(not self._collapsed)

    def set_content(self, widget: QWidget) -> None:
        """Set the content widget to show/hide."""
        # Clear existing content
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        self._content_layout.addWidget(widget)

    def set_collapsed(self, collapsed: bool) -> None:  # noqa: FBT001
        """Set collapsed state programmatically."""
        self._collapsed = collapsed
        self._arrow_label.setText("▶" if collapsed else "▼")
        self._content.setVisible(not collapsed)

    def is_collapsed(self) -> bool:
        """Return current collapsed state."""
        return self._collapsed
