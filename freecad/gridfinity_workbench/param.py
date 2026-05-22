"""Concrete parameter groups and data containers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import FreeCAD as fc  # noqa: N813

from .param_system import (
    BooleanParam,
    CombinedParams,
    DefaultType,
    FloatParam,
    IntParam,
    ParameterGroup,
    ParameterValidationError,
)


@dataclass(frozen=True)
class FundamentalsParamsData:
    grid_size: fc.Units.Quantity
    outer_radius: fc.Units.Quantity
    main_profile_half_width: fc.Units.Quantity
    main_profile_height: fc.Units.Quantity


@dataclass(frozen=True)
class ClipParamsData:
    enabled: bool
    tolerance: fc.Units.Quantity
    clip_length: fc.Units.Quantity


@dataclass(frozen=True)
class CombinedClipParamsData:
    fundamentals: FundamentalsParamsData
    clip: ClipParamsData


class FundamentalsParams(ParameterGroup):
    _category = "Gridfinity_Fundamentals"

    def __init__(self, **kwargs):
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
        errors = self.validate()
        if errors:
            raise ParameterValidationError(errors)
        return FundamentalsParamsData(
            grid_size=self.get_value("grid_size"),
            outer_radius=self.get_value("outer_radius"),
            main_profile_half_width=self.get_value("main_half_width"),
            main_profile_height=self.get_value("main_height"),
        )


class ClipParams(ParameterGroup):
    _category = "Gridfinity_Clip"

    def __init__(self, **kwargs):
        parameters = [
            BooleanParam("enabled", "Enabled", default_value=True),
            FloatParam("tolerance", "Tolerance", fc.Units.Quantity("0.15 mm")),
            FloatParam("clip_length", "Clip Length", fc.Units.Quantity("3.0 mm")),
        ]

        super().__init__(parameters)
        self.set_all_values(kwargs)

    def data(self) -> ClipParamsData:
        errors = self.validate()
        if errors:
            raise ParameterValidationError(errors)
        return ClipParamsData(
            enabled=self.get_value("enabled"),
            tolerance=self.get_value("tolerance"),
            clip_length=self.get_value("clip_length"),
        )


class CombinedClipParams(CombinedParams):
    def __init__(
        self,
        fundamentals: FundamentalsParams = None,
        clip: ClipParams = None,
    ):
        super().__init__(
            fundamentals=fundamentals or FundamentalsParams(),
            clip=clip or ClipParams(),
        )

    def validate(self) -> Dict[str, str]:
        errors = super().validate()
        try:
            tolerance_val = float(self.clip.get_value("tolerance"))
            clip_length_val = float(self.clip.get_value("clip_length"))
            if clip_length_val <= 2 * tolerance_val:
                errors["clip.clip_length"] = (
                    f"Clip length ({clip_length_val}) must be greater than 2 * tolerance ({2 * tolerance_val})"
                )
        except (AttributeError, KeyError, TypeError, ValueError):
            pass
        return errors

    def data(self) -> CombinedClipParamsData:
        errors = self.validate()
        if errors:
            raise ParameterValidationError(errors)
        return CombinedClipParamsData(
            fundamentals=self.fundamentals.data(),
            clip=self.clip.data(),
        )


class BaseplateSizeParams(ParameterGroup):
    _category = "Gridfinity_BaseplateSize"

    def __init__(self, **kwargs):
        parameters = [
            IntParam(
                "x_grid_count",
                "X Grid Count",
                2,
                positive_only=True,
                default_type=DefaultType.MEM,
            ),
            IntParam(
                "y_grid_count",
                "Y Grid Count",
                2,
                positive_only=True,
                default_type=DefaultType.MEM,
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


class BaseplateCoreParams(ParameterGroup):
    _category = "Gridfinity_Core"

    def __init__(self, **kwargs):
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
            FloatParam(
                "clearance",
                "Clearance",
                fc.Units.Quantity("0.25 mm"),
            ),
        ]

        super().__init__(parameters)
        self.set_all_values(kwargs)


class ClickSpringParams(ParameterGroup):
    _category = "Gridfinity_ClickSpring"

    def __init__(self, **kwargs):
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


class JunctionScrewParams(ParameterGroup):
    _category = "Gridfinity_JunctionScrew"

    def __init__(self, **kwargs):
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


class ScrewStubParams(ParameterGroup):
    _category = "Gridfinity_ScrewStub"

    def __init__(self, **kwargs):
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


class SupportParams(ParameterGroup):
    _category = "Gridfinity_Support"

    def __init__(self, **kwargs):
        parameters = [
            FloatParam(
                "overhang_angle",
                "Overhang Angle",
                fc.Units.Quantity("45.0 mm"),
            ),
        ]

        super().__init__(parameters)
        self.set_all_values(kwargs)


class CombinedBaseplateParams(CombinedParams):
    def __init__(
        self,
        fundamentals: FundamentalsParams = None,
        size: BaseplateSizeParams = None,
        core: BaseplateCoreParams = None,
        click_springs: ClickSpringParams = None,
        junction_screws: JunctionScrewParams = None,
        clip_cutouts: ClipParams = None,
    ):
        super().__init__(
            fundamentals=fundamentals or FundamentalsParams(),
            size=size or BaseplateSizeParams(),
            core=core or BaseplateCoreParams(),
            click_springs=click_springs or ClickSpringParams(),
            junction_screws=junction_screws or JunctionScrewParams(),
            clip_cutouts=clip_cutouts or ClipParams(),
        )


class CombinedStackedBaseplateParams(CombinedParams):
    def __init__(
        self,
        fundamentals: FundamentalsParams = None,
        size: BaseplateSizeParams = None,
        core: BaseplateCoreParams = None,
        click_springs: ClickSpringParams = None,
        junction_screws: JunctionScrewParams = None,
        screw_stubs: ScrewStubParams = None,
        support: SupportParams = None,
        clip_cutouts: ClipParams = None,
    ):
        super().__init__(
            fundamentals=fundamentals or FundamentalsParams(),
            size=size or BaseplateSizeParams(),
            core=core or BaseplateCoreParams(),
            click_springs=click_springs or ClickSpringParams(),
            junction_screws=junction_screws or JunctionScrewParams(),
            screw_stubs=screw_stubs or ScrewStubParams(),
            support=support or SupportParams(),
            clip_cutouts=clip_cutouts or ClipParams(),
        )
