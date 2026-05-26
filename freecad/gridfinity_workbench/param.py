"""Concrete parameter groups and data containers.

This module defines the actual parameter groups used by Gridfinity objects.
Each ParameterGroup subclass sets `_default_type` to control how defaults
are resolved for all parameters in the group:

- DefaultType.VALUE: Hardcoded defaults (most groups use this)
- DefaultType.MEM: Remember last used values within session (BaseplateSizeParams)
- DefaultType.SAVED: Persist to FreeCAD preferences (PluginSettingsParams)

CANONICAL DATA CLASS REQUIREMENT:
All *ParamsData dataclasses must use field names that exactly match the
corresponding ParameterGroup's parameter names. This 1:1 mapping ensures
consistency between UI parameters and data containers. Do not rename, prefix,
or transform field names in data classes.
"""

from __future__ import annotations

from dataclasses import dataclass

import FreeCAD as fc  # noqa: N813

from .param_system import (
    BaseParam,
    BooleanParam,
    CombinedParams,
    DefaultType,
    FloatParam,
    IntParam,
    LiteralParam,
    OptionalLayoutParam,
    OptionalQuantityParam,
    ParamCombination,
    ParameterGroup,
    ParameterValidationError,
    ValidationError,
)


@dataclass(frozen=True)
class FundamentalsParamsData:
    """Immutable data container for fundamental Gridfinity dimensions."""

    grid_size: fc.Units.Quantity
    outer_radius: fc.Units.Quantity
    main_half_width: fc.Units.Quantity
    main_height: fc.Units.Quantity


@dataclass(frozen=True)
class ConnectingClipsParamsData:
    """Immutable data container for connecting clip cutout parameters."""

    enabled: bool
    tolerance: fc.Units.Quantity
    clip_length: fc.Units.Quantity


@dataclass(frozen=True)
class CombinedConnectingClipsParamsData:
    """Immutable combined data for connecting clip geometry generation."""

    fundamentals: FundamentalsParamsData
    connecting_clips: ConnectingClipsParamsData


@dataclass(frozen=True)
class BaseplateSizeParamsData:
    """Immutable data container for baseplate size (grid counts, fillers)."""

    x_grid_count: int
    y_grid_count: int
    filler_top_enabled: bool
    filler_top_width: fc.Units.Quantity
    filler_right_enabled: bool
    filler_right_width: fc.Units.Quantity
    filler_bottom_enabled: bool
    filler_bottom_width: fc.Units.Quantity
    filler_left_enabled: bool
    filler_left_width: fc.Units.Quantity
    custom_layout_enabled: bool
    custom_layout: list[list[bool]] | None


@dataclass(frozen=True)
class BaseplateCoreParamsData:
    """Immutable data container for baseplate core profile parameters."""

    lower_chamfer_enabled: bool
    lower_chamfer_size: fc.Units.Quantity
    top_crop: fc.Units.Quantity


@dataclass(frozen=True)
class ClickSpringsParamsData:
    """Immutable data container for click/snap spring parameters."""

    enabled: bool
    click_thickness: fc.Units.Quantity
    click_length: fc.Units.Quantity
    click_offset: fc.Units.Quantity


@dataclass(frozen=True)
class JunctionScrewsParamsData:
    """Immutable data container for junction screw parameters."""

    enabled: bool
    screw_diameter: fc.Units.Quantity
    counterbore_diameter: fc.Units.Quantity
    counterbore_depth: fc.Units.Quantity


@dataclass(frozen=True)
class ScrewStubsParamsData:
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
    baseplate_size: BaseplateSizeParamsData
    baseplate_core: BaseplateCoreParamsData
    click_springs: ClickSpringsParamsData
    support: SupportParamsData


@dataclass(frozen=True)
class CombinedBaseplateParamsData:
    """Immutable combined data for baseplate geometry generation."""

    fundamentals: FundamentalsParamsData
    baseplate_size: BaseplateSizeParamsData
    baseplate_core: BaseplateCoreParamsData
    click_springs: ClickSpringsParamsData
    junction_screws: JunctionScrewsParamsData
    screw_stubs: ScrewStubsParamsData
    connecting_clips: ConnectingClipsParamsData


@dataclass(frozen=True)
class CombinedStackedBaseplatesParamsData:
    """Immutable combined data for stacked baseplates geometry generation."""

    fundamentals: FundamentalsParamsData
    baseplate_size: BaseplateSizeParamsData
    baseplate_core: BaseplateCoreParamsData
    click_springs: ClickSpringsParamsData
    junction_screws: JunctionScrewsParamsData
    screw_stubs: ScrewStubsParamsData
    support: SupportParamsData
    stacking: StackingParamsData
    connecting_clips: ConnectingClipsParamsData


class FundamentalsParams(ParameterGroup):
    """Fundamental Gridfinity dimensions (grid size, radius, profile)."""

    _default_type = DefaultType.SAVED

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
            grid_size=self.get_value("grid_size"),
            outer_radius=self.get_value("outer_radius"),
            main_half_width=self.get_value("main_half_width"),
            main_height=self.get_value("main_height"),
        )


class ConnectingClipsParams(ParameterGroup):
    """Parameters for connecting clip cutout features on baseplates."""

    _default_type = DefaultType.SAVED

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

    def data(self) -> ConnectingClipsParamsData:
        """Return validated immutable data container."""
        errors = self.validate()
        if errors:
            raise ParameterValidationError(errors)
        return ConnectingClipsParamsData(
            enabled=self.get_value("enabled"),
            tolerance=self.get_value("tolerance"),
            clip_length=self.get_value("clip_length"),
        )


class CombinedConnectingClipsParams(CombinedParams):
    """Combined parameters for connecting clip geometry (fundamentals + clip settings)."""

    def __init__(
        self,
        connecting_clips: ConnectingClipsParams = None,
        fundamentals: FundamentalsParams = None,
    ) -> None:
        """Initialize with fundamentals and connecting clip parameter groups."""
        super().__init__(
            connecting_clips=connecting_clips or ConnectingClipsParams(),
            fundamentals=fundamentals or FundamentalsParams(),
        )

    def validate(self) -> list[ValidationError]:
        """Validate cross-group constraints."""
        errors = super().validate()
        try:
            tolerance_val = float(self.connecting_clips.get_value("tolerance"))
            clip_length_val = float(self.connecting_clips.get_value("clip_length"))
            if clip_length_val <= 2 * tolerance_val:
                msg = (
                    f"Clip length ({clip_length_val}) must be > 2 * tolerance ({2 * tolerance_val})"
                )
                errors.append(
                    ValidationError(
                        message=msg,
                        affected_params=("connecting_clips.clip_length",),
                    )
                )
        except (AttributeError, KeyError, TypeError, ValueError):
            pass
        return errors

    def data(self) -> CombinedConnectingClipsParamsData:
        """Return validated immutable combined data container."""
        errors = self.validate()
        if errors:
            raise ParameterValidationError(errors)
        return CombinedConnectingClipsParamsData(
            fundamentals=self.fundamentals.data(),
            connecting_clips=self.connecting_clips.data(),
        )


class BaseplateSizeParams(ParameterGroup):
    """Baseplate size parameters (grid counts, filler dimensions).

    Uses MEM default type - values are remembered within the session so
    creating a new baseplate defaults to the last used grid size.
    """

    _default_type = DefaultType.MEM

    def __init__(self, **kwargs) -> None:
        """Initialize with grid counts and filler dimensions."""
        parameters: list[BaseParam | ParamCombination] = [
            IntParam("x_grid_count", "X Grid Count", 2, min_value=0),
            IntParam("y_grid_count", "Y Grid Count", 2, min_value=0),
            OptionalQuantityParam(
                "filler_top",
                "Top Filler",
                enabled_suffix="_enabled",
                quantity_suffix="_width",
                default_quantity=fc.Units.Quantity("30 mm"),
            ),
            OptionalQuantityParam(
                "filler_right",
                "Right Filler",
                enabled_suffix="_enabled",
                quantity_suffix="_width",
                default_quantity=fc.Units.Quantity("30 mm"),
            ),
            OptionalQuantityParam(
                "filler_bottom",
                "Bottom Filler",
                enabled_suffix="_enabled",
                quantity_suffix="_width",
                default_quantity=fc.Units.Quantity("30 mm"),
            ),
            OptionalQuantityParam(
                "filler_left",
                "Left Filler",
                enabled_suffix="_enabled",
                quantity_suffix="_width",
                default_quantity=fc.Units.Quantity("30 mm"),
            ),
            OptionalLayoutParam(
                "custom_layout",
                "Custom Layout",
                enabled_suffix="_enabled",
                layout_suffix="",
            ),
        ]

        super().__init__(parameters)
        self.set_all_values(kwargs)

    def data(self) -> BaseplateSizeParamsData:
        """Return immutable data container."""
        return BaseplateSizeParamsData(
            x_grid_count=self.get_value("x_grid_count"),
            y_grid_count=self.get_value("y_grid_count"),
            filler_top_enabled=self.get_value("filler_top_enabled"),
            filler_top_width=self.get_value("filler_top_width"),
            filler_right_enabled=self.get_value("filler_right_enabled"),
            filler_right_width=self.get_value("filler_right_width"),
            filler_bottom_enabled=self.get_value("filler_bottom_enabled"),
            filler_bottom_width=self.get_value("filler_bottom_width"),
            filler_left_enabled=self.get_value("filler_left_enabled"),
            filler_left_width=self.get_value("filler_left_width"),
            custom_layout_enabled=self.get_value("custom_layout_enabled"),
            custom_layout=self.get_value("custom_layout"),
        )


class BaseplateCoreParams(ParameterGroup):
    """Core baseplate profile parameters (chamfer, top crop)."""

    _default_type = DefaultType.SAVED

    def __init__(self, **kwargs) -> None:
        """Initialize with chamfer and top crop settings."""
        parameters: list[BaseParam | ParamCombination] = [
            OptionalQuantityParam(
                "lower_chamfer",
                "Lower Chamfer",
                enabled_suffix="_enabled",
                quantity_suffix="_size",
                default_quantity=fc.Units.Quantity("0.7 mm"),
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
            lower_chamfer_enabled=self.get_value("lower_chamfer_enabled"),
            lower_chamfer_size=self.get_value("lower_chamfer_size"),
            top_crop=self.get_value("top_crop"),
        )


class ClickSpringsParams(ParameterGroup):
    """Parameters for click/snap spring features."""

    _default_type = DefaultType.SAVED

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

    def data(self) -> ClickSpringsParamsData:
        """Return immutable data container."""
        return ClickSpringsParamsData(
            enabled=self.get_value("enabled"),
            click_thickness=self.get_value("click_thickness"),
            click_length=self.get_value("click_length"),
            click_offset=self.get_value("click_offset"),
        )


class JunctionScrewsParams(ParameterGroup):
    """Parameters for junction screw holes."""

    _default_type = DefaultType.SAVED

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

    def data(self) -> JunctionScrewsParamsData:
        """Return immutable data container."""
        return JunctionScrewsParamsData(
            enabled=self.get_value("enabled"),
            screw_diameter=self.get_value("screw_diameter"),
            counterbore_diameter=self.get_value("counterbore_diameter"),
            counterbore_depth=self.get_value("counterbore_depth"),
        )


class ScrewStubsParams(ParameterGroup):
    """Parameters for screw stubs (clearance settings)."""

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

    def data(self) -> ScrewStubsParamsData:
        """Return immutable data container."""
        return ScrewStubsParamsData(
            enabled=self.get_value("enabled"),
            clearance=self.get_value("clearance"),
        )


class SupportParams(ParameterGroup):
    """Parameters for overhang support generation."""

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
        baseplate_size: BaseplateSizeParams = None,
        fundamentals: FundamentalsParams = None,
        baseplate_core: BaseplateCoreParams = None,
        click_springs: ClickSpringsParams = None,
        junction_screws: JunctionScrewsParams = None,
        connecting_clips: ConnectingClipsParams = None,
    ) -> None:
        """Initialize with all baseplate parameter groups."""
        super().__init__(
            baseplate_size=baseplate_size or BaseplateSizeParams(),
            fundamentals=fundamentals or FundamentalsParams(),
            baseplate_core=baseplate_core or BaseplateCoreParams(),
            click_springs=click_springs or ClickSpringsParams(),
            junction_screws=junction_screws or JunctionScrewsParams(),
            connecting_clips=connecting_clips or ConnectingClipsParams(),
        )

    def validate(self) -> list[ValidationError]:  # noqa: C901, PLR0912, PLR0915
        """Validate cross-group constraints."""
        errors = super().validate()
        fundamentals = self.fundamentals.data()
        size = self.baseplate_size.data()
        core = self.baseplate_core.data()
        click = self.click_springs.data()
        junction = self.junction_screws.data()
        clip = self.connecting_clips.data()

        half_width = float(fundamentals.main_half_width)
        outer_radius = float(fundamentals.outer_radius)
        top_crop = float(core.top_crop)
        grid_size = float(fundamentals.grid_size)

        if not top_crop < half_width:
            errors.append(
                ValidationError(
                    message="Top crop must be less than main profile half width",
                    affected_params=("baseplate_core.top_crop",),
                )
            )
        if not outer_radius > half_width:
            errors.append(
                ValidationError(
                    message="Outer radius must be greater than main profile half width",
                    affected_params=("fundamentals.outer_radius",),
                )
            )

        if click.enabled:
            if not float(click.click_thickness) < half_width:
                errors.append(
                    ValidationError(
                        message="Click thickness must be less than main profile half width",
                        affected_params=("click_springs.click_thickness",),
                    )
                )
            bin_vertical_radius = outer_radius - half_width
            max_half = grid_size / 4 - bin_vertical_radius
            if not float(click.click_length) / 2 < max_half:
                errors.append(
                    ValidationError(
                        message="Click length/2 must be < grid/4 - (radius - half_width)",
                        affected_params=("click_springs.click_length",),
                    )
                )

        if junction.enabled:
            screw_d = float(junction.screw_diameter)
            counterbore_d = float(junction.counterbore_diameter)
            counterbore_depth = float(junction.counterbore_depth)
            if not screw_d > 0:
                errors.append(
                    ValidationError(
                        message="Screw diameter must be greater than 0",
                        affected_params=("junction_screws.screw_diameter",),
                    )
                )
            if not counterbore_d > 0:
                errors.append(
                    ValidationError(
                        message="Counterbore diameter must be greater than 0",
                        affected_params=("junction_screws.counterbore_diameter",),
                    )
                )
            if not counterbore_depth > 0:
                errors.append(
                    ValidationError(
                        message="Counterbore depth must be greater than 0",
                        affected_params=("junction_screws.counterbore_depth",),
                    )
                )
            if not counterbore_d > screw_d:
                errors.append(
                    ValidationError(
                        message="Counterbore diameter must be greater than screw diameter",
                        affected_params=("junction_screws.counterbore_diameter",),
                    )
                )

        if clip.enabled:
            clip_length = float(clip.clip_length)
            clip_tolerance = float(clip.tolerance)
            max_clip = 2 * half_width
            if not clip_length > 0:
                errors.append(
                    ValidationError(
                        message="Clip length must be greater than 0",
                        affected_params=("connecting_clips.clip_length",),
                    )
                )
            if not clip_length < max_clip:
                errors.append(
                    ValidationError(
                        message="Clip length must be less than 2 * main profile half width",
                        affected_params=("connecting_clips.clip_length",),
                    )
                )
            if not clip_tolerance >= 0:
                errors.append(
                    ValidationError(
                        message="Clip tolerance must be greater than or equal to 0",
                        affected_params=("connecting_clips.tolerance",),
                    )
                )

        x_units = int(size.x_grid_count)
        y_units = int(size.y_grid_count)
        left_present = size.filler_left_enabled and float(size.filler_left_width) > 0
        right_present = size.filler_right_enabled and float(size.filler_right_width) > 0
        top_present = size.filler_top_enabled and float(size.filler_top_width) > 0
        bottom_present = size.filler_bottom_enabled and float(size.filler_bottom_width) > 0

        if x_units == 0 and not (left_present or right_present):
            errors.append(
                ValidationError(
                    message="X grid count 0 requires left or right filler",
                    affected_params=("baseplate_size.x_grid_count",),
                )
            )
        if y_units == 0 and not (top_present or bottom_present):
            errors.append(
                ValidationError(
                    message="Y grid count 0 requires top or bottom filler",
                    affected_params=("baseplate_size.y_grid_count",),
                )
            )
        if x_units == 0 and y_units == 0:
            errors.append(
                ValidationError(
                    message="X and Y grid count cannot both be 0",
                    affected_params=(
                        "baseplate_size.x_grid_count",
                        "baseplate_size.y_grid_count",
                    ),
                )
            )

        filler_checks = [
            (
                size.filler_left_enabled,
                float(size.filler_left_width),
                "baseplate_size.filler_left_width",
            ),
            (
                size.filler_right_enabled,
                float(size.filler_right_width),
                "baseplate_size.filler_right_width",
            ),
            (
                size.filler_top_enabled,
                float(size.filler_top_width),
                "baseplate_size.filler_top_width",
            ),
            (
                size.filler_bottom_enabled,
                float(size.filler_bottom_width),
                "baseplate_size.filler_bottom_width",
            ),
        ]
        for enabled, width, key in filler_checks:
            if enabled and not (0 < width < grid_size):
                errors.append(
                    ValidationError(
                        message="Filler width must be greater than 0 and less than grid size",
                        affected_params=(key,),
                    )
                )

        # Custom layout validation
        if size.custom_layout_enabled:
            # Require layout to be defined when enabled
            if not size.custom_layout:
                errors.append(
                    ValidationError(
                        message="Custom layout must be defined when enabled",
                        affected_params=("baseplate_size.custom_layout",),
                    )
                )
            # Custom layout and fillers are mutually exclusive
            conflicting_fillers: list[str] = []
            if size.filler_left_enabled:
                conflicting_fillers.append("baseplate_size.filler_left_enabled")
            if size.filler_right_enabled:
                conflicting_fillers.append("baseplate_size.filler_right_enabled")
            if size.filler_top_enabled:
                conflicting_fillers.append("baseplate_size.filler_top_enabled")
            if size.filler_bottom_enabled:
                conflicting_fillers.append("baseplate_size.filler_bottom_enabled")
            if conflicting_fillers:
                errors.append(
                    ValidationError(
                        message="Custom layout and fillers are mutually exclusive",
                        affected_params=(
                            "baseplate_size.custom_layout_enabled",
                            *conflicting_fillers,
                        ),
                    )
                )

        two_radius = 2 * outer_radius
        if (
            size.filler_left_enabled
            and x_units == 0
            and not float(size.filler_left_width) > two_radius
        ):
            errors.append(
                ValidationError(
                    message="With x=0, left filler width must be > 2 * outer radius",
                    affected_params=("baseplate_size.filler_left_width",),
                )
            )
        if (
            size.filler_right_enabled
            and x_units == 0
            and not float(size.filler_right_width) > two_radius
        ):
            errors.append(
                ValidationError(
                    message="With x=0, right filler width must be > 2 * outer radius",
                    affected_params=("baseplate_size.filler_right_width",),
                )
            )
        if (
            size.filler_top_enabled
            and y_units == 0
            and not float(size.filler_top_width) > two_radius
        ):
            errors.append(
                ValidationError(
                    message="With y=0, top filler width must be > 2 * outer radius",
                    affected_params=("baseplate_size.filler_top_width",),
                )
            )
        if (
            size.filler_bottom_enabled
            and y_units == 0
            and not float(size.filler_bottom_width) > two_radius
        ):
            errors.append(
                ValidationError(
                    message="With y=0, bottom filler width must be > 2 * outer radius",
                    affected_params=("baseplate_size.filler_bottom_width",),
                )
            )

        return errors

    def data(self) -> CombinedBaseplateParamsData:
        """Return validated immutable combined data container."""
        return CombinedBaseplateParamsData(
            fundamentals=self.fundamentals.data(),
            baseplate_size=self.baseplate_size.data(),
            baseplate_core=self.baseplate_core.data(),
            click_springs=self.click_springs.data(),
            junction_screws=self.junction_screws.data(),
            screw_stubs=ScrewStubsParamsData(enabled=False, clearance=fc.Units.Quantity("0.15 mm")),
            connecting_clips=self.connecting_clips.data(),
        )


class CombinedSupportBaseplateParams(CombinedParams):
    """Combined parameters for support baseplate geometry generation."""

    def __init__(
        self,
        fundamentals: FundamentalsParams = None,
        baseplate_size: BaseplateSizeParams = None,
        baseplate_core: BaseplateCoreParams = None,
        click_springs: ClickSpringsParams = None,
        support: SupportParams = None,
    ) -> None:
        """Initialize with fundamentals, size, core, click springs, and support."""
        super().__init__(
            fundamentals=fundamentals or FundamentalsParams(),
            baseplate_size=baseplate_size or BaseplateSizeParams(),
            baseplate_core=baseplate_core or BaseplateCoreParams(),
            click_springs=click_springs or ClickSpringsParams(),
            support=support or SupportParams(),
        )

    def validate(self) -> list[ValidationError]:
        """Validate cross-group constraints."""
        errors = super().validate()
        fundamentals = self.fundamentals.data()
        core = self.baseplate_core.data()
        half_width = float(fundamentals.main_half_width)
        outer_radius = float(fundamentals.outer_radius)
        top_crop = float(core.top_crop)

        if not top_crop < half_width:
            errors.append(
                ValidationError(
                    message="Top crop must be less than main profile half width",
                    affected_params=("baseplate_core.top_crop",),
                )
            )
        if not outer_radius > half_width:
            errors.append(
                ValidationError(
                    message="Outer radius must be greater than main profile half width",
                    affected_params=("fundamentals.outer_radius",),
                )
            )
        return errors

    def data(self) -> CombinedSupportBaseplateParamsData:
        """Return validated immutable combined data container."""
        return CombinedSupportBaseplateParamsData(
            fundamentals=self.fundamentals.data(),
            baseplate_size=self.baseplate_size.data(),
            baseplate_core=self.baseplate_core.data(),
            click_springs=self.click_springs.data(),
            support=self.support.data(),
        )


class CombinedStackedBaseplatesParams(CombinedParams):
    """Combined parameters for stacked baseplates geometry generation."""

    def __init__(  # noqa: PLR0913
        self,
        baseplate_size: BaseplateSizeParams = None,
        fundamentals: FundamentalsParams = None,
        baseplate_core: BaseplateCoreParams = None,
        click_springs: ClickSpringsParams = None,
        junction_screws: JunctionScrewsParams = None,
        screw_stubs: ScrewStubsParams = None,
        support: SupportParams = None,
        stacking: StackingParams = None,
        connecting_clips: ConnectingClipsParams = None,
    ) -> None:
        """Initialize with all stacked baseplates parameter groups."""
        super().__init__(
            baseplate_size=baseplate_size or BaseplateSizeParams(),
            fundamentals=fundamentals or FundamentalsParams(),
            baseplate_core=baseplate_core or BaseplateCoreParams(),
            click_springs=click_springs or ClickSpringsParams(),
            junction_screws=junction_screws or JunctionScrewsParams(),
            screw_stubs=screw_stubs or ScrewStubsParams(),
            support=support or SupportParams(),
            stacking=stacking or StackingParams(),
            connecting_clips=connecting_clips or ConnectingClipsParams(),
        )

    def validate(self) -> list[ValidationError]:
        """Validate cross-group constraints."""
        errors = CombinedBaseplateParams(
            fundamentals=self.fundamentals,
            baseplate_size=self.baseplate_size,
            baseplate_core=self.baseplate_core,
            click_springs=self.click_springs,
            junction_screws=self.junction_screws,
            connecting_clips=self.connecting_clips,
        ).validate()
        screw_stubs = self.screw_stubs.data()
        junction = self.junction_screws.data()
        if screw_stubs.enabled:
            if not junction.enabled:
                errors.append(
                    ValidationError(
                        message="Screw stubs require junction screws",
                        affected_params=("screw_stubs.enabled",),
                    )
                )
            if not float(screw_stubs.clearance) >= 0:
                errors.append(
                    ValidationError(
                        message="Screw stub clearance must be >= 0",
                        affected_params=("screw_stubs.clearance",),
                    )
                )
            stub_d = float(junction.screw_diameter) - 2 * float(screw_stubs.clearance)
            if not stub_d > 0:
                errors.append(
                    ValidationError(
                        message="Screw stub clearance is too large",
                        affected_params=("screw_stubs.clearance",),
                    )
                )
        return errors

    def data(self) -> CombinedStackedBaseplatesParamsData:
        """Return validated immutable combined data container."""
        return CombinedStackedBaseplatesParamsData(
            fundamentals=self.fundamentals.data(),
            baseplate_size=self.baseplate_size.data(),
            baseplate_core=self.baseplate_core.data(),
            click_springs=self.click_springs.data(),
            junction_screws=self.junction_screws.data(),
            screw_stubs=self.screw_stubs.data(),
            support=self.support.data(),
            stacking=self.stacking.data(),
            connecting_clips=self.connecting_clips.data(),
        )


@dataclass(frozen=True)
class DrawerParamsData:
    """Immutable data container for drawer fitting parameters."""

    drawer_width: fc.Units.Quantity
    drawer_depth: fc.Units.Quantity
    width_filler_alignment: str
    depth_filler_alignment: str
    split_algorithm: str


@dataclass(frozen=True)
class PrinterParamsData:
    """Immutable data container for printer bed parameters."""

    bed_width: fc.Units.Quantity
    bed_depth: fc.Units.Quantity


@dataclass(frozen=True)
class CombinedDrawerBaseplateParamsData:
    """Immutable combined data for drawer baseplate geometry generation."""

    fundamentals: FundamentalsParamsData
    baseplate_size: BaseplateSizeParamsData
    baseplate_core: BaseplateCoreParamsData
    click_springs: ClickSpringsParamsData
    junction_screws: JunctionScrewsParamsData
    connecting_clips: ConnectingClipsParamsData
    drawer: DrawerParamsData
    printer: PrinterParamsData


class DrawerParams(ParameterGroup):
    """Drawer fitting parameters for drawer baseplates.

    Uses MEM default type - values are remembered within the session so
    creating a new drawer baseplate defaults to the last used dimensions.
    """

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
        )


class PrinterParams(ParameterGroup):
    """Printer bed parameters.

    Uses SAVED default type - values persist across sessions.
    """

    _default_type = DefaultType.SAVED

    def __init__(self, **kwargs) -> None:
        """Initialize with printer bed dimensions."""
        parameters = [
            FloatParam(
                "bed_width",
                "Bed Width",
                fc.Units.Quantity("256 mm"),
                positive_only=True,
            ),
            FloatParam(
                "bed_depth",
                "Bed Depth",
                fc.Units.Quantity("240 mm"),
                positive_only=True,
            ),
        ]

        super().__init__(parameters)
        self.set_all_values(kwargs)

    def data(self) -> PrinterParamsData:
        """Return immutable data container."""
        return PrinterParamsData(
            bed_width=self.get_value("bed_width"),
            bed_depth=self.get_value("bed_depth"),
        )


class CombinedDrawerBaseplateParams(CombinedParams):
    """Combined parameters for drawer baseplate geometry generation."""

    def __init__(  # noqa: PLR0913
        self,
        fundamentals: FundamentalsParams = None,
        baseplate_core: BaseplateCoreParams = None,
        click_springs: ClickSpringsParams = None,
        junction_screws: JunctionScrewsParams = None,
        connecting_clips: ConnectingClipsParams = None,
        drawer: DrawerParams = None,
        printer: PrinterParams = None,
    ) -> None:
        """Initialize with all drawer baseplate parameter groups."""
        # Drawer first in UI, then printer, then baseplate options
        super().__init__(
            drawer=drawer or DrawerParams(),
            printer=printer or PrinterParams(),
            fundamentals=fundamentals or FundamentalsParams(),
            baseplate_core=baseplate_core or BaseplateCoreParams(),
            click_springs=click_springs or ClickSpringsParams(),
            junction_screws=junction_screws or JunctionScrewsParams(),
            connecting_clips=connecting_clips or ConnectingClipsParams(),
        )
        # Internal defaults for baseplate_size (not shown in UI - computed from drawer dims)
        self._baseplate_size_defaults = BaseplateSizeParams()

    def validate(self) -> list[ValidationError]:
        """Validate cross-group constraints."""
        errors = CombinedBaseplateParams(
            fundamentals=self.fundamentals,
            baseplate_size=self._baseplate_size_defaults,
            baseplate_core=self.baseplate_core,
            click_springs=self.click_springs,
            junction_screws=self.junction_screws,
            connecting_clips=self.connecting_clips,
        ).validate()
        drawer = self.drawer.data()
        printer = self.printer.data()
        grid_size = float(self.fundamentals.data().grid_size)
        if float(drawer.drawer_width) < grid_size:
            errors.append(
                ValidationError(
                    message=f"Drawer width must be at least {grid_size} mm (grid size)",
                    affected_params=("drawer.drawer_width",),
                )
            )
        if float(drawer.drawer_depth) < grid_size:
            errors.append(
                ValidationError(
                    message=f"Drawer depth must be at least {grid_size} mm (grid size)",
                    affected_params=("drawer.drawer_depth",),
                )
            )
        if float(printer.bed_width) < grid_size:
            errors.append(
                ValidationError(
                    message=f"Printer bed width must be at least {grid_size} mm (grid size)",
                    affected_params=("printer.bed_width",),
                )
            )
        if float(printer.bed_depth) < grid_size:
            errors.append(
                ValidationError(
                    message=f"Printer bed depth must be at least {grid_size} mm (grid size)",
                    affected_params=("printer.bed_depth",),
                )
            )
        return errors

    def baseplate_data(self) -> CombinedBaseplateParamsData:
        """Return baseplate-only data container for builder compatibility."""
        return CombinedBaseplateParamsData(
            fundamentals=self.fundamentals.data(),
            baseplate_size=self._baseplate_size_defaults.data(),
            baseplate_core=self.baseplate_core.data(),
            click_springs=self.click_springs.data(),
            junction_screws=self.junction_screws.data(),
            screw_stubs=ScrewStubsParamsData(enabled=False, clearance=fc.Units.Quantity("0.15 mm")),
            connecting_clips=self.connecting_clips.data(),
        )

    def data(self) -> CombinedDrawerBaseplateParamsData:
        """Return validated immutable combined data container."""
        return CombinedDrawerBaseplateParamsData(
            fundamentals=self.fundamentals.data(),
            baseplate_size=self._baseplate_size_defaults.data(),
            baseplate_core=self.baseplate_core.data(),
            click_springs=self.click_springs.data(),
            junction_screws=self.junction_screws.data(),
            connecting_clips=self.connecting_clips.data(),
            drawer=self.drawer.data(),
            printer=self.printer.data(),
        )


class PluginSettingsParams(ParameterGroup):
    """Plugin-level settings (cache sizes, etc.) - not used for geometry.

    Uses SAVED default type - values persist to FreeCAD preferences and
    survive across sessions. Changed via Edit Defaults UI.
    """

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
