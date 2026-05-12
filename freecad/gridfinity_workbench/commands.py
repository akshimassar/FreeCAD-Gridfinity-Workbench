"""Gridfinity workbench commands module.

Contains command objects representing what should happen on a button press.
"""

# ruff: noqa: D101, D102, D107, N802

import re
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
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import custom_shape, features, utils
from .settings import defaults, factory_defaults

if TYPE_CHECKING:
    import Part

ICONDIR = Path(__file__).parent / "icons"

PASCAL_CASE_REGEX = re.compile(r"(?<!^)(?=[A-Z])")


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

    def doubleClicked(self, vobj: fcg.ViewProviderDocumentObject) -> bool:
        """Open edit task dialog on double click for simple baseplate."""
        obj = getattr(vobj, "Object", None)
        if obj is None:
            return False
        if not isinstance(getattr(obj, "Proxy", None), features.Baseplate):
            return False
        fcg.Control.showDialog(CreateBaseplateTaskPanel(self.icon_path, target_obj=obj))
        return True


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


def _build_size_section(layout: QVBoxLayout) -> dict[str, QWidget]:
    layout.addWidget(_section_label("Size"))
    form = QFormLayout()
    form.setContentsMargins(20, 0, 0, 0)

    x_grid_units = QSpinBox()
    x_grid_units.setMinimum(1)
    x_grid_units.setMaximum(200)
    x_grid_units.setValue(2)
    form.addRow("X grid units", x_grid_units)

    y_grid_units = QSpinBox()
    y_grid_units.setMinimum(1)
    y_grid_units.setMaximum(200)
    y_grid_units.setValue(2)
    form.addRow("Y grid units", y_grid_units)
    layout.addLayout(form)
    return {"x_grid_units": x_grid_units, "y_grid_units": y_grid_units}


def _build_fundamentals_section(layout: QVBoxLayout, *, show_note: bool) -> dict[str, QWidget]:
    layout.addWidget(_section_label("Fundamentals"))
    if show_note:
        compatibility_note = QLabel(
            "Changing these values affects Gridfinity compatibility with other objects."
        )
        compatibility_note.setWordWrap(True)
        compatibility_note.setAlignment(Qt.AlignLeft)
        layout.addWidget(compatibility_note)

    form = QFormLayout()
    form.setContentsMargins(20, 0, 0, 0)

    grid_size = _mm_spinbox(defaults.grid_size, minimum=1.0, maximum=500.0)
    form.addRow("Grid Size", grid_size)

    base_profile_main_half_width = _mm_spinbox(defaults.base_profile_main_half_width)
    form.addRow("Base profile half width", base_profile_main_half_width)

    base_profile_main_height = _mm_spinbox(defaults.base_profile_main_height)
    form.addRow("Base profile height", base_profile_main_height)

    bin_outer_radius = _mm_spinbox(defaults.bin_outer_radius)
    form.addRow("Outer radius", bin_outer_radius)

    layout.addLayout(form)
    return {
        "grid_size": grid_size,
        "base_profile_main_half_width": base_profile_main_half_width,
        "base_profile_main_height": base_profile_main_height,
        "bin_outer_radius": bin_outer_radius,
    }


def _build_baseplate_section(layout: QVBoxLayout, *, include_clearance: bool) -> dict[str, QWidget]:
    layout.addWidget(_section_label("Baseplate"))
    form = QFormLayout()
    form.setContentsMargins(20, 0, 0, 0)

    enable_lower_chamfer = QCheckBox()
    enable_lower_chamfer.setChecked(defaults.baseplate_lower_chamfer_enabled)
    form.addRow("Enable lower chamfer", enable_lower_chamfer)

    base_profile_lower_chamfer_size = _mm_spinbox(defaults.base_profile_lower_chamfer_size)
    form.addRow("Lower chamfer size", base_profile_lower_chamfer_size)

    top_crop = _mm_spinbox(defaults.baseplate_top_crop)
    form.addRow("Top crop", top_crop)

    controls: dict[str, QWidget] = {
        "enable_lower_chamfer": enable_lower_chamfer,
        "base_profile_lower_chamfer_size": base_profile_lower_chamfer_size,
        "top_crop": top_crop,
    }
    if include_clearance:
        clearance = _mm_spinbox(defaults.clearance)
        form.addRow("Clearance", clearance)
        controls["clearance"] = clearance

    layout.addLayout(form)

    layout.addWidget(_section_label("Snap springs", indent_px=20))
    click_form = QFormLayout()
    click_form.setContentsMargins(40, 0, 0, 0)
    click_springs_enabled = QCheckBox()
    click_springs_enabled.setChecked(defaults.click_springs_enabled)
    click_form.addRow("Enabled", click_springs_enabled)
    click_thickness = _mm_spinbox(defaults.click_thickness)
    click_form.addRow("Thickness", click_thickness)
    click_length = _mm_spinbox(defaults.click_length, maximum=1000.0)
    click_form.addRow("Length", click_length)
    click_offset = _mm_spinbox(defaults.click_offset)
    click_form.addRow("Offset", click_offset)
    layout.addLayout(click_form)
    controls.update(
        {
            "click_springs_enabled": click_springs_enabled,
            "click_thickness": click_thickness,
            "click_length": click_length,
            "click_offset": click_offset,
        }
    )

    layout.addWidget(_section_label("Junction screws", indent_px=20))
    junction_form = QFormLayout()
    junction_form.setContentsMargins(40, 0, 0, 0)
    junction_screw_holes = QCheckBox()
    junction_screw_holes.setChecked(defaults.junction_screw_holes)
    junction_form.addRow("Enabled", junction_screw_holes)
    junction_screw_diameter = _mm_spinbox(defaults.junction_screw_diameter)
    junction_form.addRow("Screw diameter", junction_screw_diameter)
    junction_counterbore_diameter = _mm_spinbox(defaults.junction_counterbore_diameter)
    junction_form.addRow("Counterbore diameter", junction_counterbore_diameter)
    junction_counterbore_depth = _mm_spinbox(defaults.junction_counterbore_depth)
    junction_form.addRow("Counterbore depth", junction_counterbore_depth)
    layout.addLayout(junction_form)
    controls.update(
        {
            "junction_screw_holes": junction_screw_holes,
            "junction_screw_diameter": junction_screw_diameter,
            "junction_counterbore_diameter": junction_counterbore_diameter,
            "junction_counterbore_depth": junction_counterbore_depth,
        }
    )

    layout.addWidget(_section_label("Connecting clips", indent_px=20))
    clip_form = QFormLayout()
    clip_form.setContentsMargins(40, 0, 0, 0)
    clip_cutouts_enabled = QCheckBox()
    clip_cutouts_enabled.setChecked(defaults.clip_cutouts_enabled)
    clip_form.addRow("Enabled", clip_cutouts_enabled)
    clip_length = _mm_spinbox(defaults.clip_length)
    clip_form.addRow("Clip length", clip_length)
    layout.addLayout(clip_form)
    controls.update({"clip_cutouts_enabled": clip_cutouts_enabled, "clip_length": clip_length})
    return controls


def _build_bin_section(layout: QVBoxLayout) -> dict[str, QWidget]:
    layout.addWidget(_section_label("Bin"))
    form = QFormLayout()
    form.setContentsMargins(20, 0, 0, 0)
    clearance = _mm_spinbox(defaults.clearance)
    form.addRow("Clearance", clearance)
    half_grid_size = QCheckBox()
    half_grid_size.setChecked(defaults.half_grid_size)
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
            menu_text=f"Gridfinity {PASCAL_CASE_REGEX.sub(' ', name)}",
            tooltip=f"Create a Gridfinty {PASCAL_CASE_REGEX.sub(' ', name)}.",
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
            pixmap=ICONDIR / "BinBlank.svg",
        )


class CreateBinBase(CreateCommand):
    def __init__(self) -> None:
        super().__init__(
            name="BinBase",
            gridfinity_function=features.BinBase,
            pixmap=ICONDIR / "BinBase.svg",
        )


class CreateSimpleStorageBin(CreateCommand):
    def __init__(self) -> None:
        super().__init__(
            name="SimpleStorageBin",
            gridfinity_function=features.SimpleStorageBin,
            pixmap=ICONDIR / "SimpleStorageBin.svg",
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
            pixmap=ICONDIR / "Baseplate.svg",
        )

    def Activated(self) -> None:
        fcg.Control.showDialog(CreateBaseplateTaskPanel(self.pixmap))


class CreateBaseplateTaskPanel:
    """Task panel for creating a simple baseplate with custom parameters."""

    def __init__(self, pixmap: Path | str, target_obj: fc.DocumentObject | None = None) -> None:
        self._pixmap = pixmap
        self._target_obj = target_obj
        self._created_preview_obj = False
        self._original_values: dict[str, float | bool] | None = None
        self._original_view: dict[str, Any] | None = None
        self._preview_applied = False
        self.form = QWidget()
        self.form.setWindowTitle("Edit Baseplate" if target_obj is not None else "Create Baseplate")
        layout = QVBoxLayout(self.form)
        controls: dict[str, QWidget] = {}
        controls.update(_build_size_section(layout))
        controls.update(_build_fundamentals_section(layout, show_note=False))
        controls.update(_build_baseplate_section(layout, include_clearance=True))
        for key, widget in controls.items():
            setattr(self, key, widget)

        if self._target_obj is None:
            self._target_obj = utils.new_object("Baseplate")
            self._created_preview_obj = True
            if fc.GuiUp:
                view_object: fcg.ViewProviderDocumentObject = self._target_obj.ViewObject
                ViewProviderGridfinity(view_object, str(self._pixmap))
            features.Baseplate(self._target_obj)
        else:
            self._original_values = self._capture_object_values(self._target_obj)

        self._capture_and_set_preview_visuals()

        if self._target_obj is not None:
            self._load_from_object(self._target_obj)

        self._preview_timer = QTimer(self.form)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(500)
        self._preview_timer.timeout.connect(self._update_preview)
        self._connect_preview_signals()
        if self._created_preview_obj:
            self._update_preview()

    def getStandardButtons(self) -> int:  # noqa: N802
        return int(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)

    def _load_from_object(self, obj: fc.DocumentObject) -> None:
        self.x_grid_units.setValue(int(obj.xGridUnits + 1e-6))
        self.y_grid_units.setValue(int(obj.yGridUnits + 1e-6))
        self.grid_size.setValue(obj.xGridSize.Value)
        self.base_profile_main_half_width.setValue(obj.BaseProfileMainHalfWidth.Value)
        self.base_profile_main_height.setValue(obj.BaseProfileMainHeight.Value)
        self.bin_outer_radius.setValue(obj.BinOuterRadius.Value)
        self.enable_lower_chamfer.setChecked(bool(obj.BaseProfileLowerChamferEnabled))
        self.base_profile_lower_chamfer_size.setValue(obj.BaseProfileLowerChamferSize.Value)
        self.top_crop.setValue(obj.BaseProfileTopCrop.Value)
        self.clearance.setValue(obj.Clearance.Value)
        self.click_springs_enabled.setChecked(bool(obj.ClickSpringsEnabled))
        self.click_thickness.setValue(obj.ClickThickness.Value)
        self.click_length.setValue(obj.ClickLength.Value)
        self.click_offset.setValue(obj.ClickOffset.Value)
        self.junction_screw_holes.setChecked(bool(obj.JunctionScrewHoles))
        self.junction_screw_diameter.setValue(obj.JunctionScrewDiameter.Value)
        self.junction_counterbore_diameter.setValue(obj.JunctionCounterboreDiameter.Value)
        self.junction_counterbore_depth.setValue(obj.JunctionCounterboreDepth.Value)
        self.clip_cutouts_enabled.setChecked(bool(obj.ClipCutoutsEnabled))
        self.clip_length.setValue(obj.ClipLength.Value)

    def _capture_object_values(self, obj: fc.DocumentObject) -> dict[str, float | bool]:
        return {
            "xGridUnits": float(obj.xGridUnits),
            "yGridUnits": float(obj.yGridUnits),
            "xGridSize": obj.xGridSize.Value,
            "yGridSize": obj.yGridSize.Value,
            "BaseProfileMainHalfWidth": obj.BaseProfileMainHalfWidth.Value,
            "BaseProfileMainHeight": obj.BaseProfileMainHeight.Value,
            "BinOuterRadius": obj.BinOuterRadius.Value,
            "BaseProfileLowerChamferEnabled": bool(obj.BaseProfileLowerChamferEnabled),
            "BaseProfileLowerChamferSize": obj.BaseProfileLowerChamferSize.Value,
            "BaseProfileTopCrop": obj.BaseProfileTopCrop.Value,
            "Clearance": obj.Clearance.Value,
            "ClickSpringsEnabled": bool(obj.ClickSpringsEnabled),
            "ClickThickness": obj.ClickThickness.Value,
            "ClickLength": obj.ClickLength.Value,
            "ClickOffset": obj.ClickOffset.Value,
            "JunctionScrewHoles": bool(obj.JunctionScrewHoles),
            "JunctionScrewDiameter": obj.JunctionScrewDiameter.Value,
            "JunctionCounterboreDiameter": obj.JunctionCounterboreDiameter.Value,
            "JunctionCounterboreDepth": obj.JunctionCounterboreDepth.Value,
            "ClipCutoutsEnabled": bool(obj.ClipCutoutsEnabled),
            "ClipLength": obj.ClipLength.Value,
        }

    def _restore_object_values(
        self, obj: fc.DocumentObject, values: dict[str, float | bool]
    ) -> None:
        obj.xGridUnits = values["xGridUnits"]
        obj.yGridUnits = values["yGridUnits"]
        obj.xGridSize = values["xGridSize"]
        obj.yGridSize = values["yGridSize"]
        obj.BaseProfileMainHalfWidth = values["BaseProfileMainHalfWidth"]
        obj.BaseProfileMainHeight = values["BaseProfileMainHeight"]
        obj.BinOuterRadius = values["BinOuterRadius"]
        obj.BaseProfileLowerChamferEnabled = values["BaseProfileLowerChamferEnabled"]
        obj.BaseProfileLowerChamferSize = values["BaseProfileLowerChamferSize"]
        obj.BaseProfileTopCrop = values["BaseProfileTopCrop"]
        obj.Clearance = values["Clearance"]
        obj.ClickSpringsEnabled = values["ClickSpringsEnabled"]
        obj.ClickThickness = values["ClickThickness"]
        obj.ClickLength = values["ClickLength"]
        obj.ClickOffset = values["ClickOffset"]
        obj.JunctionScrewHoles = values["JunctionScrewHoles"]
        obj.JunctionScrewDiameter = values["JunctionScrewDiameter"]
        obj.JunctionCounterboreDiameter = values["JunctionCounterboreDiameter"]
        obj.JunctionCounterboreDepth = values["JunctionCounterboreDepth"]
        obj.ClipCutoutsEnabled = values["ClipCutoutsEnabled"]
        obj.ClipLength = values["ClipLength"]

    def _apply_dialog_values(self, obj: fc.DocumentObject, *, preview_mode: bool) -> None:
        obj.xGridUnits = self.x_grid_units.value()
        obj.yGridUnits = self.y_grid_units.value()
        obj.xGridSize = self.grid_size.value()
        obj.yGridSize = self.grid_size.value()
        obj.BaseProfileMainHalfWidth = self.base_profile_main_half_width.value()
        obj.BaseProfileMainHeight = self.base_profile_main_height.value()
        obj.BinOuterRadius = self.bin_outer_radius.value()

        obj.BaseProfileLowerChamferEnabled = self.enable_lower_chamfer.isChecked()
        obj.BaseProfileLowerChamferSize = self.base_profile_lower_chamfer_size.value()
        obj.BaseProfileTopCrop = self.top_crop.value()
        obj.Clearance = self.clearance.value()

        if preview_mode:
            obj.ClickSpringsEnabled = False
            obj.JunctionScrewHoles = False
            obj.ClipCutoutsEnabled = False
        else:
            obj.ClickSpringsEnabled = self.click_springs_enabled.isChecked()
            obj.JunctionScrewHoles = self.junction_screw_holes.isChecked()
            obj.ClipCutoutsEnabled = self.clip_cutouts_enabled.isChecked()

        obj.ClickThickness = self.click_thickness.value()
        obj.ClickLength = self.click_length.value()
        obj.ClickOffset = self.click_offset.value()

        obj.JunctionScrewDiameter = self.junction_screw_diameter.value()
        obj.JunctionCounterboreDiameter = self.junction_counterbore_diameter.value()
        obj.JunctionCounterboreDepth = self.junction_counterbore_depth.value()
        obj.ClipLength = self.clip_length.value()

    def _preview_color(self) -> tuple[float, float, float]:
        """Return FreeCAD standard-ish preview color from preferences, fallback orange."""
        prefs = fc.ParamGet("User parameter:BaseApp/Preferences/View")
        color_uint = prefs.GetUnsigned("DefaultShapeColor", 0xCC9966)
        r = ((color_uint >> 24) & 0xFF) / 255.0
        g = ((color_uint >> 16) & 0xFF) / 255.0
        b = ((color_uint >> 8) & 0xFF) / 255.0
        return (r, g, b)

    def _capture_and_set_preview_visuals(self) -> None:
        if not fc.GuiUp or self._target_obj is None:
            return
        view = self._target_obj.ViewObject
        self._original_view = {
            "ShapeColor": tuple(view.ShapeColor),
            "Transparency": int(view.Transparency),
        }
        view.ShapeColor = self._preview_color()
        view.Transparency = 70

    def _restore_preview_visuals(self) -> None:
        if not fc.GuiUp or self._target_obj is None or self._original_view is None:
            return
        view = self._target_obj.ViewObject
        view.ShapeColor = self._original_view["ShapeColor"]
        view.Transparency = self._original_view["Transparency"]

    def _connect_preview_signals(self) -> None:
        controls = [
            self.x_grid_units,
            self.y_grid_units,
            self.grid_size,
            self.base_profile_main_half_width,
            self.base_profile_main_height,
            self.bin_outer_radius,
            self.enable_lower_chamfer,
            self.base_profile_lower_chamfer_size,
            self.top_crop,
            self.clearance,
            self.click_springs_enabled,
            self.click_thickness,
            self.click_length,
            self.click_offset,
            self.junction_screw_holes,
            self.junction_screw_diameter,
            self.junction_counterbore_diameter,
            self.junction_counterbore_depth,
            self.clip_cutouts_enabled,
            self.clip_length,
        ]
        for control in controls:
            if isinstance(control, (QDoubleSpinBox, QSpinBox)):
                control.valueChanged.connect(lambda *_: self._preview_timer.start())
            else:
                control.stateChanged.connect(lambda *_: self._preview_timer.start())

    def _update_preview(self) -> None:
        if self._target_obj is None:
            return
        self._apply_dialog_values(self._target_obj, preview_mode=True)
        fc.ActiveDocument.recompute()
        self._preview_applied = True

    def accept(self) -> bool:
        if self._target_obj is None:
            return False
        self._apply_dialog_values(self._target_obj, preview_mode=False)
        fc.ActiveDocument.recompute()
        self._restore_preview_visuals()
        fcg.SendMsgToActiveView("ViewFit")
        fcg.Control.closeDialog()
        return True

    def reject(self) -> bool:
        if self._target_obj is not None:
            if self._created_preview_obj:
                fc.ActiveDocument.removeObject(self._target_obj.Name)
            elif self._original_values is not None and self._preview_applied:
                self._restore_object_values(self._target_obj, self._original_values)
                fc.ActiveDocument.recompute()
            self._restore_preview_visuals()
        fcg.Control.closeDialog()
        return True


class CreateSupportBaseplate(CreateCommand):
    def __init__(self) -> None:
        super().__init__(
            name="SupportBaseplate",
            gridfinity_function=features.SupportBaseplate,
            pixmap=ICONDIR / "Baseplate.svg",
        )


class CreateMagnetBaseplate(CreateCommand):
    def __init__(self) -> None:
        super().__init__(
            name="MagnetBaseplate",
            gridfinity_function=features.MagnetBaseplate,
            pixmap=ICONDIR / "magnet_baseplate.svg",
        )


class CreateScrewTogetherBaseplate(CreateCommand):
    def __init__(self) -> None:
        super().__init__(
            name="ScrewTogetherBaseplate",
            gridfinity_function=features.ScrewTogetherBaseplate,
            pixmap=ICONDIR / "screw_together_baseplate.svg",
        )


class CreateConnectingClip(CreateCommand):
    def __init__(self) -> None:
        super().__init__(
            name="ConnectingClip",
            gridfinity_function=features.ConnectingClip,
            pixmap=ICONDIR / "template_resource.svg",
        )


class GridfinitySettingsTaskPanel:
    """Task panel for editing persisted Gridfinity defaults."""

    def __init__(self) -> None:
        self.form = QWidget()
        self.form.setWindowTitle("Gridfinity Default Settings")

        layout = QVBoxLayout(self.form)
        controls: dict[str, QWidget] = {}
        controls.update(_build_fundamentals_section(layout, show_note=True))
        controls.update(_build_baseplate_section(layout, include_clearance=False))
        controls.update(_build_bin_section(layout))
        for key, widget in controls.items():
            setattr(self, key, widget)

        self._wire_default_warning_colors()

    def getStandardButtons(self) -> int:  # noqa: N802
        return int(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)

    def _set_warn_style(self, widget: QWidget, warn: bool) -> None:
        if warn:
            widget.setStyleSheet("border: 1px solid #e6a700;")
        else:
            widget.setStyleSheet("")

    def _wire_default_warning_colors(self) -> None:
        numeric_controls = [
            (self.grid_size, factory_defaults.grid_size),
            (self.base_profile_main_half_width, factory_defaults.base_profile_main_half_width),
            (self.base_profile_main_height, factory_defaults.base_profile_main_height),
            (self.bin_outer_radius, factory_defaults.bin_outer_radius),
            (
                self.base_profile_lower_chamfer_size,
                factory_defaults.base_profile_lower_chamfer_size,
            ),
            (self.top_crop, factory_defaults.baseplate_top_crop),
            (self.click_thickness, factory_defaults.click_thickness),
            (self.click_length, factory_defaults.click_length),
            (self.click_offset, factory_defaults.click_offset),
            (self.junction_screw_diameter, factory_defaults.junction_screw_diameter),
            (self.junction_counterbore_diameter, factory_defaults.junction_counterbore_diameter),
            (self.junction_counterbore_depth, factory_defaults.junction_counterbore_depth),
            (self.clip_length, factory_defaults.clip_length),
            (self.clearance, factory_defaults.clearance),
        ]

        for control, default_value in numeric_controls:

            def updater(
                _value: float, c: QDoubleSpinBox = control, d: float = default_value
            ) -> None:
                self._set_warn_style(c, abs(c.value() - d) > 1e-9)

            control.valueChanged.connect(updater)
            updater(control.value())

        bool_controls = [
            (self.enable_lower_chamfer, factory_defaults.baseplate_lower_chamfer_enabled),
            (self.click_springs_enabled, factory_defaults.click_springs_enabled),
            (self.junction_screw_holes, factory_defaults.junction_screw_holes),
            (self.clip_cutouts_enabled, factory_defaults.clip_cutouts_enabled),
            (self.half_grid_size, factory_defaults.half_grid_size),
        ]

        for control, default_value in bool_controls:

            def updater(_state: int, c: QCheckBox = control, d: bool = default_value) -> None:
                self._set_warn_style(c, c.isChecked() != d)

            control.stateChanged.connect(updater)
            updater(0)

    def accept(self) -> bool:
        defaults.grid_size = self.grid_size.value()
        defaults.base_profile_main_half_width = self.base_profile_main_half_width.value()
        defaults.base_profile_main_height = self.base_profile_main_height.value()
        defaults.base_profile_lower_chamfer_size = self.base_profile_lower_chamfer_size.value()
        defaults.baseplate_lower_chamfer_enabled = self.enable_lower_chamfer.isChecked()
        defaults.baseplate_top_crop = self.top_crop.value()
        defaults.bin_outer_radius = self.bin_outer_radius.value()
        defaults.clearance = self.clearance.value()
        defaults.half_grid_size = self.half_grid_size.isChecked()

        defaults.click_springs_enabled = self.click_springs_enabled.isChecked()
        defaults.click_thickness = self.click_thickness.value()
        defaults.click_length = self.click_length.value()
        defaults.click_offset = self.click_offset.value()

        defaults.junction_screw_holes = self.junction_screw_holes.isChecked()
        defaults.junction_screw_diameter = self.junction_screw_diameter.value()
        defaults.junction_counterbore_diameter = self.junction_counterbore_diameter.value()
        defaults.junction_counterbore_depth = self.junction_counterbore_depth.value()
        defaults.clip_cutouts_enabled = self.clip_cutouts_enabled.isChecked()
        defaults.clip_length = self.clip_length.value()

        defaults.save()
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
            menu_text="Gridfinity default settings",
            tooltip="Open Gridfinity default settings task dialog.",
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
            menu_text="Gridfinity Custom Bin",
            tooltip="Draw a custom gridfinity bin of any type.",
            gridfinity_functions=OrderedDict(
                [
                    ("Blank Bin", features.CustomBlankBin),
                    ("Bin Base", features.CustomBinBase),
                    ("Storage Bin", features.CustomStorageBin),
                    ("Eco Bin", features.CustomEcoBin),
                ],
            ),
        )


class DrawBaseplate(DrawCommand):
    def __init__(self) -> None:
        super().__init__(
            name="CustomBaseplate",
            pixmap=ICONDIR / "CustomBaseplate.svg",
            menu_text="Gridfinity Custom Baseplate",
            tooltip="Draw a custom gridfinity baseplate of any type.",
            gridfinity_functions=OrderedDict(
                [
                    ("Simple Baseplate", features.CustomBaseplate),
                    ("Magnet Baseplate", features.CustomMagnetBaseplate),
                    ("Screw Together Baseplate", features.CustomScrewTogetherBaseplate),
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
                "Select any Gridfinity Bin face and run this command to create a label shelf"
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
