"""Task panel base classes for Gridfinity workbench.

Provides unified architecture for feature-creating task panels with:
- Separate preview object (temporary Part::Feature sibling)
- Feature object created only on accept
- Common preview lifecycle, timer, visuals, error rendering
"""

# ruff: noqa: D102, D107, N802
from __future__ import annotations

import contextlib
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import FreeCAD as fc  # noqa: N813
import FreeCADGui as fcg  # noqa: N813
from PySide.QtCore import QTimer
from PySide.QtWidgets import QDialogButtonBox, QVBoxLayout, QWidget

if TYPE_CHECKING:
    from pathlib import Path

    import Part

    from .param_system import CombinedParams

PREVIEW_SHAPE_COLOR = (100.0 / 255.0, 1.0, 1.0)  # 0x64FFFF
PREVIEW_TRANSPARENCY = 40


def _standard_buttons_ok_cancel() -> int:
    """Return Ok|Cancel button flags compatible with both PySide2 and PySide6."""
    ok = QDialogButtonBox.Ok
    cancel = QDialogButtonBox.Cancel
    if hasattr(ok, "value"):
        return ok.value | cancel.value
    return int(ok) | int(cancel)


class BaseFeatureTaskPanel(ABC):
    """Base class for all feature-creating task panels.

    Preview model: Always creates a separate preview object (Part::Feature sibling)
    that displays the computed shape. The actual feature object is created only on accept.

    Subclasses must implement:
    - _get_params() -> CombinedParams
    - _build_preview_shape() -> Part.Shape
    - _format_label(params) -> str
    - _create_feature_object() -> fc.DocumentObject
    - _on_accept_finalize(output_obj, params) - post-accept logic
    """

    _DEBOUNCE_MS = 500

    def __init__(
        self,
        pixmap: Path | str,
        edit_obj: fc.DocumentObject | None = None,
        *,
        window_title: str,
    ) -> None:
        self._pixmap = pixmap
        self._edit_obj = edit_obj
        self._preview_obj: fc.DocumentObject | None = None
        self._preview_timer: QTimer | None = None

        self.form = QWidget()
        self.form.setWindowTitle(
            f"Edit {window_title}" if edit_obj is not None else f"Create {window_title}"
        )

    def _setup_ui(self, params: CombinedParams) -> dict[str, QWidget]:
        """Build UI from params and return controls dict."""
        layout = QVBoxLayout(self.form)
        controls, _ = params.build_ui(layout)
        for key, widget in controls.items():
            setattr(self, key, widget)
        return controls

    def _setup_preview(self, params: CombinedParams, controls: dict[str, QWidget]) -> None:
        """Create preview object and connect signals."""
        self._preview_obj = fc.ActiveDocument.addObject("Part::Feature", "Preview")
        if fc.GuiUp and self._preview_obj is not None:
            self._set_show_in_tree(self._preview_obj, visible=False)
            self._apply_preview_visuals(self._preview_obj)

        self._preview_timer = QTimer(self.form)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(self._DEBOUNCE_MS)
        self._preview_timer.timeout.connect(self._update_preview)

        params.connect_control_signals(controls, self._on_control_changed)
        self._update_preview()

    def _preview_style(self) -> tuple[tuple[float, float, float], int]:
        return PREVIEW_SHAPE_COLOR, PREVIEW_TRANSPARENCY

    def _apply_preview_visuals(self, obj: fc.DocumentObject) -> None:
        """Apply preview color/transparency to an object."""
        if not fc.GuiUp or obj is None:
            return
        color, transparency = self._preview_style()
        try:
            view = obj.ViewObject
        except (AttributeError, ReferenceError):
            return
        if hasattr(view, "ShapeColor"):
            view.ShapeColor = color
            if hasattr(view, "LineColor"):
                view.LineColor = color
            view.Transparency = transparency

    def _set_show_in_tree(self, obj: fc.DocumentObject, *, visible: bool) -> None:
        if not fc.GuiUp:
            return
        try:
            view = obj.ViewObject
        except ReferenceError:
            return
        if hasattr(view, "ShowInTree"):
            with contextlib.suppress(Exception):
                view.ShowInTree = visible

    def _on_control_changed(self) -> None:
        if self._preview_timer is not None:
            self._preview_timer.start()

    def _stop_preview_timer(self) -> None:
        if self._preview_timer is not None:
            self._preview_timer.stop()

    def _remove_preview_object(self) -> None:
        if self._preview_obj is not None:
            fc.ActiveDocument.removeObject(self._preview_obj.Name)
            self._preview_obj = None

    def _validate_and_render_errors(self, params: CombinedParams) -> bool:
        """Validate params and render errors. Returns True if valid."""
        params.update_from_ui_owner(self)
        errors = params.validate()
        params.render_errors(errors)
        return not errors

    def _show_status_message(self, message: str, duration_ms: int = 2500) -> None:
        if fc.GuiUp and fcg is not None:
            try:
                status_bar = fcg.getMainWindow().statusBar()
                status_bar.showMessage(message, duration_ms)
            except (AttributeError, RuntimeError):
                pass

    def getStandardButtons(self) -> int:
        return _standard_buttons_ok_cancel()

    def _update_preview(self) -> None:
        """Update preview shape from current params."""
        params = self._get_params()
        params.update_from_ui_owner(self)
        errors = params.validate()
        params.render_errors(errors)
        if errors:
            return

        start = time.perf_counter()
        shape = self._build_preview_shape(params)
        if self._preview_obj is not None and shape is not None:
            self._preview_obj.Shape = shape
            label = self._format_label(params)
            self._preview_obj.Label = f"[Preview] {label}"
        elapsed = time.perf_counter() - start
        self._show_status_message(f"Preview built in {elapsed:.2f} seconds")

    def accept(self) -> bool:
        self._stop_preview_timer()

        params = self._get_params()
        if not self._validate_and_render_errors(params):
            return False

        # Create or use existing feature object
        output_obj = self._edit_obj if self._edit_obj is not None else self._create_feature_object()

        params.to_obj(output_obj)
        output_obj.Label = self._format_label(params)

        self._on_accept_finalize(output_obj, params)

        self._remove_preview_object()
        self._set_show_in_tree(output_obj, visible=True)

        fc.ActiveDocument.recompute()
        fcg.SendMsgToActiveView("ViewFit")
        fcg.Control.closeDialog()
        return True

    def reject(self) -> bool:
        self._stop_preview_timer()
        self._remove_preview_object()
        fcg.Control.closeDialog()
        return True

    @abstractmethod
    def _get_params(self) -> CombinedParams:
        """Return the params instance for this panel."""
        ...

    @abstractmethod
    def _build_preview_shape(self, params: CombinedParams) -> Part.Shape:
        """Build and return the preview shape from params."""
        ...

    @abstractmethod
    def _format_label(self, params: CombinedParams) -> str:
        """Format the FreeCAD object label from params."""
        ...

    @abstractmethod
    def _create_feature_object(self) -> fc.DocumentObject:
        """Create the actual feature object (called on accept for new objects)."""
        ...

    @abstractmethod
    def _on_accept_finalize(self, output_obj: fc.DocumentObject, params: CombinedParams) -> None:
        """Post-accept finalization (companions, defaults, etc.)."""
        ...


class SingleFeatureTaskPanel(BaseFeatureTaskPanel):
    """Task panel for creating a single feature object (Baseplate, ConnectingClip, Bins).

    Preview is a separate Part::Feature. Feature object is created on accept.
    """


class GroupFeatureTaskPanel(BaseFeatureTaskPanel):
    """Task panel for creating a group with child objects (DrawerBaseplates).

    Creates group object during init (needed for params storage).
    Preview shows combined shape. On accept, triggers child creation.
    """

    def __init__(
        self,
        pixmap: Path | str,
        edit_obj: fc.DocumentObject | None = None,
        *,
        window_title: str,
    ) -> None:
        super().__init__(pixmap, edit_obj, window_title=window_title)
        self._target_obj: fc.DocumentObject | None = None
        self._created_new_group = False
        self._original_label: str | None = None

    def _setup_group_object(
        self,
        params: CombinedParams,  # noqa: ARG002
        group_name: str,
        group_feature_class: type,
        view_provider_class: type,
    ) -> None:
        """Create or use existing group object."""
        if self._edit_obj is not None:
            self._target_obj = self._edit_obj
            self._original_label = self._edit_obj.Label
        else:
            self._target_obj = fc.ActiveDocument.addObject(
                "App::DocumentObjectGroupPython", group_name
            )
            self._created_new_group = True
            group_feature_class(self._target_obj)
            if fc.GuiUp and self._target_obj is not None:
                view_object = self._target_obj.ViewObject
                view_provider_class(view_object, str(self._pixmap))
                self._set_show_in_tree(self._target_obj, visible=False)

    def accept(self) -> bool:
        self._stop_preview_timer()

        params = self._get_params()
        if not self._validate_and_render_errors(params):
            return False

        if self._target_obj is None:
            return False

        params.to_obj(self._target_obj)
        self._target_obj.Label = self._format_label(params)

        # Set preview mode off to trigger child creation on recompute
        if hasattr(self._target_obj, "PreviewBuildMode"):
            self._target_obj.PreviewBuildMode = False

        self._on_accept_finalize(self._target_obj, params)

        self._remove_preview_object()

        fc.ActiveDocument.recompute()

        # Show group and children in tree
        self._set_show_in_tree(self._target_obj, visible=True)
        for child in getattr(self._target_obj, "Group", []):
            self._set_show_in_tree(child, visible=True)

        fcg.SendMsgToActiveView("ViewFit")
        fcg.Control.closeDialog()
        return True

    def reject(self) -> bool:
        self._stop_preview_timer()
        self._remove_preview_object()

        if self._created_new_group and self._target_obj is not None:
            for child in list(getattr(self._target_obj, "Group", [])):
                fc.ActiveDocument.removeObject(child.Name)
            fc.ActiveDocument.removeObject(self._target_obj.Name)
            self._target_obj = None
        elif self._original_label is not None and self._target_obj is not None:
            self._target_obj.Label = self._original_label

        fcg.Control.closeDialog()
        return True

    def _create_feature_object(self) -> fc.DocumentObject:
        """Not used for groups - group is created in __init__."""
        raise NotImplementedError("Groups are created in __init__, not on accept")
