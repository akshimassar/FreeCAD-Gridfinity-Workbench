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
    QComboBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import baseplate_builder, custom_shape, features, utils
from .drawer_split import split_axis_into_printable_chunks
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

    from .param import CombinedConnectingClipParams
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


def _build_size_section(layout: QVBoxLayout) -> dict[str, QWidget]:
    from .param import BaseplateSizeParams

    # Create size param group and build its UI
    params = BaseplateSizeParams()
    controls, widget = params.build_ui(None, "Size", show_description=True)

    # Add to layout
    layout.addWidget(widget)

    # Prefix control names to match expected return format
    prefixed_controls = {}
    for param_name, control in controls.items():
        prefixed_controls[f"size__{param_name}"] = control

    return prefixed_controls


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
        ClickSpringParams,
        ConnectingClipParams,
        JunctionScrewParams,
    )

    # Create the core baseplate param group and build its UI
    core_params = BaseplateCoreParams()
    core_controls, core_widget = core_params.build_ui(None, "Baseplate", show_description=True)

    # Add core controls to layout
    layout.addWidget(core_widget)

    # Add to main controls dict
    controls: dict[str, QWidget] = {}
    for param_name, control in core_controls.items():
        controls[f"core__{param_name}"] = control

    # Create and add snap springs section
    click_params = ClickSpringParams()
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
    junction_params = JunctionScrewParams()
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
    clip_params = ConnectingClipParams()
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
        controls[f"connecting_clip__{param_name}"] = control

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


def _build_support_section(layout: QVBoxLayout, *, overhang_angle: float) -> dict[str, QWidget]:
    from .param import ScrewStubParams, SupportParams

    # Create the support params group
    support_params = SupportParams(overhang_angle=overhang_angle * fc.Units.Quantity("1 deg"))
    support_controls, support_widget = support_params.build_ui(
        None,
        "Support",
        show_description=True,
    )

    # Add to layout
    layout.addWidget(support_widget)

    # Create screw stub params group
    screw_stub_params = ScrewStubParams()
    screw_stub_controls, screw_stub_widget = screw_stub_params.build_ui(
        None,
        "",
        show_description=True,
    )  # No title for secondary section

    # Add label for screw stubs section
    stub_label = _section_label("Screw stubs")
    layout.addWidget(stub_label)
    layout.addWidget(screw_stub_widget)

    # Combine controls with appropriate naming
    controls = {}
    for param_name, control in support_controls.items():
        controls[f"support__{param_name}"] = control

    for param_name, control in screw_stub_controls.items():
        controls[f"screw_stubs__{param_name}"] = control

    return controls


def _build_stacked_section(
    layout: QVBoxLayout,
    *,
    instance_count: int,
    corner_stitching: bool,
    stitching_thickness: float,
) -> dict[str, QWidget]:
    from .param import StackingParams

    stacking_params = StackingParams(
        instance_count=instance_count,
        corner_stitching=corner_stitching,
        stitching_thickness=fc.Units.Quantity(f"{stitching_thickness} mm"),
    )
    stacking_controls, stacking_widget = stacking_params.build_ui(
        None,
        "Stacked",
        show_description=True,
    )

    layout.addWidget(stacking_widget)

    # Prefix control names with group name for consistent naming
    controls = {}
    for param_name, control in stacking_controls.items():
        controls[f"stacking__{param_name}"] = control

    return controls


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
    """Task panel for planning drawer baseplate splits (no geometry yet)."""

    def __init__(  # noqa: PLR0915
        self,
        pixmap: Path | str,
        target_obj: fc.DocumentObject | None = None,
    ) -> None:
        self._pixmap = pixmap
        self._edit_obj = target_obj
        self._target_obj: fc.DocumentObject | None = None
        self._created_preview_obj = False
        self._preview_applied = False
        self._original_view: dict[str, Any] | None = None
        self.form = QWidget()
        self.form.setWindowTitle(
            "Edit Drawer Fit Baseplates"
            if target_obj is not None
            else "Create Drawer Fit Baseplates",
        )

        layout = QVBoxLayout(self.form)

        layout.addWidget(_section_label("Drawer"))
        drawer_form = QFormLayout()
        drawer_form.setContentsMargins(20, 0, 0, 0)
        self.drawer_width = _mm_spinbox(600.0, minimum=1.0, maximum=5000.0)
        drawer_form.addRow("Drawer width", self.drawer_width)
        self.drawer_depth = _mm_spinbox(600.0, minimum=1.0, maximum=5000.0)
        drawer_form.addRow("Drawer depth", self.drawer_depth)

        self.width_alignment = QComboBox()
        self.width_alignment.addItems(["Left", "Right", "Both"])
        self.width_alignment.setCurrentText("Right")
        drawer_form.addRow("Width filler alignment", self.width_alignment)

        self.depth_alignment = QComboBox()
        self.depth_alignment.addItems(["Bottom", "Top", "Both"])
        self.depth_alignment.setCurrentText("Top")
        drawer_form.addRow("Depth filler alignment", self.depth_alignment)
        self.split_algorithm = QComboBox()
        self.split_algorithm.addItems(["Balanced", "Greedy"])
        self.split_algorithm.setCurrentText("Balanced")
        drawer_form.addRow("Split algorithm", self.split_algorithm)
        layout.addLayout(drawer_form)

        layout.addWidget(_section_label("Printer bed"))
        bed_form = QFormLayout()
        bed_form.setContentsMargins(20, 0, 0, 0)
        self.bed_width = _mm_spinbox(256.0, minimum=1.0, maximum=2000.0)
        bed_form.addRow("Bed width", self.bed_width)
        self.bed_depth = _mm_spinbox(240.0, minimum=1.0, maximum=2000.0)
        bed_form.addRow("Bed depth", self.bed_depth)
        layout.addLayout(bed_form)

        controls: dict[str, QWidget] = {}
        controls.update(_build_fundamentals_section(layout, show_note=False))
        controls.update(
            _build_baseplate_section(layout),
        )
        for key, widget in controls.items():
            setattr(self, key, widget)

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        layout.addWidget(_section_label("Drawer fit plan"))
        layout.addWidget(self.summary)

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
            self._restore_object_values(
                self._target_obj,
                self._capture_object_values(self._edit_obj),
            )

        self._preview_timer = QTimer(self.form)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(500)
        self._preview_timer.timeout.connect(self._update_preview)

        self._connect_signals()
        if self._target_obj is not None:
            self._load_from_object(self._target_obj)

        self._capture_and_set_preview_visuals()

        self._refresh_summary()
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

    def _capture_object_values(self, obj: fc.DocumentObject) -> dict[str, Any]:
        return {
            "DrawerWidth": obj.DrawerWidth,
            "DrawerDepth": obj.DrawerDepth,
            "WidthFillerAlignment": str(obj.WidthFillerAlignment),
            "DepthFillerAlignment": str(obj.DepthFillerAlignment),
            "SplitAlgorithm": str(getattr(obj, "SplitAlgorithm", "Balanced")),
            "PrinterBedWidth": obj.PrinterBedWidth,
            "PrinterBedDepth": obj.PrinterBedDepth,
            "BaseplateParams": CombinedBaseplateParams().from_obj(obj),
            "PreviewBuildMode": bool(getattr(obj, "PreviewBuildMode", False)),
        }

    def _restore_object_values(self, obj: fc.DocumentObject, values: dict[str, Any]) -> None:
        baseplate_params = values.get("BaseplateParams")
        if baseplate_params is not None:
            baseplate_params.to_obj(obj)
        for key, value in values.items():
            if key == "BaseplateParams":
                continue
            if hasattr(obj, key):
                setattr(obj, key, value)

    def _load_from_object(self, obj: fc.DocumentObject) -> None:
        if hasattr(obj, "DrawerWidth"):
            self.drawer_width.setValue(float(obj.DrawerWidth))
        if hasattr(obj, "DrawerDepth"):
            self.drawer_depth.setValue(float(obj.DrawerDepth))
        if hasattr(obj, "WidthFillerAlignment"):
            self.width_alignment.setCurrentText(str(obj.WidthFillerAlignment))
        if hasattr(obj, "DepthFillerAlignment"):
            self.depth_alignment.setCurrentText(str(obj.DepthFillerAlignment))
        if hasattr(obj, "SplitAlgorithm"):
            self.split_algorithm.setCurrentText(str(obj.SplitAlgorithm))
        if hasattr(obj, "PrinterBedWidth"):
            self.bed_width.setValue(float(obj.PrinterBedWidth))
        if hasattr(obj, "PrinterBedDepth"):
            self.bed_depth.setValue(float(obj.PrinterBedDepth))

        params = CombinedBaseplateParams().from_obj(obj)
        params.apply_to_ui_owner(self)

    def getStandardButtons(self) -> int:
        return _standard_buttons_ok_cancel()

    def _set_validation_visuals(self, errors: dict[str, str]) -> None:
        mapping = {
            "top_crop": self.core__top_crop,
            "click_thickness": self.click_springs__click_thickness,
            "click_length": self.click_springs__click_length,
            "junction_screw_diameter": self.junction_screws__screw_diameter,
            "junction_counterbore_diameter": self.junction_screws__counterbore_diameter,
            "junction_counterbore_depth": self.junction_screws__counterbore_depth,
            **(
                {"screw_stub_clearance": self.screw_stubs__clearance}
                if hasattr(self, "screw_stubs__clearance")
                else {}
            ),
            "clip_length": self.connecting_clip__clip_length,
        }
        for key, widget in mapping.items():
            if key in errors:
                widget.setStyleSheet("border: 1px solid #cc3d3d;")
            else:
                widget.setStyleSheet("")

    def _format_axis(
        self,
        *,
        chunks: list[Any],
    ) -> str:
        encoded_chunks: list[str] = []
        for chunk in chunks:
            encoded = f"{chunk.cells}G"
            if chunk.low_fill_mm > 0:
                encoded = f"F+{encoded}"
            if chunk.high_fill_mm > 0:
                encoded = f"{encoded}+F"
            encoded_chunks.append(encoded)
        return ", ".join(encoded_chunks)

    def _refresh_summary(self) -> None:
        validation = self._baseplate_params_from_ui(preview_mode=False)
        errors = validation.validate()
        self._set_validation_visuals(errors)
        if errors:
            msg = "\n".join(f"{k}: {v}" for k, v in sorted(errors.items()))
            self.summary.setText(f"Validation errors:\n{msg}")
            return
        try:
            grid_mm = float(self.fundamentals__grid_size.value())
            drawer_w = float(self.drawer_width.value())
            drawer_d = float(self.drawer_depth.value())
            bed_w = float(self.bed_width.value())
            bed_d = float(self.bed_depth.value())
            if drawer_w <= 0 or drawer_d <= 0:
                self.summary.setText("Drawer dimensions must be > 0")
                return
            if bed_w <= 0 or bed_d <= 0:
                self.summary.setText("Bed dimensions must be > 0")
                return
            x_chunks = split_axis_into_printable_chunks(
                length_mm=float(self.drawer_width.value()),
                bed_mm=float(self.bed_width.value()),
                grid_mm=grid_mm,
                alignment=(
                    "low"
                    if self.width_alignment.currentText() == "Left"
                    else ("high" if self.width_alignment.currentText() == "Right" else "both")
                ),
                algorithm=(
                    "greedy" if self.split_algorithm.currentText() == "Greedy" else "balanced"
                ),
            )
            y_chunks = split_axis_into_printable_chunks(
                length_mm=float(self.drawer_depth.value()),
                bed_mm=float(self.bed_depth.value()),
                grid_mm=grid_mm,
                alignment=(
                    "low"
                    if self.depth_alignment.currentText() == "Bottom"
                    else ("high" if self.depth_alignment.currentText() == "Top" else "both")
                ),
                algorithm=(
                    "greedy" if self.split_algorithm.currentText() == "Greedy" else "balanced"
                ),
            )
        except ValueError as exc:
            self.summary.setText(f"Error: {exc}")
            return

        x_desc = self._format_axis(chunks=x_chunks)
        y_desc = self._format_axis(chunks=y_chunks)
        pieces = len(x_chunks) * len(y_chunks)
        self.summary.setText(
            f"X printable chunks: {len(x_chunks)} [{x_desc}]\n"
            f"Y printable chunks: {len(y_chunks)} [{y_desc}]\n"
            f"Total printable pieces: {pieces}",
        )

    def _connect_signals(self) -> None:
        controls: list[QWidget] = [
            self.drawer_width,
            self.drawer_depth,
            self.bed_width,
            self.bed_depth,
            self.fundamentals__grid_size,
            self.width_alignment,
            self.depth_alignment,
            self.split_algorithm,
        ]
        for control in controls:
            if isinstance(control, QDoubleSpinBox):
                control.valueChanged.connect(lambda *_: self._on_control_changed())
            elif isinstance(control, QComboBox):
                control.currentIndexChanged.connect(lambda *_: self._on_control_changed())

    def _on_control_changed(self) -> None:
        self._refresh_summary()
        self._preview_timer.start()

    def _baseplate_params_from_ui(self, *, preview_mode: bool) -> CombinedBaseplateParams:
        params = CombinedBaseplateParams()
        params.update_from_ui_owner(self)
        if preview_mode:
            params.click_springs.set_value("enabled", value=False)
            params.junction_screws.set_value("enabled", value=False)
            params.connecting_clip.set_value("enabled", value=False)
        return params

    def _apply_dialog_values(self, obj: fc.DocumentObject, *, preview_mode: bool) -> bool:
        self._refresh_summary()
        if self.summary.text().startswith("Error:") or self.summary.text().startswith(
            "Validation errors:",
        ):
            return False

        params = self._baseplate_params_from_ui(preview_mode=preview_mode)
        errors = params.validate()
        if errors:
            return False
        params.to_obj(obj)

        obj.DrawerWidth = float(self.drawer_width.value()) * fc.Units.Quantity("1 mm")
        obj.DrawerDepth = float(self.drawer_depth.value()) * fc.Units.Quantity("1 mm")
        obj.WidthFillerAlignment = self.width_alignment.currentText()
        obj.DepthFillerAlignment = self.depth_alignment.currentText()
        if hasattr(obj, "SplitAlgorithm"):
            obj.SplitAlgorithm = self.split_algorithm.currentText()
        obj.PrinterBedWidth = float(self.bed_width.value()) * fc.Units.Quantity("1 mm")
        obj.PrinterBedDepth = float(self.bed_depth.value()) * fc.Units.Quantity("1 mm")

        base_label = self._format_drawer_baseplates_label(
            float(self.drawer_width.value()),
            float(self.drawer_depth.value()),
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
        self._last_valid_params: CombinedBaseplateParams | None = None
        self._error_labels: dict[str, QLabel] = {}
        self._error_containers: dict[str, QWidget] = {}
        self.form = QWidget()
        self.form.setWindowTitle(
            f"Edit {self._label_name}" if target_obj is not None else f"Create {self._label_name}",
        )
        layout = QVBoxLayout(self.form)
        controls: dict[str, QWidget] = {}
        controls.update(_build_size_section(layout))
        controls.update(self._build_pre_sections(layout))
        controls.update(_build_fundamentals_section(layout, show_note=False))
        controls.update(
            _build_baseplate_section(layout),
        )
        controls.update(self._build_extra_sections(layout))
        for key, widget in controls.items():
            setattr(self, key, widget)

        self._install_inline_error_rows()

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
            CombinedBaseplateParams().from_obj(self._edit_obj).to_obj(self._target_obj)
            self._copy_extended_params_to_preview(self._edit_obj, self._target_obj)

        self._capture_and_set_preview_visuals()

        if self._target_obj is not None:
            self._load_from_object(self._target_obj)

        self._preview_timer = QTimer(self.form)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(500)
        self._preview_timer.timeout.connect(self._update_preview)
        self._connect_preview_signals()
        self._update_preview()

    def _build_extra_sections(self, _layout: QVBoxLayout) -> dict[str, QWidget]:
        return {}

    def _build_pre_sections(self, _layout: QVBoxLayout) -> dict[str, QWidget]:
        return {}

    def _copy_extended_params_to_preview(
        self,
        _source_obj: fc.DocumentObject,
        _preview_obj: fc.DocumentObject,
    ) -> None:
        return

    def getStandardButtons(self) -> int:
        return _standard_buttons_ok_cancel()

    def _load_from_object(self, obj: fc.DocumentObject) -> None:
        params = CombinedBaseplateParams().from_obj(obj)
        params.apply_to_ui_owner(self)

    def _validate_controls(self, *, preview_mode: bool) -> CombinedParams | None:  # noqa: ARG002
        params = CombinedBaseplateParams()
        params.update_from_ui_owner(self)
        errors = dict(params.validate())
        self._render_validation_errors(errors)
        self._last_valid_params = params
        if errors:
            return None
        return params

    def _find_form_layout_for_widget(self, widget: QWidget) -> QFormLayout | None:
        def visit(layout: QLayout) -> QFormLayout | None:
            if isinstance(layout, QFormLayout):
                row, _ = layout.getWidgetPosition(widget)
                if row >= 0:
                    return layout
            for i in range(layout.count()):
                item = layout.itemAt(i)
                child_layout = item.layout()
                if child_layout is None:
                    continue
                found = visit(child_layout)
                if found is not None:
                    return found
            return None

        root = self.form.layout()
        if root is None:
            return None
        return visit(root)

    def _install_inline_error_rows(self) -> None:
        for key, widget in vars(self).items():
            if not isinstance(widget, QWidget):
                continue
            if "__" not in key:
                continue
            layout = self._find_form_layout_for_widget(widget)
            if layout is None:
                continue
            row, _ = layout.getWidgetPosition(widget)
            if row < 0:
                continue
            container = QWidget()
            box = QVBoxLayout(container)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(2)
            box.addWidget(widget)
            label = QLabel("")
            label.setStyleSheet("font-style: italic; font-size: 11px;")
            label.hide()
            box.addWidget(label)
            layout.setWidget(row, QFormLayout.FieldRole, container)
            self._error_labels[key] = label
            self._error_containers[key] = container

    def _render_validation_errors(self, errors: dict[str, str]) -> None:
        normalized_errors = {key.replace(".", "__"): message for key, message in errors.items()}
        for key, label in self._error_labels.items():
            control = getattr(self, key)
            if key in normalized_errors:
                control.setStyleSheet("border: 1px solid #cc3d3d;")
                label.setText(normalized_errors[key])
                label.show()
            else:
                control.setStyleSheet("")
                label.setText("")
                label.hide()

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

    def _connect_preview_signals(self) -> None:
        controls: list[QWidget] = []
        for key, widget in vars(self).items():
            if not isinstance(widget, QWidget):
                continue
            if "__" in key:
                controls.append(widget)
        controls.extend(self._extra_preview_controls())
        for control in controls:
            if isinstance(control, QDoubleSpinBox | QSpinBox):
                control.valueChanged.connect(lambda *_: self._preview_timer.start())
            elif isinstance(control, QPushButton):
                # Layout edit buttons don't trigger preview directly
                pass
            else:
                control.stateChanged.connect(lambda *_: self._preview_timer.start())

    def _extra_preview_controls(self) -> list[QWidget]:
        return []

    def _update_preview(self) -> None:
        if self._target_obj is None:
            return
        params = self._validate_controls(preview_mode=True)
        if params is None:
            return
        params.to_obj(self._target_obj)
        base_label = self._format_simple_baseplate_label(
            int(self.size__x_grid_count.value()),
            int(self.size__y_grid_count.value()),
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
        # Directly build preview shape instead of relying on recompute
        data = params.data()
        layout = [
            [True] * data.baseplate_size.y_grid_count
            for _ in range(data.baseplate_size.x_grid_count)
        ]
        options = baseplate_builder.BaseplateBuildOptions(
            include_junction_screws=data.junction_screws.enabled,
            include_clip_cutouts=data.connecting_clip.enabled,
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
    def _format_simple_baseplate_label(x_cells: int, y_cells: int) -> str:
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

    def accept(self) -> bool:
        if self._target_obj is None:
            return False
        params = self._validate_controls(preview_mode=False)
        if params is None:
            return False
        output_obj = self._edit_obj if self._edit_obj is not None else self._target_obj
        params.to_obj(output_obj)
        output_obj.Label = self._format_simple_baseplate_label(
            int(params.baseplate_size.get_value("x_grid_count")),
            int(params.baseplate_size.get_value("y_grid_count")),
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

        self._params_class = CombinedStackedBaseplatesParams
        super().__init__(
            pixmap,
            target_obj,
            object_name="StackedBaseplates",
            label_name="Stacked Baseplates",
            feature_ctor=features.StackedBaseplates,
        )

    @staticmethod
    def _format_simple_baseplate_label(x_cells: int, y_cells: int) -> str:
        return f"Stacked Baseplates {x_cells} x {y_cells}"

    def _build_extra_sections(self, _layout: QVBoxLayout) -> dict[str, QWidget]:
        return {}

    def _copy_extended_params_to_preview(
        self,
        source_obj: fc.DocumentObject,
        preview_obj: fc.DocumentObject,
    ) -> None:
        from .param import CombinedStackedBaseplatesParams

        CombinedStackedBaseplatesParams().from_obj(source_obj).to_obj(preview_obj)

    def _build_pre_sections(self, layout: QVBoxLayout) -> dict[str, QWidget]:
        controls: dict[str, QWidget] = {}
        controls.update(
            _build_stacked_section(
                layout,
                instance_count=3,
                corner_stitching=False,
                stitching_thickness=0.4,
            ),
        )
        controls.update(_build_support_section(layout, overhang_angle=50.0))
        return controls

    def _extra_preview_controls(self) -> list[QWidget]:
        return [
            self.support__overhang_angle,
            self.stacking__instance_count,
            self.stacking__corner_stitching,
            self.stacking__stitching_thickness,
        ]

    def _load_from_object(self, obj: fc.DocumentObject) -> None:
        from .param import CombinedStackedBaseplatesParams

        params = CombinedStackedBaseplatesParams().from_obj(obj)
        params.apply_to_ui_owner(self)

    def _validate_controls(self, *, preview_mode: bool) -> CombinedParams | None:  # noqa: ARG002
        from .param import CombinedStackedBaseplatesParams

        params = CombinedStackedBaseplatesParams()
        params.update_from_ui_owner(self)
        errors = dict(params.validate())
        self._render_validation_errors(errors)
        self._last_valid_params = params
        if errors:
            return None
        return params

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

        base_label = self._format_simple_baseplate_label(
            int(params.baseplate_size.x_grid_count),
            int(params.baseplate_size.y_grid_count),
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
        self._pixmap = pixmap
        self._edit_obj = target_obj
        self._target_obj: fc.DocumentObject | None = None
        self._created_preview_obj = False
        self._original_view: dict[str, Any] | None = None
        self._preview_applied = False
        self._controls_by_key: dict[str, QWidget] = {}
        self.form = QWidget()
        self.form.setWindowTitle(
            "Edit Connecting Clip" if target_obj is not None else "Create Connecting Clip",
        )
        layout = QVBoxLayout(self.form)

        from .param import CombinedConnectingClipParams

        params = CombinedConnectingClipParams()
        self._controls_by_key = self._build_connecting_clip_controls(layout, params)

        # Create preview object
        self._target_obj = utils.new_object("ConnectingClip")
        self._created_preview_obj = True
        if fc.GuiUp:
            view_object: fcg.ViewProviderDocumentObject = self._target_obj.ViewObject
            ViewProviderGridfinity(view_object, str(self._pixmap))
            if hasattr(view_object, "ShowInTree"):
                with contextlib.suppress(Exception):
                    view_object.ShowInTree = False

        features.ConnectingClip(self._target_obj, params)

        if self._edit_obj is not None:
            # Load values from existing object
            self._load_from_object(self._edit_obj)

        for control in self._controls_by_key.values():
            if hasattr(control, "valueChanged"):
                control.valueChanged.connect(self._update_preview)
            if hasattr(control, "stateChanged"):
                control.stateChanged.connect(self._update_preview)

        # Initial preview update
        self._capture_and_set_preview_visuals()
        self._update_preview()

    def _load_from_object(self, obj: fc.DocumentObject) -> None:
        """Load values from an existing connecting clip object."""
        from .param import CombinedConnectingClipParams

        params = CombinedConnectingClipParams().from_obj(obj)
        params.apply_to_ui_owner(self)

    def _build_connecting_clip_controls(
        self,
        layout: QVBoxLayout,
        params: CombinedConnectingClipParams,
    ) -> dict[str, QWidget]:
        controls: dict[str, QWidget] = {}

        # Use the new param system UI generation for fundamentals
        if hasattr(params, "fundamentals") and hasattr(params.fundamentals, "build_ui"):
            # Add fundamentals section with compatibility note
            layout.addWidget(_section_label("Fundamentals"))
            compatibility_note = QLabel(
                "Changing these values affects Gridfinity compatibility with other objects.",
            )
            compatibility_note.setWordWrap(True)
            compatibility_note.setAlignment(Qt.AlignLeft)
            layout.addWidget(compatibility_note)

            # Generate UI for fundamentals group
            fundamental_controls, fundamental_widget = params.fundamentals.build_ui()
            layout.addWidget(fundamental_widget)

            # Add controls with proper naming
            for param_name, control in fundamental_controls.items():
                key = f"fundamentals__{param_name}"
                controls[key] = control
                setattr(self, key, control)

        # Use the new param system UI generation for clip section
        if hasattr(params, "clip") and hasattr(params.clip, "build_ui"):
            # Add clip section
            clip_controls, clip_widget = params.clip.build_ui(
                None,
                "Connecting Clip",
                show_description=True,
            )
            layout.addWidget(clip_widget)

            # Add controls with proper naming
            for param_name, control in clip_controls.items():
                key = f"clip__{param_name}"
                controls[key] = control
                setattr(self, key, control)

        return controls

    def getStandardButtons(self) -> int:
        return _standard_buttons_ok_cancel()

    def _update_preview(self) -> None:
        """Update the preview object with current values."""
        if self._target_obj is None:
            return

        # Apply values to the preview object using the new param system
        from .param import CombinedConnectingClipParams

        # Create param object using values from controls
        params = CombinedConnectingClipParams()

        params.update_from_ui_owner(self)

        # Apply params to object
        params.to_obj(self._target_obj)

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

        # Apply final values to the target object using the new param system
        from .param import CombinedConnectingClipParams

        # Create param object using values from controls
        params = CombinedConnectingClipParams()

        params.update_from_ui_owner(self)

        # Validate the parameters using the new system
        validation_errors = params.validate()
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

        # Apply params to object using the new system
        params.to_obj(self._target_obj)

        output_obj = self._edit_obj if self._edit_obj is not None else self._target_obj
        # Use a clean name without dimensions
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
            ClickSpringParams,
            ConnectingClipParams,
            FundamentalsParams,
            JunctionScrewParams,
            PluginSettingsParams,
        )

        self.form = QWidget()
        self.form.setWindowTitle("Gridfinity Default Settings")
        layout = QVBoxLayout(self.form)

        # Create param groups and load saved defaults
        self._groups = [
            FundamentalsParams(),
            BaseplateCoreParams(),
            ClickSpringParams(),
            JunctionScrewParams(),
            ConnectingClipParams(),
            PluginSettingsParams(),
        ]

        # Store controls per group for later retrieval
        self._group_controls: dict[str, dict[str, QWidget]] = {}

        for group in self._groups:
            group.load_saved_defaults()
            title = getattr(group, "_section_title", "")
            controls, widget = group.build_ui(None, title, show_description=True)
            layout.addWidget(widget)
            self._group_controls[group._group_name] = controls  # noqa: SLF001

    def getStandardButtons(self) -> int:
        return _standard_buttons_ok_cancel()

    def accept(self) -> bool:
        # Update group values from UI controls, then save
        for group in self._groups:
            controls = self._group_controls.get(group._group_name, {})  # noqa: SLF001
            group.update_from_ui_controls(controls)
            errors = group.validate()
            if errors:
                # NOTE: Could show validation errors in UI dialog
                fc.Console.PrintError(f"Validation errors: {errors}\n")
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
