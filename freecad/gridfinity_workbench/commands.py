"""Gridfinity workbench commands module.

Contains command objects representing what should happen on a button press.
"""

# ruff: noqa: D101, D102, D107, N802
from __future__ import annotations

import contextlib
import re
import time
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import FreeCAD as fc  # noqa: N813
import FreeCADGui as fcg  # noqa: N813
from PySide.QtCore import Qt, QTimer
from PySide.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from . import baseplate_builder, custom_shape, features, utils
from .param import CombinedBaseplateParams


def _standard_buttons_ok_cancel() -> int:
    """Return Ok|Cancel button flags compatible with both PySide2 and PySide6."""
    ok = QDialogButtonBox.Ok
    cancel = QDialogButtonBox.Cancel
    # PySide6 enums have .value, PySide2 enums are already int-like
    if hasattr(ok, "value"):
        return ok.value | cancel.value
    return int(ok) | int(cancel)


if TYPE_CHECKING:
    import Part

    from .param_system import CombinedParams

ICONDIR = Path(__file__).parent / "icons"

PASCAL_CASE_REGEX = re.compile(r"(?<!^)(?=[A-Z])")

PREVIEW_SHAPE_COLOR = (100.0 / 255.0, 1.0, 1.0)  # 0x64FFFF
PREVIEW_TRANSPARENCY = 40


class ViewProviderGridfinity:
    """Gridfinity workbench viewprovider."""

    def __init__(self, obj: fcg.ViewProviderDocumentObject, icon_path: str) -> None:
        # Set this object to the proxy object of the actual view provider
        obj.Proxy = self
        self._check_attr()
        self.icon_path = icon_path or str(ICONDIR / "gridfinity_workbench_icon.svg")

    def _check_attr(self) -> None:
        """Check for missing attributes.

        Required to set icon_path when reopening after saving.
        """
        if not hasattr(self, "icon_path") or not Path(self.icon_path).exists():
            self.icon_path = str(ICONDIR / "gridfinity_workbench_icon.svg")

    def attach(self, vobj: fcg.ViewProviderDocumentObject) -> None:
        """Attach viewproviderdocument object to self."""
        self.vobj = vobj

    def getIcon(self) -> str:
        """Get icons path."""
        self._check_attr()
        return self.icon_path

    def dumps(self) -> dict:
        """Needed for JSON Serialization when saving a file containing gridfinity object."""
        self._check_attr()
        return {"icon_path": self.icon_path}

    def loads(self, state: dict) -> None:
        """Needed for JSON Serialization when saving a file containing gridfinity object."""
        if state and "icon_path" in state:
            self.icon_path = state["icon_path"]

    def doubleClicked(self, vobj: fcg.ViewProviderDocumentObject) -> bool:  # noqa: PLR0911
        """Open edit task dialog on double click for simple baseplate."""
        obj = getattr(vobj, "Object", None)
        if obj is None:
            return False
        proxy = getattr(obj, "Proxy", None)
        if isinstance(proxy, features.DrawerBaseplate):
            fcg.Control.showDialog(CreateDrawerBaseplateTaskPanel(self.icon_path, target_obj=obj))
            return True
        # Keep subclass checks before Baseplate: StackedBaseplates inherits Baseplate,
        # and generic dispatch here would skip stacked-specific relabeling/link handling.
        if isinstance(proxy, features.StackedBaseplates):
            fcg.Control.showDialog(CreateStackedBaseplatesTaskPanel(self.icon_path, target_obj=obj))
            return True
        if isinstance(proxy, features.StackedBaseplatesSupport):
            source = getattr(obj, "SourceStackedBaseplates", None)
            if source is None:
                return False
            fcg.Control.showDialog(
                CreateStackedBaseplatesTaskPanel(self.icon_path, target_obj=source),
            )
            return True
        if isinstance(proxy, features.Baseplate):
            fcg.Control.showDialog(CreateBaseplateTaskPanel(self.icon_path, target_obj=obj))
            return True
        if isinstance(proxy, features.ConnectingClip):
            fcg.Control.showDialog(CreateConnectingClipTaskPanel(self.icon_path, target_obj=obj))
            return True
        return False


class BaseCommand:
    """Base for gridfinity workbench command.

    A command should derive from this BaseCommand class.

    """

    def __init__(
        self,
        *,
        name: str,
        pixmap: Path,
        menu_text: str,
        tooltip: str,
    ) -> None:
        self.name = name
        self.pixmap = pixmap
        self.menu_text = menu_text
        self.tooltip = tooltip

    def IsActive(self) -> bool:
        """Check if command should be active."""
        return fc.ActiveDocument is not None

    def Activated(self) -> None:
        """Execute when command is activated."""
        raise NotImplementedError

    def GetResources(self) -> dict[str, str]:
        """Get command resources."""
        return {
            "Pixmap": str(self.pixmap),
            "MenuText": self.menu_text,
            "ToolTip": self.tooltip,
        }


def _section_label(text: str, *, indent_px: int = 0) -> QLabel:
    label = QLabel(text)
    style = "font-weight: bold;"
    if indent_px:
        style += f" padding-left: {indent_px}px;"
    label.setStyleSheet(style)
    return label


def _mm_spinbox(value: float, *, minimum: float = 0.0, maximum: float = 100.0) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setDecimals(2)
    box.setMinimum(minimum)
    box.setMaximum(maximum)
    box.setSuffix(" mm")
    box.setValue(value)
    return box


def _build_fundamentals_section(layout: QVBoxLayout, *, show_note: bool) -> dict[str, QWidget]:
    from .param import FundamentalsParams

    # Create fundamentals param group and build its UI
    params = FundamentalsParams()
    controls, widget = params.build_ui(None, "Fundamentals", show_note)

    # Add to layout
    layout.addWidget(widget)

    # Add note if needed
    if show_note:
        compatibility_note = QLabel(
            "Changing these values affects Gridfinity compatibility with other objects.",
        )
        compatibility_note.setWordWrap(True)
        compatibility_note.setAlignment(Qt.AlignLeft)
        layout.insertWidget(0, compatibility_note)  # Insert before the main widget
        # We need to re-add the fundamentals label after the note
        layout.insertWidget(0, _section_label("Fundamentals"))

    # Prefix control names to match expected return format
    prefixed_controls = {}
    for param_name, control in controls.items():
        prefixed_controls[f"fundamentals__{param_name}"] = control

    return prefixed_controls


def _build_baseplate_section(layout: QVBoxLayout) -> dict[str, QWidget]:
    from .param import (
        BaseplateCoreParams,
        ClickSpringsParams,
        ConnectingClipsParams,
        JunctionScrewsParams,
    )

    # Create the core baseplate param group and build its UI
    core_params = BaseplateCoreParams()
    core_controls, core_widget = core_params.build_ui(None, "Baseplate", show_description=True)

    # Add core controls to layout
    layout.addWidget(core_widget)

    # Add to main controls dict
    controls: dict[str, QWidget] = {}
    for param_name, control in core_controls.items():
        controls[f"baseplate_core__{param_name}"] = control

    # Create and add snap springs section
    click_params = ClickSpringsParams()
    click_controls, click_widget = click_params.build_ui(
        None,
        "",
        show_description=True,
    )  # No title - we'll add our own
    # Add styled label for subsection
    click_label = _section_label("Snap springs", indent_px=20)
    layout.addWidget(click_label)
    layout.addWidget(click_widget)

    # Add click spring controls to main dict
    for param_name, control in click_controls.items():
        controls[f"click_springs__{param_name}"] = control

    # Create and add junction screws section
    junction_params = JunctionScrewsParams()
    junction_controls, junction_widget = junction_params.build_ui(
        None,
        "",
        show_description=True,
    )  # No title
    # Add styled label for subsection
    junction_label = _section_label("Junction screws", indent_px=20)
    layout.addWidget(junction_label)
    layout.addWidget(junction_widget)

    # Add junction screw controls to main dict
    for param_name, control in junction_controls.items():
        controls[f"junction_screws__{param_name}"] = control

    # Create and add connecting clips section
    clip_params = ConnectingClipsParams()
    clip_controls, clip_widget = clip_params.build_ui(
        None,
        "",
        show_description=True,
    )  # No title
    # Add styled label for subsection
    clip_label = _section_label("Connecting clips", indent_px=20)
    layout.addWidget(clip_label)
    layout.addWidget(clip_widget)

    # Add clip controls to main dict
    for param_name, control in clip_controls.items():
        controls[f"connecting_clips__{param_name}"] = control

    return controls


def _build_bin_section(layout: QVBoxLayout) -> dict[str, QWidget]:
    # NOTE: Bin section needs rework. Hardcoded defaults for now.
    from PySide.QtWidgets import QFormLayout

    layout.addWidget(_section_label("Bin"))
    form = QFormLayout()
    form.setContentsMargins(20, 0, 0, 0)
    clearance = _mm_spinbox(0.25)  # NOTE: migrate to param system after bin rework
    form.addRow("Clearance", clearance)
    half_grid_size = QCheckBox()
    half_grid_size.setChecked(False)  # NOTE: half_grid_size dropped until bin rework
    form.addRow("Half Grid Size", half_grid_size)
    layout.addLayout(form)
    return {"clearance": clearance, "half_grid_size": half_grid_size}


class CreateCommand(BaseCommand):
    """Base for gridfinity workbench command.

    Used for commands that always create an object.

    """

    def __init__(
        self,
        *,
        name: str,
        gridfinity_function: type[features.FoundationGridfinity],
        pixmap: Path,
    ) -> None:
        super().__init__(
            name=name,
            pixmap=pixmap,
            menu_text=PASCAL_CASE_REGEX.sub(" ", name),
            tooltip=f"Create a {PASCAL_CASE_REGEX.sub(' ', name)}.",
        )
        self.gridfinity_function = gridfinity_function

    def Activated(self) -> None:
        """Execute when command is activated."""
        obj = utils.new_object(self.name)
        if fc.GuiUp:
            view_object: fcg.ViewProviderDocumentObject = obj.ViewObject
            ViewProviderGridfinity(view_object, str(self.pixmap))

        self.gridfinity_function(obj)

        fc.ActiveDocument.recompute()
        fcg.SendMsgToActiveView("ViewFit")


class CreateBinBlank(CreateCommand):
    def __init__(self) -> None:
        super().__init__(
            name="BinBlank",
            gridfinity_function=features.BinBlank,
            pixmap=ICONDIR / "bin-blank.svg",
        )


class CreateBinBase(CreateCommand):
    def __init__(self) -> None:
        super().__init__(
            name="BinBase",
            gridfinity_function=features.BinBase,
            pixmap=ICONDIR / "bin-base.svg",
        )


class CreateSimpleStorageBin(CreateCommand):
    def __init__(self) -> None:
        super().__init__(
            name="SimpleStorageBin",
            gridfinity_function=features.SimpleStorageBin,
            pixmap=ICONDIR / "bin-std.svg",
        )


class CreateEcoBin(CreateCommand):
    def __init__(self) -> None:
        super().__init__(
            name="EcoBin",
            gridfinity_function=features.EcoBin,
            pixmap=ICONDIR / "eco_bin.svg",
        )


class CreatePartsBin(CreateCommand):
    def __init__(self) -> None:
        super().__init__(
            name="PartsBin",
            gridfinity_function=features.PartsBin,
            pixmap=ICONDIR / "parts_bin.svg",
        )


class CreateBaseplate(CreateCommand):
    def __init__(self) -> None:
        super().__init__(
            name="Baseplate",
            gridfinity_function=features.Baseplate,
            pixmap=ICONDIR / "baseplate-std.svg",
        )

    def Activated(self) -> None:
        fcg.Control.showDialog(CreateBaseplateTaskPanel(ICONDIR / "baseplate-obj.svg"))


class CreateDrawerBaseplate(BaseCommand):
    def __init__(self) -> None:
        super().__init__(
            name="DrawerBaseplate",
            pixmap=ICONDIR / "drawer-baseplate.svg",
            menu_text="Fit drawer with printable baseplates",
            tooltip="Fit drawer with printable baseplates",
        )

    def Activated(self) -> None:
        fcg.Control.showDialog(CreateDrawerBaseplateTaskPanel(self.pixmap))


class CreateDrawerBaseplateTaskPanel:
    """Task panel for planning drawer baseplate splits."""

    def __init__(
        self,
        pixmap: Path | str,
        target_obj: fc.DocumentObject | None = None,
    ) -> None:
        from .param import CombinedDrawerBaseplateParams

        self._pixmap = pixmap
        self._edit_obj = target_obj
        self._target_obj: fc.DocumentObject | None = None
        self._created_preview_obj = False
        self._preview_applied = False
        self._original_view: dict[str, Any] | None = None
        self._params = CombinedDrawerBaseplateParams()

        self.form = QWidget()
        self.form.setWindowTitle(
            "Edit Drawer Fit Baseplates"
            if target_obj is not None
            else "Create Drawer Fit Baseplates",
        )

        layout = QVBoxLayout(self.form)

        # Build UI using the param system
        controls, _ = self._params.build_ui(layout)
        for key, widget in controls.items():
            setattr(self, key, widget)

        self._target_obj = utils.new_object("DrawerBaseplates")
        self._created_preview_obj = True
        if fc.GuiUp:
            view_object: fcg.ViewProviderDocumentObject = self._target_obj.ViewObject
            ViewProviderGridfinity(view_object, str(self._pixmap))
            if hasattr(view_object, "ShowInTree"):
                with contextlib.suppress(Exception):
                    view_object.ShowInTree = False
        features.DrawerBaseplate(self._target_obj)

        if self._edit_obj is not None:
            self._params = self._params.from_obj(self._edit_obj)
            self._params.to_obj(self._target_obj)

        self._preview_timer = QTimer(self.form)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(500)
        self._preview_timer.timeout.connect(self._update_preview)

        self._params.connect_control_signals(controls, self._on_control_changed)
        self._params.apply_to_ui_owner(self)

        self._capture_and_set_preview_visuals()
        self._update_preview()

    def _preview_style(self) -> tuple[tuple[float, float, float], int]:
        return PREVIEW_SHAPE_COLOR, PREVIEW_TRANSPARENCY

    def _capture_and_set_preview_visuals(self) -> None:
        if not fc.GuiUp or self._target_obj is None:
            return
        view = self._target_obj.ViewObject
        self._original_view = {
            "ShapeColor": tuple(view.ShapeColor),
            "Transparency": int(view.Transparency),
            "LineColor": tuple(view.LineColor) if hasattr(view, "LineColor") else None,
        }
        color, transparency = self._preview_style()
        view.ShapeColor = color
        if hasattr(view, "LineColor"):
            view.LineColor = color
        view.Transparency = transparency

    def _restore_preview_visuals(self) -> None:
        if not fc.GuiUp or self._target_obj is None or self._original_view is None:
            return
        try:
            view = self._target_obj.ViewObject
        except ReferenceError:
            return
        view.ShapeColor = self._original_view["ShapeColor"]
        if hasattr(view, "LineColor") and self._original_view.get("LineColor") is not None:
            view.LineColor = self._original_view["LineColor"]
        view.Transparency = self._original_view["Transparency"]

    @staticmethod
    def _format_drawer_baseplates_label(drawer_width_mm: float, drawer_depth_mm: float) -> str:
        return f"Drawer Baseplates {int(round(drawer_width_mm))} x {int(round(drawer_depth_mm))} mm"

    @staticmethod
    def _format_preview_label(base_label: str) -> str:
        return f"[Preview] {base_label}"

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

    def getStandardButtons(self) -> int:
        return _standard_buttons_ok_cancel()

    def _on_control_changed(self) -> None:
        self._preview_timer.start()

    def _validate_controls(self, *, preview_mode: bool) -> CombinedParams | None:
        self._params.update_from_ui_owner(self)
        if preview_mode:
            self._params.click_springs.set_value("enabled", value=False)
            self._params.junction_screws.set_value("enabled", value=False)
            self._params.connecting_clips.set_value("enabled", value=False)
        errors = self._params.validate()
        if errors:
            return None
        return self._params

    def _apply_dialog_values(self, obj: fc.DocumentObject, *, preview_mode: bool) -> bool:
        params = self._validate_controls(preview_mode=preview_mode)
        if params is None:
            return False
        params.to_obj(obj)

        data = params.data()
        base_label = self._format_drawer_baseplates_label(
            float(data.drawer.drawer_width),
            float(data.drawer.drawer_depth),
        )
        obj.Label = self._format_preview_label(base_label) if preview_mode else base_label
        if hasattr(obj, "PreviewBuildMode"):
            obj.PreviewBuildMode = preview_mode

        return True

    def _update_preview(self) -> None:
        if self._target_obj is None:
            return
        applied = self._apply_dialog_values(self._target_obj, preview_mode=True)
        if not applied:
            return
        status_bar = None
        if fc.GuiUp and fcg is not None:
            try:
                status_bar = fcg.getMainWindow().statusBar()
                status_bar.showMessage("Recomputing preview...")
            except (AttributeError, RuntimeError):
                # GUI may not be fully initialized or main window not available
                status_bar = None

        start = time.perf_counter()
        fc.ActiveDocument.recompute()
        elapsed = time.perf_counter() - start

        if status_bar is not None:
            status_bar.showMessage(f"Preview recomputed in {elapsed:.2f} seconds", 2500)
        self._preview_applied = True

    def accept(self) -> bool:
        if self._target_obj is None:
            return False
        output_obj = self._edit_obj if self._edit_obj is not None else self._target_obj
        applied = self._apply_dialog_values(output_obj, preview_mode=False)
        if not applied:
            return False
        if self._edit_obj is not None and self._created_preview_obj:
            fc.ActiveDocument.removeObject(self._target_obj.Name)
        elif output_obj is self._target_obj:
            self._restore_preview_visuals()
            self._set_show_in_tree(output_obj, visible=True)

        fc.ActiveDocument.recompute()
        fcg.SendMsgToActiveView("ViewFit")
        fcg.Control.closeDialog()
        return True

    def reject(self) -> bool:
        if self._target_obj is not None:
            if self._created_preview_obj:
                fc.ActiveDocument.removeObject(self._target_obj.Name)
            else:
                self._restore_preview_visuals()
        fcg.Control.closeDialog()
        return True


class CreateBaseplateTaskPanel:
    """Task panel for creating a simple baseplate with custom parameters."""

    def __init__(
        self,
        pixmap: Path | str,
        target_obj: fc.DocumentObject | None = None,
        *,
        object_name: str = "Baseplate",
        label_name: str = "Baseplate",
        feature_ctor: type[features.FoundationGridfinity] = features.Baseplate,
    ) -> None:
        self._pixmap = pixmap
        self._edit_obj = target_obj
        self._object_name = object_name
        self._label_name = label_name
        self._feature_ctor = feature_ctor
        self._target_obj: fc.DocumentObject | None = None
        self._created_preview_obj = False
        self._original_view: dict[str, Any] | None = None
        self._preview_applied = False

        # Initialize params - subclasses can set _params before calling super().__init__()
        if not hasattr(self, "_params"):
            self._params = CombinedBaseplateParams()

        self.form = QWidget()
        self.form.setWindowTitle(
            f"Edit {self._label_name}" if target_obj is not None else f"Create {self._label_name}",
        )
        layout = QVBoxLayout(self.form)

        # Build UI using the param system (also creates error labels)
        controls, widget = self._params.build_ui(layout)
        for key, control in controls.items():
            setattr(self, key, control)

        self._target_obj = utils.new_object(self._object_name)
        self._created_preview_obj = True
        if fc.GuiUp:
            view_object: fcg.ViewProviderDocumentObject = self._target_obj.ViewObject
            ViewProviderGridfinity(view_object, str(self._pixmap))
            if hasattr(view_object, "ShowInTree"):
                with contextlib.suppress(Exception):
                    view_object.ShowInTree = False
        self._feature_ctor(self._target_obj)

        if self._edit_obj is not None:
            # Load values from existing object
            self._params = self._params.from_obj(self._edit_obj)
            self._params.to_obj(self._target_obj)

        self._capture_and_set_preview_visuals()

        if self._target_obj is not None:
            self._params.apply_to_ui_owner(self)

        self._preview_timer = QTimer(self.form)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(500)
        self._preview_timer.timeout.connect(self._update_preview)
        self._params.connect_control_signals(controls, lambda: self._preview_timer.start())
        self._update_preview()

    def getStandardButtons(self) -> int:
        return _standard_buttons_ok_cancel()

    def _validate_controls(self, *, preview_mode: bool) -> CombinedParams | None:  # noqa: ARG002
        self._params.update_from_ui_owner(self)
        errors = self._params.validate()
        self._params.render_errors(errors)
        if errors:
            return None
        return self._params

    def _preview_style(self) -> tuple[tuple[float, float, float], int]:
        return PREVIEW_SHAPE_COLOR, PREVIEW_TRANSPARENCY

    def _capture_and_set_preview_visuals(self) -> None:
        if not fc.GuiUp or self._target_obj is None:
            return
        view = self._target_obj.ViewObject
        self._original_view = {
            "ShapeColor": tuple(view.ShapeColor),
            "Transparency": int(view.Transparency),
            "LineColor": tuple(view.LineColor) if hasattr(view, "LineColor") else None,
        }
        color, transparency = self._preview_style()
        view.ShapeColor = color
        if hasattr(view, "LineColor"):
            view.LineColor = color
        view.Transparency = transparency

    def _restore_preview_visuals(self) -> None:
        if not fc.GuiUp or self._target_obj is None or self._original_view is None:
            return
        view = self._target_obj.ViewObject
        view.ShapeColor = self._original_view["ShapeColor"]
        if hasattr(view, "LineColor") and self._original_view.get("LineColor") is not None:
            view.LineColor = self._original_view["LineColor"]
        view.Transparency = self._original_view["Transparency"]

    def _update_preview(self) -> None:
        if self._target_obj is None:
            return
        params = self._validate_controls(preview_mode=True)
        if params is None:
            return
        params.to_obj(self._target_obj)

        # Get layout for preview
        data = params.data()
        size = data.baseplate_size
        if size.custom_layout_enabled and size.custom_layout:
            layout = size.custom_layout
        else:
            layout = [[True] * size.y_grid_count for _ in range(size.x_grid_count)]

        custom_layout = size.custom_layout if size.custom_layout_enabled else None
        base_label = self._format_simple_baseplate_label(
            int(self.baseplate_size__x_grid_count.value()),
            int(self.baseplate_size__y_grid_count.value()),
            custom_layout,
        )
        self._target_obj.Label = self._format_preview_label(base_label)
        status_bar = None
        if fc.GuiUp and fcg is not None:
            try:
                status_bar = fcg.getMainWindow().statusBar()
                status_bar.showMessage("Building preview...")
            except (AttributeError, RuntimeError):
                # GUI may not be fully initialized or main window not available
                status_bar = None

        start = time.perf_counter()
        options = baseplate_builder.BaseplateBuildOptions(
            include_junction_screws=data.junction_screws.enabled,
            include_clip_cutouts=data.connecting_clips.enabled,
            include_snap_springs=data.click_springs.enabled,
        )
        shape = baseplate_builder.build_simple_baseplate_from_params(
            data,
            layout,
            options,
            preview=True,
        )
        self._target_obj.Shape = shape
        elapsed = time.perf_counter() - start

        if status_bar is not None:
            status_bar.showMessage(f"Preview built in {elapsed:.2f} seconds", 2500)
        self._preview_applied = True

    @staticmethod
    def _format_simple_baseplate_label(
        x_cells: int,
        y_cells: int,
        custom_layout: list[list[bool]] | None = None,
    ) -> str:
        if custom_layout:
            cell_count = sum(sum(row) for row in custom_layout)
            return f"Baseplate Custom {cell_count}"
        return f"Baseplate {x_cells} x {y_cells}"

    @staticmethod
    def _format_preview_label(base_label: str) -> str:
        return f"[Preview] {base_label}"

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

    def _stop_preview_timer(self) -> None:
        """Stop the preview timer to prevent callbacks after cleanup."""
        if hasattr(self, "_preview_timer") and self._preview_timer is not None:
            self._preview_timer.stop()

    def accept(self) -> bool:
        self._stop_preview_timer()
        if self._target_obj is None:
            return False
        params = self._validate_controls(preview_mode=False)
        if params is None:
            return False
        output_obj = self._edit_obj if self._edit_obj is not None else self._target_obj
        params.to_obj(output_obj)
        custom_layout_enabled = params.baseplate_size.get_value("custom_layout_enabled")
        custom_layout = (
            params.baseplate_size.get_value("custom_layout") if custom_layout_enabled else None
        )
        output_obj.Label = self._format_simple_baseplate_label(
            int(params.baseplate_size.get_value("x_grid_count")),
            int(params.baseplate_size.get_value("y_grid_count")),
            custom_layout,
        )
        if self._edit_obj is not None and self._created_preview_obj:
            fc.ActiveDocument.removeObject(self._target_obj.Name)
        else:
            self._restore_preview_visuals()
            self._set_show_in_tree(output_obj, visible=True)

        fc.ActiveDocument.recompute()
        fcg.SendMsgToActiveView("ViewFit")
        fcg.Control.closeDialog()
        return True

    def reject(self) -> bool:
        self._stop_preview_timer()
        if self._target_obj is not None:
            if self._created_preview_obj:
                fc.ActiveDocument.removeObject(self._target_obj.Name)
            else:
                self._restore_preview_visuals()
        fcg.Control.closeDialog()
        return True


class CreateStackedBaseplatesTaskPanel(CreateBaseplateTaskPanel):
    def __init__(self, pixmap: Path | str, target_obj: fc.DocumentObject | None = None) -> None:
        from .param import CombinedStackedBaseplatesParams

        # Set params before super().__init__() so base class uses correct type
        self._params = CombinedStackedBaseplatesParams()
        super().__init__(
            pixmap,
            target_obj,
            object_name="StackedBaseplates",
            label_name="Stacked Baseplates",
            feature_ctor=features.StackedBaseplates,
        )

    @staticmethod
    def _format_simple_baseplate_label(
        x_cells: int,
        y_cells: int,
        custom_layout: list[list[bool]] | None = None,  # noqa: ARG004
    ) -> str:
        return f"Stacked Baseplates {x_cells} x {y_cells}"

    @staticmethod
    def _support_label_for(base_label: str) -> str:
        return f"{base_label} Support"

    @staticmethod
    def _find_support_companions(base_obj: fc.DocumentObject) -> list[fc.DocumentObject]:
        doc = fc.ActiveDocument
        if doc is None:
            return []
        companions: list[fc.DocumentObject] = []
        for obj in doc.Objects:
            proxy = getattr(obj, "Proxy", None)
            if not isinstance(proxy, features.StackedBaseplatesSupport):
                continue
            if getattr(obj, "SourceStackedBaseplates", None) is base_obj:
                companions.append(obj)
        return companions

    def _resolve_or_create_support_companion(
        self,
        base_obj: fc.DocumentObject,
    ) -> tuple[fc.DocumentObject, list[fc.DocumentObject]]:
        companions = self._find_support_companions(base_obj)
        if companions:
            canonical = companions[0]
            extras = companions[1:]
            return canonical, extras

        companion = utils.new_object("StackedBaseplatesSupport")
        if fc.GuiUp:
            view_object: fcg.ViewProviderDocumentObject = companion.ViewObject
            ViewProviderGridfinity(view_object, str(self._pixmap))
        features.StackedBaseplatesSupport(companion, base_obj)
        return companion, []

    def accept(self) -> bool:
        if self._target_obj is None:
            return False
        params = self._validate_controls(preview_mode=False)
        if params is None:
            return False

        base_obj = self._edit_obj if self._edit_obj is not None else self._target_obj
        companion, extra_companions = self._resolve_or_create_support_companion(base_obj)

        params.to_obj(base_obj)

        data = params.data()
        base_label = self._format_simple_baseplate_label(
            int(data.baseplate_size.x_grid_count),
            int(data.baseplate_size.y_grid_count),
        )
        base_obj.Label = base_label

        companion.Label = self._support_label_for(base_label)
        companion.SourceStackedBaseplates = base_obj
        for extra in extra_companions:
            extra.SourceStackedBaseplates = None

        if self._edit_obj is not None and self._created_preview_obj:
            fc.ActiveDocument.removeObject(self._target_obj.Name)
        else:
            self._restore_preview_visuals()
            self._set_show_in_tree(base_obj, visible=True)

        self._set_show_in_tree(companion, visible=True)
        fc.ActiveDocument.recompute()
        fcg.SendMsgToActiveView("ViewFit")
        fcg.Control.closeDialog()
        return True


class CreateSupportBaseplate(CreateCommand):
    def __init__(self) -> None:
        super().__init__(
            name="SupportBaseplate",
            gridfinity_function=features.SupportBaseplate,
            pixmap=ICONDIR / "support_baseplate.svg",
        )


class CreateStackedBaseplates(CreateCommand):
    def __init__(self) -> None:
        super().__init__(
            name="StackedBaseplates",
            gridfinity_function=features.StackedBaseplates,
            pixmap=ICONDIR / "baseplate-stacked.svg",
        )

    def Activated(self) -> None:
        fcg.Control.showDialog(CreateStackedBaseplatesTaskPanel(self.pixmap))


class CreateConnectingClipTaskPanel:
    """Task panel for creating a connecting clip with custom parameters."""

    def __init__(self, pixmap: Path | str, target_obj: fc.DocumentObject | None = None) -> None:
        from .param import CombinedConnectingClipsParams

        self._pixmap = pixmap
        self._edit_obj = target_obj
        self._target_obj: fc.DocumentObject | None = None
        self._created_preview_obj = False
        self._original_view: dict[str, Any] | None = None
        self._preview_applied = False
        self._params = CombinedConnectingClipsParams()

        self.form = QWidget()
        self.form.setWindowTitle(
            "Edit Connecting Clip" if target_obj is not None else "Create Connecting Clip",
        )
        layout = QVBoxLayout(self.form)

        # Build UI using the param system
        controls, widget = self._params.build_ui(layout)
        for key, control in controls.items():
            setattr(self, key, control)

        # Create preview object
        self._target_obj = utils.new_object("ConnectingClip")
        self._created_preview_obj = True
        if fc.GuiUp:
            view_object: fcg.ViewProviderDocumentObject = self._target_obj.ViewObject
            ViewProviderGridfinity(view_object, str(self._pixmap))
            if hasattr(view_object, "ShowInTree"):
                with contextlib.suppress(Exception):
                    view_object.ShowInTree = False

        features.ConnectingClip(self._target_obj, self._params)

        if self._edit_obj is not None:
            # Load values from existing object into params, then apply to UI
            self._params = self._params.from_obj(self._edit_obj)
            self._params.apply_to_ui_owner(self)

        self._params.connect_control_signals(controls, self._update_preview)

        # Initial preview update
        self._capture_and_set_preview_visuals()
        self._update_preview()

    def getStandardButtons(self) -> int:
        return _standard_buttons_ok_cancel()

    def _update_preview(self) -> None:
        """Update the preview object with current values."""
        if self._target_obj is None:
            return

        # Update params from UI and apply to object
        self._params.update_from_ui_owner(self)
        self._params.to_obj(self._target_obj)

        # Recompute the object to update the shape
        try:
            fc.ActiveDocument.recompute()
            self._preview_applied = True
        except (RuntimeError, ValueError):
            # Preview recompute can fail due to invalid params - safe to ignore
            pass

    def _preview_style(self) -> tuple[tuple[float, float, float], int]:
        return PREVIEW_SHAPE_COLOR, PREVIEW_TRANSPARENCY

    def _capture_and_set_preview_visuals(self) -> None:
        if not fc.GuiUp or self._target_obj is None:
            return
        view = self._target_obj.ViewObject
        self._original_view = {
            "ShapeColor": tuple(view.ShapeColor),
            "Transparency": int(view.Transparency),
            "LineColor": tuple(view.LineColor) if hasattr(view, "LineColor") else None,
        }
        color, transparency = self._preview_style()
        view.ShapeColor = color
        if hasattr(view, "LineColor"):
            view.LineColor = color
        view.Transparency = transparency

    def _restore_preview_visuals(self) -> None:
        if not fc.GuiUp or self._target_obj is None or self._original_view is None:
            return
        view = self._target_obj.ViewObject
        view.ShapeColor = self._original_view["ShapeColor"]
        if hasattr(view, "LineColor") and self._original_view.get("LineColor") is not None:
            view.LineColor = self._original_view["LineColor"]
        view.Transparency = self._original_view["Transparency"]

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

    def accept(self) -> bool:
        """Accept the dialog and create the final object."""
        if self._target_obj is None:
            return False

        # Update params from UI
        self._params.update_from_ui_owner(self)

        # Validate the parameters
        validation_errors = self._params.validate()
        if validation_errors:
            # Display validation errors to user
            error_msg = "Validation errors:\n" + "\n".join(
                [f"- {msg}" for msg in validation_errors.values()],
            )
            try:
                from PySide.QtWidgets import QMessageBox

                QMessageBox.warning(None, "Validation Error", error_msg)
            except (ImportError, RuntimeError):
                # Fallback to console if GUI not available
                fc.Console.PrintWarning(f"{error_msg}\n")
            return False

        # Apply params to output object
        output_obj = self._edit_obj if self._edit_obj is not None else self._target_obj
        self._params.to_obj(output_obj)
        output_obj.Label = "ConnectingClip"

        if self._edit_obj is not None and self._created_preview_obj:
            fc.ActiveDocument.removeObject(self._target_obj.Name)
        else:
            self._restore_preview_visuals()
            self._set_show_in_tree(output_obj, visible=True)

        # Recompute to finalize the shape
        fc.ActiveDocument.recompute()
        fcg.SendMsgToActiveView("ViewFit")
        fcg.Control.closeDialog()
        return True

    def reject(self) -> bool:
        """Reject the dialog and cleanup preview object."""
        if self._target_obj is not None:
            if self._created_preview_obj:
                fc.ActiveDocument.removeObject(self._target_obj.Name)
            else:
                self._restore_preview_visuals()
        fcg.Control.closeDialog()
        return True


class CreateConnectingClip(CreateCommand):
    def __init__(self) -> None:
        super().__init__(
            name="ConnectingClip",
            gridfinity_function=features.ConnectingClip,
            pixmap=ICONDIR / "connecting-clip.svg",
        )

    def Activated(self) -> None:
        fcg.Control.showDialog(CreateConnectingClipTaskPanel(self.pixmap))


class GridfinitySettingsTaskPanel:
    """Task panel for editing persisted Gridfinity defaults using param system."""

    def __init__(self) -> None:
        from .param import (
            BaseplateCoreParams,
            ClickSpringsParams,
            ConnectingClipsParams,
            FundamentalsParams,
            JunctionScrewsParams,
            PluginSettingsParams,
        )

        self.form = QWidget()
        self.form.setWindowTitle("Gridfinity Default Settings")
        layout = QVBoxLayout(self.form)

        # Create param groups and load saved defaults
        self._groups = [
            FundamentalsParams(),
            BaseplateCoreParams(),
            ClickSpringsParams(),
            JunctionScrewsParams(),
            ConnectingClipsParams(),
            PluginSettingsParams(),
        ]

        # Store controls per group for later retrieval
        self._group_controls: dict[str, dict[str, QWidget]] = {}

        for group in self._groups:
            group.load_saved_defaults()
            controls, widget = group.build_ui(None, group.section_title, show_description=True)
            layout.addWidget(widget)
            self._group_controls[group._group_name] = controls  # noqa: SLF001
            # Connect signals to trigger validation and warnings on change
            group.connect_control_signals(controls, self._on_control_changed)

        # Initial validation and warnings display
        self._update_feedback()

    def _on_control_changed(self) -> None:
        """Handle control value changes - update validation and warnings."""
        self._update_feedback()

    def _update_feedback(self) -> None:
        """Validate all groups and display errors/warnings."""
        for group in self._groups:
            controls = self._group_controls.get(group._group_name, {})  # noqa: SLF001
            group.update_from_ui_controls(controls)
            errors = group.validate()
            warnings = group.warn_non_defaults()
            group.render_errors(errors, warnings)

    def getStandardButtons(self) -> int:
        return _standard_buttons_ok_cancel()

    def accept(self) -> bool:
        # Update group values from UI controls, validate, and save
        for group in self._groups:
            controls = self._group_controls.get(group._group_name, {})  # noqa: SLF001
            group.update_from_ui_controls(controls)
            errors = group.validate()
            if errors:
                # Show validation errors in UI
                warnings = group.warn_non_defaults()
                group.render_errors(errors, warnings)
                return False
            group.save_as_defaults()

        # Apply plugin settings (cache sizes)
        for group in self._groups:
            if hasattr(group, "apply_to_system"):
                group.apply_to_system()

        fcg.Control.closeDialog()
        return True

    def reject(self) -> bool:
        fcg.Control.closeDialog()
        return True


class OpenGridfinitySettings(BaseCommand):
    def __init__(self) -> None:
        super().__init__(
            name="OpenGridfinitySettings",
            pixmap=ICONDIR / "settings.svg",
            menu_text="Default settings",
            tooltip="Open default settings task dialog.",
        )

    def Activated(self) -> None:
        fcg.Control.showDialog(GridfinitySettingsTaskPanel())


class DrawCommand(BaseCommand):
    """Base for gridfinity workbench command.

    Used for commands where an object is drawn.

    """

    def __init__(
        self,
        *,
        name: str,
        pixmap: Path,
        menu_text: str,
        tooltip: str,
        gridfinity_functions: OrderedDict[str, Any],
    ) -> None:
        super().__init__(
            name=name,
            pixmap=pixmap,
            menu_text=menu_text,
            tooltip=tooltip,
        )
        self.gridfinity_functions = gridfinity_functions

    def Activated(self) -> None:
        dialog_data = custom_shape.custom_bin_dialog(list(self.gridfinity_functions.keys()), None)
        if dialog_data is None:
            return
        assert dialog_data.bin_type is not None
        assert dialog_data.bin_type in self.gridfinity_functions

        obj = utils.new_object(self.name)
        if fc.GuiUp:
            view_object: fcg.ViewProviderDocumentObject = obj.ViewObject
            ViewProviderGridfinity(view_object, str(self.pixmap))

        self.gridfinity_functions[dialog_data.bin_type](obj, dialog_data.layout)

        fc.ActiveDocument.recompute()
        fcg.SendMsgToActiveView("ViewFit")


class DrawBin(DrawCommand):
    def __init__(self) -> None:
        super().__init__(
            name="CustomBin",
            pixmap=ICONDIR / "CustomBin.svg",
            menu_text="Custom Bin",
            tooltip="Draw a custom bin of any type.",
            gridfinity_functions=OrderedDict(
                [
                    ("Blank Bin", features.CustomBlankBin),
                    ("Bin Base", features.CustomBinBase),
                    ("Storage Bin", features.CustomStorageBin),
                    ("Eco Bin", features.CustomEcoBin),
                ],
            ),
        )


class ChangeLayout(BaseCommand):
    def __init__(self) -> None:
        super().__init__(
            name="ChangeLayout",
            pixmap=ICONDIR / "ChangeLayout.svg",
            menu_text="Change layout",
            tooltip=("Change the layout of an existing custom shape."),
        )

    def IsActive(self) -> bool:
        selection = fcg.Selection.getSelection()
        return len(selection) == 1 and hasattr(selection[0].Proxy, "layout")

    def Activated(self) -> None:
        obj = fcg.Selection.getSelection()[0]

        dialog_data = custom_shape.custom_bin_dialog([], obj.Proxy.layout)
        if dialog_data is None:
            return
        assert dialog_data.bin_type is None

        obj.Proxy.layout = dialog_data.layout
        obj.recompute()


class StandaloneLabelShelf(BaseCommand):
    def __init__(self) -> None:
        super().__init__(
            name="StandaloneLabelShelf",
            pixmap=ICONDIR / "PlaceLabelShelf.svg",
            menu_text="Standalone label shelf",
            tooltip=(
                "Create a standalone label shelf.<br><br>"
                "Select any bin face and run this command to create a label shelf"
                "attached to selected face."
            ),
        )

    def IsActive(self) -> bool:
        selection = fcg.Selection.getSelectionEx()
        if len(selection) != 1 or len(selection[0].SubObjects) != 1:
            return False
        obj = selection[0].Object
        if not hasattr(obj, "Baseplate") or obj.Baseplate:
            return False
        face = selection[0].SubObjects[0]
        if not hasattr(face, "ShapeType") or face.ShapeType != "Face":
            return False
        if face.findPlane() is None:
            return False
        points = [v.Point for v in face.Vertexes]
        height = max([p.z for p in points])
        max_points = [p for p in points if p.z > height - 1e-4]
        return len(max_points) == 2  # noqa: PLR2004

    def Activated(self) -> None:
        obj = utils.new_object("LabelShelf")
        if fc.GuiUp:
            view_object: fcg.ViewProviderDocumentObject = obj.ViewObject
            ViewProviderGridfinity(view_object, str(ICONDIR / "BinBlank.svg"))

        selection = fcg.Selection.getSelectionEx()
        target_obj: fc.DocumentObject = selection[0].Object
        face: Part.Face = selection[0].SubObjects[0]

        features.StandaloneLabelShelf(obj, target_obj, face)

        fc.ActiveDocument.recompute()
