"""Concrete parameter groups and data containers.

This module defines the actual parameter groups used by Gridfinity objects.
Each ParameterGroup subclass sets `_default_type` to control how defaults
are resolved for all parameters in the group:

- DefaultType.VALUE: Hardcoded defaults (most groups use this)
- DefaultType.MEM: Remember last used values within session (BaseplateSizeParams)
- DefaultType.SAVED: Persist to FreeCAD preferences (PluginSettingsParams)
"""

from __future__ import annotations

from dataclasses import dataclass

import FreeCAD as fc  # noqa: N813

from .param_system import (
    BooleanParam,
    CombinedParams,
    DefaultType,
    FloatParam,
    IntParam,
    LiteralParam,
    ParameterGroup,
    ParameterValidationError,
)


@dataclass(frozen=True)
class FundamentalsParamsData:
    """Immutable data container for fundamental Gridfinity dimensions."""

    x_grid_size: fc.Units.Quantity
    y_grid_size: fc.Units.Quantity
    bin_outer_radius: fc.Units.Quantity
    main_half_width: fc.Units.Quantity
    main_height: fc.Units.Quantity


@dataclass(frozen=True)
class ClipParamsData:
    """Immutable data container for clip cutout parameters."""

    enabled: bool
    clip_tolerance: fc.Units.Quantity
    clip_length: fc.Units.Quantity


@dataclass(frozen=True)
class CombinedClipParamsData:
    """Immutable combined data for clip geometry generation."""

    fundamentals: FundamentalsParamsData
    clip: ClipParamsData


@dataclass(frozen=True)
class BaseplateSizeParamsData:
    """Immutable data container for baseplate size (grid counts, fillers)."""

    x_grid_count: int
    y_grid_count: int
    filler_left_enabled: bool
    filler_left_width: fc.Units.Quantity
    filler_right_enabled: bool
    filler_right_width: fc.Units.Quantity
    filler_top_enabled: bool
    filler_top_width: fc.Units.Quantity
    filler_bottom_enabled: bool
    filler_bottom_width: fc.Units.Quantity


@dataclass(frozen=True)
class BaseplateCoreParamsData:
    """Immutable data container for baseplate core profile parameters."""

    base_profile_lower_chamfer_enabled: bool
    base_profile_lower_chamfer_size: fc.Units.Quantity
    base_profile_top_crop: fc.Units.Quantity


@dataclass(frozen=True)
class BaseplateCoreLayoutParamsData:
    """Immutable data container combining core params with grid layout."""

    x_grid_count: int
    y_grid_count: int
    base_profile_lower_chamfer_enabled: bool
    base_profile_lower_chamfer_size: fc.Units.Quantity
    base_profile_top_crop: fc.Units.Quantity


@dataclass(frozen=True)
class BaseplateFillersParamsData:
    """Immutable data container for filler strip parameters."""

    left_enabled: bool
    left_width: fc.Units.Quantity
    right_enabled: bool
    right_width: fc.Units.Quantity
    top_enabled: bool
    top_width: fc.Units.Quantity
    bottom_enabled: bool
    bottom_width: fc.Units.Quantity


@dataclass(frozen=True)
class ClickSpringParamsData:
    """Immutable data container for click/snap spring parameters."""

    enabled: bool
    click_thickness: fc.Units.Quantity
    click_length: fc.Units.Quantity
    click_offset: fc.Units.Quantity


@dataclass(frozen=True)
class JunctionScrewParamsData:
    """Immutable data container for junction screw parameters."""

    enabled: bool
    screw_diameter: fc.Units.Quantity
    counterbore_diameter: fc.Units.Quantity
    counterbore_depth: fc.Units.Quantity


@dataclass(frozen=True)
class ScrewStubParamsData:
    """Immutable data container for screw stub parameters."""

    enabled: bool
    clearance: fc.Units.Quantity


@dataclass(frozen=True)
class SupportParamsData:
    """Immutable data container for overhang support parameters."""

    overhang_angle: fc.Units.Quantity


@dataclass(frozen=True)
class StackingParamsData:
    """Immutable data container for stacking/instancing parameters."""

    instance_count: int
    corner_stitching: bool
    stitching_thickness: fc.Units.Quantity


@dataclass(frozen=True)
class CombinedSupportBaseplateParamsData:
    """Immutable combined data for support baseplate geometry generation."""

    fundamentals: FundamentalsParamsData
    core: BaseplateCoreLayoutParamsData
    fillers: BaseplateFillersParamsData
    click_springs: ClickSpringParamsData
    support: SupportParamsData


@dataclass(frozen=True)
class CombinedBaseplateParamsData:
    """Immutable combined data for baseplate geometry generation."""

    fundamentals: FundamentalsParamsData
    core: BaseplateCoreLayoutParamsData
    fillers: BaseplateFillersParamsData
    click_springs: ClickSpringParamsData
    junction_screws: JunctionScrewParamsData
    screw_stubs: ScrewStubParamsData
    clip_cutouts: ClipParamsData


@dataclass(frozen=True)
class CombinedStackedBaseplatesParamsData:
    """Immutable combined data for stacked baseplates geometry generation."""

    fundamentals: FundamentalsParamsData
    core: BaseplateCoreLayoutParamsData
    fillers: BaseplateFillersParamsData
    click_springs: ClickSpringParamsData
    junction_screws: JunctionScrewParamsData
    screw_stubs: ScrewStubParamsData
    support: SupportParamsData
    stacking: StackingParamsData
    clip_cutouts: ClipParamsData


class FundamentalsParams(ParameterGroup):
    """Fundamental Gridfinity dimensions (grid size, radius, profile)."""

    _category = "Gridfinity_Fundamentals"
    _section_title = "Fundamentals"

    def __init__(self, **kwargs) -> None:
        """Initialize with grid size, outer radius, and profile dimensions."""
        parameters = [
            FloatParam(
                "grid_size",
                "Grid Size",
                fc.Units.Quantity("42 mm"),
                positive_only=True,
            ),
            FloatParam(
                "outer_radius",
                "Outer Radius",
                fc.Units.Quantity("4.0 mm"),
                positive_only=True,
            ),
            FloatParam(
                "main_half_width",
                "Main Profile Half Width",
                fc.Units.Quantity("2.15 mm"),
                positive_only=True,
            ),
            FloatParam(
                "main_height",
                "Main Profile Height",
                fc.Units.Quantity("2.5 mm"),
                positive_only=True,
            ),
        ]

        super().__init__(parameters)
        self.set_all_values(kwargs)

    def data(self) -> FundamentalsParamsData:
        """Return validated immutable data container."""
        errors = self.validate()
        if errors:
            raise ParameterValidationError(errors)
        return FundamentalsParamsData(
            x_grid_size=self.get_value("grid_size"),
            y_grid_size=self.get_value("grid_size"),
            bin_outer_radius=self.get_value("outer_radius"),
            main_half_width=self.get_value("main_half_width"),
            main_height=self.get_value("main_height"),
        )


class ClipParams(ParameterGroup):
    """Parameters for clip cutout features on baseplates."""

    _category = "Gridfinity_Clip"
    _section_title = "Clip Cutouts"

    def __init__(self, **kwargs) -> None:
        """Initialize with clip enabled state, tolerance, and length."""
        parameters = [
            BooleanParam("enabled", "Enabled", default_value=True),
            FloatParam(
                "tolerance",
                "Tolerance",
                fc.Units.Quantity("0.15 mm"),
            ),
            FloatParam(
                "clip_length",
                "Clip Length",
                fc.Units.Quantity("3.0 mm"),
            ),
        ]

        super().__init__(parameters)
        self.set_all_values(kwargs)

    def data(self) -> ClipParamsData:
        """Return validated immutable data container."""
        errors = self.validate()
        if errors:
            raise ParameterValidationError(errors)
        return ClipParamsData(
            enabled=self.get_value("enabled"),
            clip_tolerance=self.get_value("tolerance"),
            clip_length=self.get_value("clip_length"),
        )


class CombinedClipParams(CombinedParams):
    """Combined parameters for clip geometry (fundamentals + clip settings)."""

    def __init__(
        self,
        fundamentals: FundamentalsParams = None,
        clip: ClipParams = None,
    ) -> None:
        """Initialize with fundamentals and clip parameter groups."""
        super().__init__(
            fundamentals=fundamentals or FundamentalsParams(),
            clip=clip or ClipParams(),
        )

    def validate(self) -> dict[str, str]:
        """Validate cross-group constraints."""
        errors = super().validate()
        try:
            tolerance_val = float(self.clip.get_value("tolerance"))
            clip_length_val = float(self.clip.get_value("clip_length"))
            if clip_length_val <= 2 * tolerance_val:
                errors["clip.clip_length"] = (
                    f"Clip length ({clip_length_val}) must be > 2 * tolerance ({2 * tolerance_val})"
                )
        except (AttributeError, KeyError, TypeError, ValueError):
            pass
        return errors

    def data(self) -> CombinedClipParamsData:
        """Return validated immutable combined data container."""
        errors = self.validate()
        if errors:
            raise ParameterValidationError(errors)
        return CombinedClipParamsData(
            fundamentals=self.fundamentals.data(),
            clip=self.clip.data(),
        )


class BaseplateSizeParams(ParameterGroup):
    """Baseplate size parameters (grid counts, filler dimensions).

    Uses MEM default type - values are remembered within the session so
    creating a new baseplate defaults to the last used grid size.
    """

    _category = "Gridfinity_BaseplateSize"
    _section_title = "Size"
    _default_type = DefaultType.MEM

    def __init__(self, **kwargs) -> None:
        """Initialize with grid counts and filler dimensions."""
        parameters = [
            IntParam(
                "x_grid_count",
                "X Grid Count",
                2,
                positive_only=True,
            ),
            IntParam(
                "y_grid_count",
                "Y Grid Count",
                2,
                positive_only=True,
            ),
            BooleanParam("filler_left_enabled", "Left Filler Enabled"),
            FloatParam(
                "filler_left_width",
                "Left Filler Width",
                fc.Units.Quantity("30 mm"),
                positive_only=True,
            ),
            BooleanParam("filler_right_enabled", "Right Filler Enabled"),
            FloatParam(
                "filler_right_width",
                "Right Filler Width",
                fc.Units.Quantity("30 mm"),
                positive_only=True,
            ),
            BooleanParam("filler_top_enabled", "Top Filler Enabled"),
            FloatParam(
                "filler_top_width",
                "Top Filler Width",
                fc.Units.Quantity("30 mm"),
                positive_only=True,
            ),
            BooleanParam("filler_bottom_enabled", "Bottom Filler Enabled"),
            FloatParam(
                "filler_bottom_width",
                "Bottom Filler Width",
                fc.Units.Quantity("30 mm"),
                positive_only=True,
            ),
        ]

        super().__init__(parameters)
        self.set_all_values(kwargs)

    def data(self) -> BaseplateSizeParamsData:
        """Return immutable data container."""
        return BaseplateSizeParamsData(
            x_grid_count=self.get_value("x_grid_count"),
            y_grid_count=self.get_value("y_grid_count"),
            filler_left_enabled=self.get_value("filler_left_enabled"),
            filler_left_width=self.get_value("filler_left_width"),
            filler_right_enabled=self.get_value("filler_right_enabled"),
            filler_right_width=self.get_value("filler_right_width"),
            filler_top_enabled=self.get_value("filler_top_enabled"),
            filler_top_width=self.get_value("filler_top_width"),
            filler_bottom_enabled=self.get_value("filler_bottom_enabled"),
            filler_bottom_width=self.get_value("filler_bottom_width"),
        )


class BaseplateCoreParams(ParameterGroup):
    """Core baseplate profile parameters (chamfer, top crop)."""

    _category = "Gridfinity_Core"
    _section_title = "Baseplate"

    def __init__(self, **kwargs) -> None:
        """Initialize with chamfer and top crop settings."""
        parameters = [
            BooleanParam(
                "lower_chamfer_enabled",
                "Lower Chamfer Enabled",
                default_value=False,
            ),
            FloatParam(
                "lower_chamfer_size",
                "Lower Chamfer Size",
                fc.Units.Quantity("0.7 mm"),
            ),
            FloatParam(
                "top_crop",
                "Top Crop",
                fc.Units.Quantity("0.8 mm"),
            ),
        ]

        super().__init__(parameters)
        self.set_all_values(kwargs)

    def data(self) -> BaseplateCoreParamsData:
        """Return immutable data container."""
        return BaseplateCoreParamsData(
            base_profile_lower_chamfer_enabled=self.get_value("lower_chamfer_enabled"),
            base_profile_lower_chamfer_size=self.get_value("lower_chamfer_size"),
            base_profile_top_crop=self.get_value("top_crop"),
        )


class ClickSpringParams(ParameterGroup):
    """Parameters for click/snap spring features."""

    _category = "Gridfinity_ClickSpring"
    _section_title = "Snap Springs"

    def __init__(self, **kwargs) -> None:
        """Initialize with spring thickness, length, and offset."""
        parameters = [
            BooleanParam(
                "enabled",
                "Enabled",
                default_value=True,
            ),
            FloatParam(
                "click_thickness",
                "Click Thickness",
                fc.Units.Quantity("0.8 mm"),
            ),
            FloatParam(
                "click_length",
                "Click Length",
                fc.Units.Quantity("12 mm"),
            ),
            FloatParam(
                "click_offset",
                "Click Offset",
                fc.Units.Quantity("0.55 mm"),
            ),
        ]

        super().__init__(parameters)
        self.set_all_values(kwargs)

    def data(self) -> ClickSpringParamsData:
        """Return immutable data container."""
        return ClickSpringParamsData(
            enabled=self.get_value("enabled"),
            click_thickness=self.get_value("click_thickness"),
            click_length=self.get_value("click_length"),
            click_offset=self.get_value("click_offset"),
        )


class JunctionScrewParams(ParameterGroup):
    """Parameters for junction screw holes."""

    _category = "Gridfinity_JunctionScrew"
    _section_title = "Junction Screws"

    def __init__(self, **kwargs) -> None:
        """Initialize with screw diameter and counterbore settings."""
        parameters = [
            BooleanParam(
                "enabled",
                "Enabled",
                default_value=True,
            ),
            FloatParam(
                "screw_diameter",
                "Screw Diameter",
                fc.Units.Quantity("3.3 mm"),
            ),
            FloatParam(
                "counterbore_diameter",
                "Counterbore Diameter",
                fc.Units.Quantity("6.0 mm"),
            ),
            FloatParam(
                "counterbore_depth",
                "Counterbore Depth",
                fc.Units.Quantity("1.5 mm"),
            ),
        ]

        super().__init__(parameters)
        self.set_all_values(kwargs)

    def data(self) -> JunctionScrewParamsData:
        """Return immutable data container."""
        return JunctionScrewParamsData(
            enabled=self.get_value("enabled"),
            screw_diameter=self.get_value("screw_diameter"),
            counterbore_diameter=self.get_value("counterbore_diameter"),
            counterbore_depth=self.get_value("counterbore_depth"),
        )


class ScrewStubParams(ParameterGroup):
    """Parameters for screw stubs (clearance settings)."""

    _category = "Gridfinity_ScrewStub"
    _section_title = "Screw Stubs"

    def __init__(self, **kwargs) -> None:
        """Initialize with screw stub enabled state and clearance."""
        parameters = [
            BooleanParam(
                "enabled",
                "Enabled",
                default_value=False,
            ),
            FloatParam(
                "clearance",
                "Clearance",
                fc.Units.Quantity("0.15 mm"),
            ),
        ]

        super().__init__(parameters)
        self.set_all_values(kwargs)

    def data(self) -> ScrewStubParamsData:
        """Return immutable data container."""
        return ScrewStubParamsData(
            enabled=self.get_value("enabled"),
            clearance=self.get_value("clearance"),
        )


class SupportParams(ParameterGroup):
    """Parameters for overhang support generation."""

    _category = "Gridfinity_Support"
    _section_title = "Support"

    def __init__(self, **kwargs) -> None:
        """Initialize with overhang angle."""
        parameters = [
            FloatParam(
                "overhang_angle",
                "Overhang Angle",
                fc.Units.Quantity("50.0 deg"),
                freecad_property_type="App::PropertyAngle",
            ),
        ]

        super().__init__(parameters)
        self.set_all_values(kwargs)

    def data(self) -> SupportParamsData:
        """Return immutable data container."""
        return SupportParamsData(overhang_angle=self.get_value("overhang_angle"))


class StackingParams(ParameterGroup):
    """Parameters for stacking/instancing baseplates."""

    _category = "Gridfinity_Stacking"
    _section_title = "Stacking"

    def __init__(self, **kwargs) -> None:
        """Initialize with instance count and stitching settings."""
        parameters = [
            IntParam(
                "instance_count",
                "Instance Count",
                3,
                min_value=1,
            ),
            BooleanParam(
                "corner_stitching",
                "Corner Stitching",
                default_value=False,
            ),
            FloatParam(
                "stitching_thickness",
                "Stitching Thickness",
                fc.Units.Quantity("0.4 mm"),
                positive_only=True,
            ),
        ]

        super().__init__(parameters)
        self.set_all_values(kwargs)

    def data(self) -> StackingParamsData:
        """Return immutable data container."""
        return StackingParamsData(
            instance_count=self.get_value("instance_count"),
            corner_stitching=self.get_value("corner_stitching"),
            stitching_thickness=self.get_value("stitching_thickness"),
        )


class CombinedBaseplateParams(CombinedParams):
    """Combined parameters for full baseplate geometry generation."""

    def __init__(  # noqa: PLR0913
        self,
        fundamentals: FundamentalsParams = None,
        size: BaseplateSizeParams = None,
        core: BaseplateCoreParams = None,
        click_springs: ClickSpringParams = None,
        junction_screws: JunctionScrewParams = None,
        clip_cutouts: ClipParams = None,
    ) -> None:
        """Initialize with all baseplate parameter groups."""
        super().__init__(
            fundamentals=fundamentals or FundamentalsParams(),
            size=size or BaseplateSizeParams(),
            core=core or BaseplateCoreParams(),
            click_springs=click_springs or ClickSpringParams(),
            junction_screws=junction_screws or JunctionScrewParams(),
            clip_cutouts=clip_cutouts or ClipParams(),
        )

    def validate(self) -> dict[str, str]:  # noqa: C901, PLR0912, PLR0915
        """Validate cross-group constraints."""
        errors = super().validate()
        fundamentals = self.fundamentals.data()
        size = self.size.data()
        core = self.core.data()
        click = self.click_springs.data()
        junction = self.junction_screws.data()
        clip = self.clip_cutouts.data()

        half_width = float(fundamentals.main_half_width)
        outer_radius = float(fundamentals.bin_outer_radius)
        top_crop = float(core.base_profile_top_crop)
        grid_size = float(fundamentals.x_grid_size)

        if not top_crop < half_width:
            errors["core.base_profile_top_crop"] = (
                "Top crop must be less than main profile half width"
            )
        if not outer_radius > half_width:
            errors["fundamentals.outer_radius"] = (
                "Outer radius must be greater than main profile half width"
            )

        if click.enabled:
            if not float(click.click_thickness) < half_width:
                errors["click_springs.click_thickness"] = (
                    "Click thickness must be less than main profile half width"
                )
            bin_vertical_radius = outer_radius - half_width
            max_half = grid_size / 4 - bin_vertical_radius
            if not float(click.click_length) / 2 < max_half:
                errors["click_springs.click_length"] = (
                    "Click length/2 must be less than grid_size/4 - (outer_radius - half_width)"
                )

        if junction.enabled:
            screw_d = float(junction.screw_diameter)
            counterbore_d = float(junction.counterbore_diameter)
            counterbore_depth = float(junction.counterbore_depth)
            if not screw_d > 0:
                errors["junction_screws.screw_diameter"] = "Screw diameter must be greater than 0"
            if not counterbore_d > 0:
                errors["junction_screws.counterbore_diameter"] = (
                    "Counterbore diameter must be greater than 0"
                )
            if not counterbore_depth > 0:
                errors["junction_screws.counterbore_depth"] = (
                    "Counterbore depth must be greater than 0"
                )
            if not counterbore_d > screw_d:
                errors["junction_screws.counterbore_diameter"] = (
                    "Counterbore diameter must be greater than screw diameter"
                )

        if clip.enabled:
            clip_length = float(clip.clip_length)
            clip_tolerance = float(clip.clip_tolerance)
            max_clip = 2 * half_width
            if not clip_length > 0:
                errors["clip_cutouts.clip_length"] = "Clip length must be greater than 0"
            if not clip_length < max_clip:
                errors["clip_cutouts.clip_length"] = (
                    "Clip length must be less than 2 * main profile half width"
                )
            if not clip_tolerance >= 0:
                errors["clip_cutouts.tolerance"] = (
                    "Clip tolerance must be greater than or equal to 0"
                )

        x_units = int(size.x_grid_count)
        y_units = int(size.y_grid_count)
        left_present = size.filler_left_enabled and float(size.filler_left_width) > 0
        right_present = size.filler_right_enabled and float(size.filler_right_width) > 0
        top_present = size.filler_top_enabled and float(size.filler_top_width) > 0
        bottom_present = size.filler_bottom_enabled and float(size.filler_bottom_width) > 0

        if x_units == 0 and not (left_present or right_present):
            errors["size.x_grid_count"] = "X grid count 0 requires left or right filler"
        if y_units == 0 and not (top_present or bottom_present):
            errors["size.y_grid_count"] = "Y grid count 0 requires top or bottom filler"
        if x_units == 0 and y_units == 0:
            errors["size.x_grid_count"] = "X and Y grid count cannot both be 0"
            errors["size.y_grid_count"] = "X and Y grid count cannot both be 0"

        filler_checks = [
            (size.filler_left_enabled, float(size.filler_left_width), "size.filler_left_width"),
            (size.filler_right_enabled, float(size.filler_right_width), "size.filler_right_width"),
            (size.filler_top_enabled, float(size.filler_top_width), "size.filler_top_width"),
            (
                size.filler_bottom_enabled,
                float(size.filler_bottom_width),
                "size.filler_bottom_width",
            ),
        ]
        for enabled, width, key in filler_checks:
            if enabled and not (0 < width < grid_size):
                errors[key] = "Filler width must be greater than 0 and less than grid size"

        two_radius = 2 * outer_radius
        if (
            size.filler_left_enabled
            and x_units == 0
            and not float(size.filler_left_width) > two_radius
        ):
            errors["size.filler_left_width"] = (
                "With x grid count 0, left filler width must be greater than 2 * outer radius"
            )
        if (
            size.filler_right_enabled
            and x_units == 0
            and not float(size.filler_right_width) > two_radius
        ):
            errors["size.filler_right_width"] = (
                "With x grid count 0, right filler width must be greater than 2 * outer radius"
            )
        if (
            size.filler_top_enabled
            and y_units == 0
            and not float(size.filler_top_width) > two_radius
        ):
            errors["size.filler_top_width"] = (
                "With y grid count 0, top filler width must be greater than 2 * outer radius"
            )
        if (
            size.filler_bottom_enabled
            and y_units == 0
            and not float(size.filler_bottom_width) > two_radius
        ):
            errors["size.filler_bottom_width"] = (
                "With y grid count 0, bottom filler width must be greater than 2 * outer radius"
            )

        return errors

    def data(self) -> CombinedBaseplateParamsData:
        """Return validated immutable combined data container."""
        size = self.size.data()
        core = self.core.data()
        return CombinedBaseplateParamsData(
            fundamentals=self.fundamentals.data(),
            core=BaseplateCoreLayoutParamsData(
                x_grid_count=size.x_grid_count,
                y_grid_count=size.y_grid_count,
                base_profile_lower_chamfer_enabled=core.base_profile_lower_chamfer_enabled,
                base_profile_lower_chamfer_size=core.base_profile_lower_chamfer_size,
                base_profile_top_crop=core.base_profile_top_crop,
            ),
            fillers=BaseplateFillersParamsData(
                left_enabled=size.filler_left_enabled,
                left_width=size.filler_left_width,
                right_enabled=size.filler_right_enabled,
                right_width=size.filler_right_width,
                top_enabled=size.filler_top_enabled,
                top_width=size.filler_top_width,
                bottom_enabled=size.filler_bottom_enabled,
                bottom_width=size.filler_bottom_width,
            ),
            click_springs=self.click_springs.data(),
            junction_screws=self.junction_screws.data(),
            screw_stubs=ScrewStubParamsData(enabled=False, clearance=fc.Units.Quantity("0.15 mm")),
            clip_cutouts=self.clip_cutouts.data(),
        )


class CombinedSupportBaseplateParams(CombinedParams):
    """Combined parameters for support baseplate geometry generation."""

    def __init__(
        self,
        fundamentals: FundamentalsParams = None,
        size: BaseplateSizeParams = None,
        core: BaseplateCoreParams = None,
        click_springs: ClickSpringParams = None,
        support: SupportParams = None,
    ) -> None:
        """Initialize with fundamentals, size, core, click springs, and support."""
        super().__init__(
            fundamentals=fundamentals or FundamentalsParams(),
            size=size or BaseplateSizeParams(),
            core=core or BaseplateCoreParams(),
            click_springs=click_springs or ClickSpringParams(),
            support=support or SupportParams(),
        )

    def validate(self) -> dict[str, str]:
        """Validate cross-group constraints."""
        errors = super().validate()
        fundamentals = self.fundamentals.data()
        core = self.core.data()
        half_width = float(fundamentals.main_half_width)
        outer_radius = float(fundamentals.bin_outer_radius)
        top_crop = float(core.base_profile_top_crop)

        if not top_crop < half_width:
            errors["core.base_profile_top_crop"] = (
                "Top crop must be less than main profile half width"
            )
        if not outer_radius > half_width:
            errors["fundamentals.outer_radius"] = (
                "Outer radius must be greater than main profile half width"
            )
        return errors

    def data(self) -> CombinedSupportBaseplateParamsData:
        """Return validated immutable combined data container."""
        size = self.size.data()
        core = self.core.data()
        return CombinedSupportBaseplateParamsData(
            fundamentals=self.fundamentals.data(),
            core=BaseplateCoreLayoutParamsData(
                x_grid_count=size.x_grid_count,
                y_grid_count=size.y_grid_count,
                base_profile_lower_chamfer_enabled=core.base_profile_lower_chamfer_enabled,
                base_profile_lower_chamfer_size=core.base_profile_lower_chamfer_size,
                base_profile_top_crop=core.base_profile_top_crop,
            ),
            fillers=BaseplateFillersParamsData(
                left_enabled=size.filler_left_enabled,
                left_width=size.filler_left_width,
                right_enabled=size.filler_right_enabled,
                right_width=size.filler_right_width,
                top_enabled=size.filler_top_enabled,
                top_width=size.filler_top_width,
                bottom_enabled=size.filler_bottom_enabled,
                bottom_width=size.filler_bottom_width,
            ),
            click_springs=self.click_springs.data(),
            support=self.support.data(),
        )


class CombinedStackedBaseplatesParams(CombinedParams):
    """Combined parameters for stacked baseplates geometry generation."""

    def __init__(  # noqa: PLR0913
        self,
        fundamentals: FundamentalsParams = None,
        size: BaseplateSizeParams = None,
        core: BaseplateCoreParams = None,
        click_springs: ClickSpringParams = None,
        junction_screws: JunctionScrewParams = None,
        screw_stubs: ScrewStubParams = None,
        support: SupportParams = None,
        stacking: StackingParams = None,
        clip_cutouts: ClipParams = None,
    ) -> None:
        """Initialize with all stacked baseplates parameter groups."""
        super().__init__(
            fundamentals=fundamentals or FundamentalsParams(),
            size=size or BaseplateSizeParams(),
            core=core or BaseplateCoreParams(),
            click_springs=click_springs or ClickSpringParams(),
            junction_screws=junction_screws or JunctionScrewParams(),
            screw_stubs=screw_stubs or ScrewStubParams(),
            support=support or SupportParams(),
            stacking=stacking or StackingParams(),
            clip_cutouts=clip_cutouts or ClipParams(),
        )

    def validate(self) -> dict[str, str]:
        """Validate cross-group constraints."""
        errors = CombinedBaseplateParams(
            fundamentals=self.fundamentals,
            size=self.size,
            core=self.core,
            click_springs=self.click_springs,
            junction_screws=self.junction_screws,
            clip_cutouts=self.clip_cutouts,
        ).validate()
        screw_stubs = self.screw_stubs.data()
        junction = self.junction_screws.data()
        if screw_stubs.enabled:
            if not junction.enabled:
                errors["screw_stubs.enabled"] = "Screw stubs require junction screws"
            if not float(screw_stubs.clearance) >= 0:
                errors["screw_stubs.clearance"] = "Screw stub clearance must be >= 0"
            stub_d = float(junction.screw_diameter) - 2 * float(screw_stubs.clearance)
            if not stub_d > 0:
                errors["screw_stubs.clearance"] = "Screw stub clearance is too large"
        return errors

    def data(self) -> CombinedStackedBaseplatesParamsData:
        """Return validated immutable combined data container."""
        size = self.size.data()
        core = self.core.data()
        return CombinedStackedBaseplatesParamsData(
            fundamentals=self.fundamentals.data(),
            core=BaseplateCoreLayoutParamsData(
                x_grid_count=size.x_grid_count,
                y_grid_count=size.y_grid_count,
                base_profile_lower_chamfer_enabled=core.base_profile_lower_chamfer_enabled,
                base_profile_lower_chamfer_size=core.base_profile_lower_chamfer_size,
                base_profile_top_crop=core.base_profile_top_crop,
            ),
            fillers=BaseplateFillersParamsData(
                left_enabled=size.filler_left_enabled,
                left_width=size.filler_left_width,
                right_enabled=size.filler_right_enabled,
                right_width=size.filler_right_width,
                top_enabled=size.filler_top_enabled,
                top_width=size.filler_top_width,
                bottom_enabled=size.filler_bottom_enabled,
                bottom_width=size.filler_bottom_width,
            ),
            click_springs=self.click_springs.data(),
            junction_screws=self.junction_screws.data(),
            screw_stubs=self.screw_stubs.data(),
            support=self.support.data(),
            stacking=self.stacking.data(),
            clip_cutouts=self.clip_cutouts.data(),
        )


@dataclass(frozen=True)
class DrawerParamsData:
    """Immutable data container for drawer fitting parameters."""

    drawer_width: fc.Units.Quantity
    drawer_depth: fc.Units.Quantity
    width_filler_alignment: str
    depth_filler_alignment: str
    split_algorithm: str
    printer_bed_width: fc.Units.Quantity
    printer_bed_depth: fc.Units.Quantity


@dataclass(frozen=True)
class CombinedDrawerBaseplateParamsData:
    """Immutable combined data for drawer baseplate geometry generation."""

    fundamentals: FundamentalsParamsData
    core: BaseplateCoreLayoutParamsData
    fillers: BaseplateFillersParamsData
    click_springs: ClickSpringParamsData
    junction_screws: JunctionScrewParamsData
    clip_cutouts: ClipParamsData
    drawer: DrawerParamsData


class DrawerParams(ParameterGroup):
    """Drawer fitting parameters for drawer baseplates.

    Uses MEM default type - values are remembered within the session so
    creating a new drawer baseplate defaults to the last used dimensions.
    """

    _category = "Gridfinity_Drawer"
    _section_title = "Drawer"
    _default_type = DefaultType.MEM

    def __init__(self, **kwargs) -> None:
        """Initialize with drawer dimensions and fitting settings."""
        parameters = [
            FloatParam(
                "drawer_width",
                "Drawer Width",
                fc.Units.Quantity("600 mm"),
                positive_only=True,
            ),
            FloatParam(
                "drawer_depth",
                "Drawer Depth",
                fc.Units.Quantity("600 mm"),
                positive_only=True,
            ),
            LiteralParam(
                "width_filler_alignment",
                "Width Filler Alignment",
                "Right",
                choices=["Left", "Right", "Both"],
            ),
            LiteralParam(
                "depth_filler_alignment",
                "Depth Filler Alignment",
                "Top",
                choices=["Bottom", "Top", "Both"],
            ),
            LiteralParam(
                "split_algorithm",
                "Split Algorithm",
                "Balanced",
                choices=["Balanced", "Greedy"],
            ),
            FloatParam(
                "printer_bed_width",
                "Printer Bed Width",
                fc.Units.Quantity("256 mm"),
                positive_only=True,
            ),
            FloatParam(
                "printer_bed_depth",
                "Printer Bed Depth",
                fc.Units.Quantity("240 mm"),
                positive_only=True,
            ),
        ]

        super().__init__(parameters)
        self.set_all_values(kwargs)

    def data(self) -> DrawerParamsData:
        """Return immutable data container."""
        return DrawerParamsData(
            drawer_width=self.get_value("drawer_width"),
            drawer_depth=self.get_value("drawer_depth"),
            width_filler_alignment=self.get_value("width_filler_alignment"),
            depth_filler_alignment=self.get_value("depth_filler_alignment"),
            split_algorithm=self.get_value("split_algorithm"),
            printer_bed_width=self.get_value("printer_bed_width"),
            printer_bed_depth=self.get_value("printer_bed_depth"),
        )


class CombinedDrawerBaseplateParams(CombinedParams):
    """Combined parameters for drawer baseplate geometry generation."""

    def __init__(  # noqa: PLR0913
        self,
        fundamentals: FundamentalsParams = None,
        size: BaseplateSizeParams = None,
        core: BaseplateCoreParams = None,
        click_springs: ClickSpringParams = None,
        junction_screws: JunctionScrewParams = None,
        clip_cutouts: ClipParams = None,
        drawer: DrawerParams = None,
    ) -> None:
        """Initialize with all drawer baseplate parameter groups."""
        super().__init__(
            fundamentals=fundamentals or FundamentalsParams(),
            size=size or BaseplateSizeParams(),
            core=core or BaseplateCoreParams(),
            click_springs=click_springs or ClickSpringParams(),
            junction_screws=junction_screws or JunctionScrewParams(),
            clip_cutouts=clip_cutouts or ClipParams(),
            drawer=drawer or DrawerParams(),
        )

    def validate(self) -> dict[str, str]:
        """Validate cross-group constraints."""
        errors = CombinedBaseplateParams(
            fundamentals=self.fundamentals,
            size=self.size,
            core=self.core,
            click_springs=self.click_springs,
            junction_screws=self.junction_screws,
            clip_cutouts=self.clip_cutouts,
        ).validate()
        drawer = self.drawer.data()
        if float(drawer.drawer_width) <= 0:
            errors["drawer.drawer_width"] = "Drawer width must be greater than 0"
        if float(drawer.drawer_depth) <= 0:
            errors["drawer.drawer_depth"] = "Drawer depth must be greater than 0"
        if float(drawer.printer_bed_width) <= 0:
            errors["drawer.printer_bed_width"] = "Printer bed width must be greater than 0"
        if float(drawer.printer_bed_depth) <= 0:
            errors["drawer.printer_bed_depth"] = "Printer bed depth must be greater than 0"
        return errors

    def baseplate_data(self) -> CombinedBaseplateParamsData:
        """Return baseplate-only data container for builder compatibility."""
        size = self.size.data()
        core = self.core.data()
        return CombinedBaseplateParamsData(
            fundamentals=self.fundamentals.data(),
            core=BaseplateCoreLayoutParamsData(
                x_grid_count=size.x_grid_count,
                y_grid_count=size.y_grid_count,
                base_profile_lower_chamfer_enabled=core.base_profile_lower_chamfer_enabled,
                base_profile_lower_chamfer_size=core.base_profile_lower_chamfer_size,
                base_profile_top_crop=core.base_profile_top_crop,
            ),
            fillers=BaseplateFillersParamsData(
                left_enabled=size.filler_left_enabled,
                left_width=size.filler_left_width,
                right_enabled=size.filler_right_enabled,
                right_width=size.filler_right_width,
                top_enabled=size.filler_top_enabled,
                top_width=size.filler_top_width,
                bottom_enabled=size.filler_bottom_enabled,
                bottom_width=size.filler_bottom_width,
            ),
            click_springs=self.click_springs.data(),
            junction_screws=self.junction_screws.data(),
            screw_stubs=ScrewStubParamsData(enabled=False, clearance=fc.Units.Quantity("0.15 mm")),
            clip_cutouts=self.clip_cutouts.data(),
        )

    def data(self) -> CombinedDrawerBaseplateParamsData:
        """Return validated immutable combined data container."""
        size = self.size.data()
        core = self.core.data()
        return CombinedDrawerBaseplateParamsData(
            fundamentals=self.fundamentals.data(),
            core=BaseplateCoreLayoutParamsData(
                x_grid_count=size.x_grid_count,
                y_grid_count=size.y_grid_count,
                base_profile_lower_chamfer_enabled=core.base_profile_lower_chamfer_enabled,
                base_profile_lower_chamfer_size=core.base_profile_lower_chamfer_size,
                base_profile_top_crop=core.base_profile_top_crop,
            ),
            fillers=BaseplateFillersParamsData(
                left_enabled=size.filler_left_enabled,
                left_width=size.filler_left_width,
                right_enabled=size.filler_right_enabled,
                right_width=size.filler_right_width,
                top_enabled=size.filler_top_enabled,
                top_width=size.filler_top_width,
                bottom_enabled=size.filler_bottom_enabled,
                bottom_width=size.filler_bottom_width,
            ),
            click_springs=self.click_springs.data(),
            junction_screws=self.junction_screws.data(),
            clip_cutouts=self.clip_cutouts.data(),
            drawer=self.drawer.data(),
        )


class PluginSettingsParams(ParameterGroup):
    """Plugin-level settings (cache sizes, etc.) - not used for geometry.

    Uses SAVED default type - values persist to FreeCAD preferences and
    survive across sessions. Changed via Edit Defaults UI.
    """

    _category = "Gridfinity_PluginSettings"
    _section_title = "Performance"
    _default_type = DefaultType.SAVED

    def __init__(self, **kwargs) -> None:
        """Initialize with cache size settings."""
        parameters = [
            IntParam(
                "baseplate_cache_size",
                "Baseplate Cache Size",
                32,
                min_value=0,
                max_value=4096,
            ),
            IntParam(
                "cell_cache_size",
                "Cell Cache Size",
                64,
                min_value=0,
                max_value=4096,
            ),
        ]

        super().__init__(parameters)
        self.set_all_values(kwargs)

    def data(self) -> None:
        """Plugin settings don't have a data object - they apply directly to system."""

    def apply_to_system(self) -> None:
        """Apply cache settings to the baseplate builder."""
        from . import baseplate_builder

        baseplate_builder.set_baseplate_shape_cache_max_entries(
            int(self.get_value("baseplate_cache_size")),
        )
        baseplate_builder.set_cell_shape_cache_max_entries(int(self.get_value("cell_cache_size")))
