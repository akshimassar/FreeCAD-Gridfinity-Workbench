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
from PySide.QtCore import Qt
from PySide.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
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

        general_label = QLabel("Fundamentals")
        general_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(general_label)

        compatibility_note = QLabel(
            "Changing these values affects Gridfinity compatibility with other objects."
        )
        compatibility_note.setWordWrap(True)
        compatibility_note.setAlignment(Qt.AlignLeft)
        layout.addWidget(compatibility_note)

        general_form = QFormLayout()
        general_form.setContentsMargins(20, 0, 0, 0)
        self.grid_size = QDoubleSpinBox()
        self.grid_size.setDecimals(2)
        self.grid_size.setMinimum(1.0)
        self.grid_size.setMaximum(500.0)
        self.grid_size.setSuffix(" mm")
        self.grid_size.setValue(defaults.grid_size)
        general_form.addRow("Grid Size", self.grid_size)

        self.base_profile_main_half_width = QDoubleSpinBox()
        self.base_profile_main_half_width.setDecimals(2)
        self.base_profile_main_half_width.setMinimum(0.0)
        self.base_profile_main_half_width.setMaximum(100.0)
        self.base_profile_main_half_width.setSuffix(" mm")
        self.base_profile_main_half_width.setValue(defaults.base_profile_main_half_width)
        general_form.addRow("Base profile half width", self.base_profile_main_half_width)

        self.base_profile_main_height = QDoubleSpinBox()
        self.base_profile_main_height.setDecimals(2)
        self.base_profile_main_height.setMinimum(0.0)
        self.base_profile_main_height.setMaximum(100.0)
        self.base_profile_main_height.setSuffix(" mm")
        self.base_profile_main_height.setValue(defaults.base_profile_main_height)
        general_form.addRow("Base profile height", self.base_profile_main_height)

        self.bin_outer_radius = QDoubleSpinBox()
        self.bin_outer_radius.setDecimals(2)
        self.bin_outer_radius.setMinimum(0.0)
        self.bin_outer_radius.setMaximum(100.0)
        self.bin_outer_radius.setSuffix(" mm")
        self.bin_outer_radius.setValue(defaults.bin_outer_radius)
        general_form.addRow("Outer radius", self.bin_outer_radius)
        layout.addLayout(general_form)

        baseplate_label = QLabel("Baseplate")
        baseplate_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(baseplate_label)

        baseplate_form = QFormLayout()
        baseplate_form.setContentsMargins(20, 0, 0, 0)

        self.enable_lower_chamfer = QCheckBox()
        self.enable_lower_chamfer.setChecked(defaults.baseplate_lower_chamfer_enabled)
        baseplate_form.addRow("Enable lower chamfer", self.enable_lower_chamfer)

        self.base_profile_lower_chamfer_size = QDoubleSpinBox()
        self.base_profile_lower_chamfer_size.setDecimals(2)
        self.base_profile_lower_chamfer_size.setMinimum(0.0)
        self.base_profile_lower_chamfer_size.setMaximum(100.0)
        self.base_profile_lower_chamfer_size.setSuffix(" mm")
        self.base_profile_lower_chamfer_size.setValue(defaults.base_profile_lower_chamfer_size)
        baseplate_form.addRow("Lower chamfer size", self.base_profile_lower_chamfer_size)

        self.top_crop = QDoubleSpinBox()
        self.top_crop.setDecimals(2)
        self.top_crop.setMinimum(0.0)
        self.top_crop.setMaximum(100.0)
        self.top_crop.setSuffix(" mm")
        self.top_crop.setValue(defaults.baseplate_top_crop)
        baseplate_form.addRow("Top crop", self.top_crop)

        layout.addLayout(baseplate_form)

        click_label = QLabel("Snap springs")
        click_label.setStyleSheet("font-weight: bold; padding-left: 20px;")
        layout.addWidget(click_label)

        click_form = QFormLayout()
        click_form.setContentsMargins(40, 0, 0, 0)
        self.click_springs_enabled = QCheckBox()
        self.click_springs_enabled.setChecked(defaults.click_springs_enabled)
        click_form.addRow("Enabled", self.click_springs_enabled)

        self.click_thickness = QDoubleSpinBox()
        self.click_thickness.setDecimals(2)
        self.click_thickness.setMinimum(0.0)
        self.click_thickness.setMaximum(100.0)
        self.click_thickness.setSuffix(" mm")
        self.click_thickness.setValue(defaults.click_thickness)
        click_form.addRow("Thickness", self.click_thickness)

        self.click_length = QDoubleSpinBox()
        self.click_length.setDecimals(2)
        self.click_length.setMinimum(0.0)
        self.click_length.setMaximum(1000.0)
        self.click_length.setSuffix(" mm")
        self.click_length.setValue(defaults.click_length)
        click_form.addRow("Length", self.click_length)

        self.click_offset = QDoubleSpinBox()
        self.click_offset.setDecimals(2)
        self.click_offset.setMinimum(0.0)
        self.click_offset.setMaximum(100.0)
        self.click_offset.setSuffix(" mm")
        self.click_offset.setValue(defaults.click_offset)
        click_form.addRow("Offset", self.click_offset)
        layout.addLayout(click_form)

        junction_label = QLabel("Junction screws")
        junction_label.setStyleSheet("font-weight: bold; padding-left: 20px;")
        layout.addWidget(junction_label)

        junction_form = QFormLayout()
        junction_form.setContentsMargins(40, 0, 0, 0)
        self.junction_screw_holes = QCheckBox()
        self.junction_screw_holes.setChecked(defaults.junction_screw_holes)
        junction_form.addRow("Enabled", self.junction_screw_holes)

        self.junction_screw_diameter = QDoubleSpinBox()
        self.junction_screw_diameter.setDecimals(2)
        self.junction_screw_diameter.setMinimum(0.0)
        self.junction_screw_diameter.setMaximum(100.0)
        self.junction_screw_diameter.setSuffix(" mm")
        self.junction_screw_diameter.setValue(defaults.junction_screw_diameter)
        junction_form.addRow("Screw diameter", self.junction_screw_diameter)

        self.junction_counterbore_diameter = QDoubleSpinBox()
        self.junction_counterbore_diameter.setDecimals(2)
        self.junction_counterbore_diameter.setMinimum(0.0)
        self.junction_counterbore_diameter.setMaximum(100.0)
        self.junction_counterbore_diameter.setSuffix(" mm")
        self.junction_counterbore_diameter.setValue(defaults.junction_counterbore_diameter)
        junction_form.addRow("Counterbore diameter", self.junction_counterbore_diameter)

        self.junction_counterbore_depth = QDoubleSpinBox()
        self.junction_counterbore_depth.setDecimals(2)
        self.junction_counterbore_depth.setMinimum(0.0)
        self.junction_counterbore_depth.setMaximum(100.0)
        self.junction_counterbore_depth.setSuffix(" mm")
        self.junction_counterbore_depth.setValue(defaults.junction_counterbore_depth)
        junction_form.addRow("Counterbore depth", self.junction_counterbore_depth)
        layout.addLayout(junction_form)

        clip_label = QLabel("Connecting clips")
        clip_label.setStyleSheet("font-weight: bold; padding-left: 20px;")
        layout.addWidget(clip_label)

        clip_form = QFormLayout()
        clip_form.setContentsMargins(40, 0, 0, 0)

        self.clip_cutouts_enabled = QCheckBox()
        self.clip_cutouts_enabled.setChecked(defaults.clip_cutouts_enabled)
        clip_form.addRow("Enabled", self.clip_cutouts_enabled)

        self.clip_length = QDoubleSpinBox()
        self.clip_length.setDecimals(2)
        self.clip_length.setMinimum(0.0)
        self.clip_length.setMaximum(100.0)
        self.clip_length.setSuffix(" mm")
        self.clip_length.setValue(defaults.clip_length)
        clip_form.addRow("Clip length", self.clip_length)

        layout.addLayout(clip_form)

        bin_label = QLabel("Bin")
        bin_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(bin_label)

        bin_form = QFormLayout()
        bin_form.setContentsMargins(20, 0, 0, 0)
        self.clearance = QDoubleSpinBox()
        self.clearance.setDecimals(2)
        self.clearance.setMinimum(0.0)
        self.clearance.setMaximum(100.0)
        self.clearance.setSuffix(" mm")
        self.clearance.setValue(defaults.clearance)
        bin_form.addRow("Clearance", self.clearance)

        self.half_grid_size = QCheckBox()
        self.half_grid_size.setChecked(defaults.half_grid_size)
        bin_form.addRow("Half Grid Size", self.half_grid_size)

        layout.addLayout(bin_form)

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
