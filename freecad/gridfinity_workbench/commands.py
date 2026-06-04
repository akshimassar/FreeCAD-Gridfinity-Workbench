"""Gridfinity workbench commands module.

Contains command objects representing what should happen on a button press.
"""

# ruff: noqa: D101, D102, D107, N802
from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import FreeCAD as fc  # noqa: N813
import FreeCADGui as fcg  # noqa: N813
import Part
from PySide.QtCore import Qt
from PySide.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from . import baseplate_builder, clip_profiles, custom_shape, features, utils
from .features import format_axis_with_filler
from .param import CombinedBaseplateParams
from .param_system import DefaultType
from .task_panels import GroupFeatureTaskPanel, SingleFeatureTaskPanel


def _standard_buttons_ok_cancel() -> int:
    """Return Ok|Cancel button flags compatible with both PySide2 and PySide6."""
    ok = QDialogButtonBox.Ok
    cancel = QDialogButtonBox.Cancel
    # PySide6 enums have .value, PySide2 enums are already int-like
    if hasattr(ok, "value"):
        return ok.value | cancel.value
    return int(ok) | int(cancel)


if TYPE_CHECKING:
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
        if isinstance(proxy, features.DrawerBaseplateGroup):
            fcg.Control.showDialog(CreateDrawerBaseplateTaskPanel(self.icon_path, target_obj=obj))
            return True
        if isinstance(proxy, features.BaseplateSupport):
            source = getattr(obj, "SourceBaseplate", None)
            if source is None:
                return False
            fcg.Control.showDialog(
                CreateBaseplateTaskPanel(self.icon_path, target_obj=source),
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


class CreateDrawerBaseplateTaskPanel(GroupFeatureTaskPanel):
    """Task panel for planning drawer baseplate splits.

    Uses a separate preview object to display combined preview shapes without
    creating actual children. On accept, children are created as independent
    Baseplate objects.
    """

    def __init__(
        self,
        pixmap: Path | str,
        target_obj: fc.DocumentObject | None = None,
    ) -> None:
        from .param import CombinedDrawerBaseplateParams

        super().__init__(pixmap, target_obj, window_title="Drawer Fit Baseplates")

        self._params = CombinedDrawerBaseplateParams()

        if target_obj is not None:
            self._params = self._params.from_obj(target_obj)

        self._setup_group_object(
            self._params,
            group_name="DrawerBaseplates",
            group_feature_class=features.DrawerBaseplateGroup,
            view_provider_class=ViewProviderGridfinity,
        )

        controls = self._setup_ui(self._params)
        self._params.apply_to_ui_owner(self)
        self._setup_preview(self._params, controls)

    def _get_params(self) -> CombinedParams:
        return self._params

    def _build_preview_shape(self, params: CombinedParams) -> Part.Shape:
        if self._target_obj is None:
            return Part.Shape()

        # Apply params to group for preview calculation
        params.to_obj(self._target_obj)
        if hasattr(self._target_obj, "PreviewBuildMode"):
            self._target_obj.PreviewBuildMode = True

        proxy = getattr(self._target_obj, "Proxy", None)
        if proxy is not None and hasattr(proxy, "build_preview_shape"):
            return proxy.build_preview_shape(self._target_obj)
        return Part.Shape()

    def _format_label(self, params: CombinedParams) -> str:
        data = params.data()
        drawer_width = float(data.drawer.drawer_width)
        drawer_depth = float(data.drawer.drawer_depth)
        return f"Drawer Baseplates {int(round(drawer_width))} x {int(round(drawer_depth))} mm"

    def _create_feature_object(self) -> fc.DocumentObject:
        # Not used for groups - group is created in _setup_group_object
        raise NotImplementedError("Groups are created in __init__, not on accept")

    def _on_accept_finalize(self, output_obj: fc.DocumentObject, params: CombinedParams) -> None:
        # Group's execute() creates children when PreviewBuildMode is False
        pass


class CreateBaseplateTaskPanel(SingleFeatureTaskPanel):
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
        super().__init__(pixmap, target_obj, window_title=label_name)

        self._object_name = object_name
        self._feature_ctor = feature_ctor
        self._params = CombinedBaseplateParams()

        if target_obj is not None:
            self._params = self._params.from_obj(target_obj)

        controls = self._setup_ui(self._params)
        self._params.apply_to_ui_owner(self)
        self._setup_preview(self._params, controls)

    def _get_params(self) -> CombinedParams:
        return self._params

    def _build_preview_shape(self, params: CombinedParams) -> Part.Shape:
        data = params.data()
        size = data.baseplate_size

        if size.custom_layout_enabled and size.custom_layout:
            layout = size.custom_layout
        else:
            layout = [[True] * size.y_grid_count for _ in range(size.x_grid_count)]

        options = baseplate_builder.BaseplateBuildOptions(
            include_junction_screws=data.junction_screws.enabled,
            include_clip_cutouts=data.connecting_clips.enabled,
            include_snap_springs=data.click_springs.enabled,
        )
        return baseplate_builder.build_simple_baseplate_from_params(
            data, layout, options, preview=True
        )

    def _format_label(self, params: CombinedParams) -> str:
        data = params.data()
        size = data.baseplate_size
        stacking_enabled = data.stacking.enabled

        custom_layout = size.custom_layout if size.custom_layout_enabled else None
        return self._format_baseplate_label(
            size.x_grid_count,
            size.y_grid_count,
            custom_layout,
            stacking_enabled=stacking_enabled,
            filler_left=size.filler_left_enabled,
            filler_right=size.filler_right_enabled,
            filler_bottom=size.filler_bottom_enabled,
            filler_top=size.filler_top_enabled,
        )

    @staticmethod
    def _format_baseplate_label(  # noqa: PLR0913
        x_cells: int,
        y_cells: int,
        custom_layout: list[list[bool]] | None = None,
        *,
        stacking_enabled: bool = False,
        filler_left: bool = False,
        filler_right: bool = False,
        filler_bottom: bool = False,
        filler_top: bool = False,
    ) -> str:
        if custom_layout:
            cell_count = sum(sum(row) for row in custom_layout)
            return f"Baseplate Custom {cell_count}"
        x_str = format_axis_with_filler(x_cells, low_fill=filler_left, high_fill=filler_right)
        y_str = format_axis_with_filler(y_cells, low_fill=filler_bottom, high_fill=filler_top)
        if stacking_enabled:
            return f"Stacked Baseplates {x_str} x {y_str}"
        return f"Baseplate {x_str} x {y_str}"

    def _create_feature_object(self) -> fc.DocumentObject:
        obj = utils.new_object(self._object_name)
        if fc.GuiUp and obj is not None:
            view_object = obj.ViewObject
            if view_object is not None:
                ViewProviderGridfinity(view_object, str(self._pixmap))
        self._feature_ctor(obj)
        return obj

    def _on_accept_finalize(self, output_obj: fc.DocumentObject, params: CombinedParams) -> None:
        params.update_defaults(DefaultType.MEM)

        # Handle support companion for stacking
        data = params.data()
        stacking_enabled = data.stacking.enabled
        base_label = output_obj.Label

        if stacking_enabled:
            companion, extra_companions = self._resolve_or_create_support_companion(output_obj)
            companion.Label = f"{base_label} Support"
            companion.SourceBaseplate = output_obj
            for extra in extra_companions:
                extra.SourceBaseplate = None
            self._set_show_in_tree(companion, visible=True)
        else:
            self._remove_support_companions(output_obj)

    @staticmethod
    def _find_support_companions(base_obj: fc.DocumentObject) -> list[fc.DocumentObject]:
        doc = fc.ActiveDocument
        if doc is None:
            return []
        companions: list[fc.DocumentObject] = []
        for obj in doc.Objects:
            proxy = getattr(obj, "Proxy", None)
            if not isinstance(proxy, features.BaseplateSupport):
                continue
            if getattr(obj, "SourceBaseplate", None) is base_obj:
                companions.append(obj)
        return companions

    def _resolve_or_create_support_companion(
        self,
        base_obj: fc.DocumentObject,
    ) -> tuple[fc.DocumentObject, list[fc.DocumentObject]]:
        companions = self._find_support_companions(base_obj)
        if companions:
            return companions[0], companions[1:]

        companion = utils.new_object("BaseplateSupport")
        if fc.GuiUp and companion is not None:
            view_object = companion.ViewObject
            if view_object is not None:
                ViewProviderGridfinity(view_object, str(self._pixmap))
        features.BaseplateSupport(companion, base_obj)
        return companion, []

    def _remove_support_companions(self, base_obj: fc.DocumentObject) -> None:
        companions = self._find_support_companions(base_obj)
        for companion in companions:
            fc.ActiveDocument.removeObject(companion.Name)


class CreateSupportBaseplate(CreateCommand):
    def __init__(self) -> None:
        super().__init__(
            name="SupportBaseplate",
            gridfinity_function=features.SupportBaseplate,
            pixmap=ICONDIR / "support_baseplate.svg",
        )


class CreateConnectingClipTaskPanel(SingleFeatureTaskPanel):
    """Task panel for creating a connecting clip with custom parameters."""

    def __init__(self, pixmap: Path | str, target_obj: fc.DocumentObject | None = None) -> None:
        from .param import CombinedConnectingClipsParams

        super().__init__(pixmap, target_obj, window_title="Connecting Clip")

        self._params = CombinedConnectingClipsParams()

        if target_obj is not None:
            self._params = self._params.from_obj(target_obj)

        controls = self._setup_ui(self._params)
        self._params.apply_to_ui_owner(self)
        self._setup_preview(self._params, controls)

    def _get_params(self) -> CombinedParams:
        return self._params

    def _build_preview_shape(self, params: CombinedParams) -> Part.Shape:
        data = params.data()
        half_width = data.fundamentals.main_half_width
        height = data.fundamentals.main_height
        tolerance = data.connecting_clips.tolerance
        clip_length = data.connecting_clips.clip_length

        wire = clip_profiles.build_clip_profile_wire(half_width, height, tolerance)
        length = clip_length - 2 * tolerance
        return (
            Part.Face(wire)
            .extrude(fc.Vector(float(length), 0, 0))
            .translate(fc.Vector(-float(length) / 2, 0, 0))
        )

    def _format_label(self, params: CombinedParams) -> str:  # noqa: ARG002
        return "ConnectingClip"

    def _create_feature_object(self) -> fc.DocumentObject:
        obj = utils.new_object("ConnectingClip")
        if fc.GuiUp and obj is not None:
            view_object = obj.ViewObject
            if view_object is not None:
                ViewProviderGridfinity(view_object, str(self._pixmap))
        features.ConnectingClip(obj, self._params)
        return obj

    def _on_accept_finalize(
        self,
        output_obj: fc.DocumentObject,  # noqa: ARG002
        params: CombinedParams,
    ) -> None:
        params.update_defaults(DefaultType.MEM)


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
            group.update_defaults(DefaultType.SAVED)

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
