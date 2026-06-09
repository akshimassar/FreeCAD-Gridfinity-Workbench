"""Custom Qt widgets for the Gridfinity workbench UI."""

from __future__ import annotations

try:
    from PySide.QtCore import Qt
    from PySide.QtWidgets import (
        QCheckBox,
        QFrame,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QSizePolicy,
        QStyle,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    # Stubs for non-GUI environments
    QWidget = object
    QLabel = object
    QVBoxLayout = object
    QHBoxLayout = object
    QFrame = object
    QCheckBox = object
    QSizePolicy = object
    QGroupBox = object
    QStyle = object
    Qt = None


class CollapsibleSection(QWidget):
    """A collapsible section with clickable divider header.

    Header shows: ──▶ Title ────────
    With checkbox: ──▶ Title [✓] ────────
    When expanded: ──▼ Title [✓] ────────
    Content is shown/hidden on click. Starts collapsed by default.
    """

    def __init__(
        self,
        title: str = "Options...",
        parent: QWidget | None = None,
        checkbox: QCheckBox | None = None,
    ) -> None:
        """Initialize collapsible section with title and optional checkbox."""
        super().__init__(parent)

        self._collapsed = True
        self._title = title
        self._checkbox = checkbox

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

        # Checkbox (if provided)
        if checkbox is not None:
            header_layout.addWidget(checkbox)

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


class CollapsibleGroupBox(QGroupBox):
    """A QGroupBox with collapsible content and arrow indicator in title.

    Title shows: ▶ Title (collapsed) or ▼ Title (expanded)
    Clicking on title area toggles collapse state.
    Use setCheckable(True) for checkbox in header.
    Native QGroupBox border rendering is preserved.
    """

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        tooltip: str | None = None,
    ) -> None:
        """Initialize collapsible group box."""
        self._base_title = title
        self._collapsed = True
        self._content_widget: QWidget | None = None

        super().__init__(self._make_title(collapsed=True), parent)

        if tooltip:
            self.setToolTip(tooltip)

    def _make_title(self, collapsed: bool) -> str:  # noqa: FBT001
        """Create title string with arrow prefix."""
        arrow = "▶" if collapsed else "▼"
        return f"{arrow} {self._base_title}"

    def mousePressEvent(self, event: object) -> None:  # noqa: N802
        """Handle mouse press - toggle collapse if clicking title area."""
        # Check if click is in title/label region (top part of group box)
        # QGroupBox title is typically in the top ~20 pixels
        style = self.style()
        if style is not None:
            # Get the label rect from style
            from PySide.QtWidgets import QStyleOptionGroupBox

            opt = QStyleOptionGroupBox()
            self.initStyleOption(opt)
            label_rect = style.subControlRect(
                QStyle.CC_GroupBox, opt, QStyle.SC_GroupBoxLabel, self
            )
            checkbox_rect = style.subControlRect(
                QStyle.CC_GroupBox, opt, QStyle.SC_GroupBoxCheckBox, self
            )

            # Get click position
            pos = event.pos()  # type: ignore[union-attr]

            # Toggle if clicked on label (but not checkbox)
            if label_rect.contains(pos) and not checkbox_rect.contains(pos):
                self.set_collapsed(not self._collapsed)
                return

        super().mousePressEvent(event)  # type: ignore[arg-type]

    def set_content_widget(self, widget: QWidget) -> None:
        """Set the content widget that will be shown/hidden."""
        self._content_widget = widget
        # Apply current collapse state
        self._update_content_visibility()

    def _update_content_visibility(self) -> None:
        """Update visibility of content based on collapse state."""
        if self._content_widget is not None:
            self._content_widget.setVisible(not self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:  # noqa: FBT001
        """Set collapsed state."""
        self._collapsed = collapsed
        self.setTitle(self._make_title(collapsed))
        self._update_content_visibility()

    def is_collapsed(self) -> bool:
        """Return current collapsed state."""
        return self._collapsed
