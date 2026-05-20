"""Parameter snapshots and adapters for simple baseplate workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import FreeCAD as fc  # noqa: N813

unitmm = fc.Units.Quantity("1 mm")


@dataclass(frozen=True)
class FundamentalsParams:
    x_grid_size: fc.Units.Quantity
    y_grid_size: fc.Units.Quantity
    bin_outer_radius: fc.Units.Quantity
    base_profile_main_half_width: fc.Units.Quantity
    base_profile_main_height: fc.Units.Quantity


@dataclass(frozen=True)
class BaseplateCoreParams:
    x_grid_count: int
    y_grid_count: int
    base_profile_lower_chamfer_enabled: bool
    base_profile_lower_chamfer_size: fc.Units.Quantity
    base_profile_top_crop: fc.Units.Quantity
    clearance: fc.Units.Quantity


@dataclass(frozen=True)
class BaseplateFillersParams:
    right_enabled: bool
    right_width: fc.Units.Quantity
    left_enabled: bool
    left_width: fc.Units.Quantity
    top_enabled: bool
    top_width: fc.Units.Quantity
    bottom_enabled: bool
    bottom_width: fc.Units.Quantity


@dataclass(frozen=True)
class ClickSpringParams:
    enabled: bool
    click_thickness: fc.Units.Quantity
    click_length: fc.Units.Quantity
    click_offset: fc.Units.Quantity


@dataclass(frozen=True)
class JunctionScrewParams:
    enabled: bool
    screw_diameter: fc.Units.Quantity
    counterbore_diameter: fc.Units.Quantity
    counterbore_depth: fc.Units.Quantity


@dataclass(frozen=True)
class ScrewStubParams:
    enabled: bool
    clearance: fc.Units.Quantity


@dataclass(frozen=True)
class ClipCutoutParams:
    enabled: bool
    clip_length: fc.Units.Quantity


@dataclass(frozen=True)
class BaseplateParams:
    fundamentals: FundamentalsParams
    core: BaseplateCoreParams
    fillers: BaseplateFillersParams
    click_springs: ClickSpringParams
    junction_screws: JunctionScrewParams
    screw_stubs: ScrewStubParams
    clip_cutouts: ClipCutoutParams


@dataclass(frozen=True)
class DialogValidationResult:
    params: BaseplateParams | None
    errors: dict[str, str]

    @property
    def is_valid(self) -> bool:
        return not self.errors and self.params is not None


def _q_mm(value: float) -> fc.Units.Quantity:
    return value * unitmm


def _fmt_mm(value: float) -> str:
    return f"{value:.2f} mm"


def _params_from_controls(data: dict[str, Any], *, preview_mode: bool) -> BaseplateParams:
    grid_size = _q_mm(float(data["grid_size"]))
    x_grid_count = int(data["x_grid_units"])
    y_grid_count = int(data["y_grid_units"])
    click_enabled = bool(data["click_springs_enabled"])
    junction_enabled = bool(data["junction_screw_holes"]) and not preview_mode
    clip_enabled = bool(data["clip_cutouts_enabled"]) and not preview_mode
    fillers = BaseplateFillersParams(
        right_enabled=bool(data["filler_right_enabled"]),
        right_width=_q_mm(float(data["filler_right_width"])),
        left_enabled=bool(data["filler_left_enabled"]),
        left_width=_q_mm(float(data["filler_left_width"])),
        top_enabled=bool(data["filler_top_enabled"]),
        top_width=_q_mm(float(data["filler_top_width"])),
        bottom_enabled=bool(data["filler_bottom_enabled"]),
        bottom_width=_q_mm(float(data["filler_bottom_width"])),
    )
    return BaseplateParams(
        fundamentals=FundamentalsParams(
            x_grid_size=grid_size,
            y_grid_size=grid_size,
            bin_outer_radius=_q_mm(float(data["bin_outer_radius"])),
            base_profile_main_half_width=_q_mm(float(data["base_profile_main_half_width"])),
            base_profile_main_height=_q_mm(float(data["base_profile_main_height"])),
        ),
        core=BaseplateCoreParams(
            x_grid_count=x_grid_count,
            y_grid_count=y_grid_count,
            base_profile_lower_chamfer_enabled=bool(data["enable_lower_chamfer"]),
            base_profile_lower_chamfer_size=_q_mm(float(data["base_profile_lower_chamfer_size"])),
            base_profile_top_crop=_q_mm(float(data["top_crop"])),
            clearance=_q_mm(float(data["clearance"])),
        ),
        fillers=fillers,
        click_springs=ClickSpringParams(
            enabled=click_enabled and not preview_mode,
            click_thickness=_q_mm(float(data["click_thickness"])),
            click_length=_q_mm(float(data["click_length"])),
            click_offset=_q_mm(float(data["click_offset"])),
        ),
        junction_screws=JunctionScrewParams(
            enabled=junction_enabled,
            screw_diameter=_q_mm(float(data["junction_screw_diameter"])),
            counterbore_diameter=_q_mm(float(data["junction_counterbore_diameter"])),
            counterbore_depth=_q_mm(float(data["junction_counterbore_depth"])),
        ),
        screw_stubs=ScrewStubParams(
            enabled=bool(data.get("screw_stubs_enabled", False)) and not preview_mode,
            clearance=_q_mm(float(data.get("screw_stub_clearance", 0.15))),
        ),
        clip_cutouts=ClipCutoutParams(
            enabled=clip_enabled,
            clip_length=_q_mm(float(data["clip_length"])),
        ),
    )


def params_from_dialog(data: dict[str, Any], *, preview_mode: bool) -> DialogValidationResult:
    params = _params_from_controls(data, preview_mode=preview_mode)
    errors: dict[str, str] = {}

    def add_error(key: str, message: str) -> None:
        if key not in errors:
            errors[key] = message
            return
        errors[key] = min(errors[key], message)

    half_width = float(params.fundamentals.base_profile_main_half_width)
    outer_radius = float(params.fundamentals.bin_outer_radius)
    top_crop = float(params.core.base_profile_top_crop)
    if not top_crop < half_width:
        add_error(
            "top_crop",
            f"BaseProfileTopCrop must be less than BaseProfileMainHalfWidth ({_fmt_mm(half_width)})",
        )
    if not outer_radius > half_width:
        add_error(
            "bin_outer_radius",
            f"BinOuterRadius must be greater than BaseProfileMainHalfWidth ({_fmt_mm(half_width)})",
        )

    if params.click_springs.enabled:
        click_thickness = float(params.click_springs.click_thickness)
        if not click_thickness < half_width:
            add_error(
                "click_thickness",
                f"ClickThickness must be less than BaseProfileMainHalfWidth ({_fmt_mm(half_width)})",
            )

        bin_vertical_radius = float(params.fundamentals.bin_outer_radius) - half_width
        x_limit = float(params.fundamentals.x_grid_size) / 4 - bin_vertical_radius
        y_limit = float(params.fundamentals.y_grid_size) / 4 - bin_vertical_radius
        max_half = min(x_limit, y_limit)
        half_len = float(params.click_springs.click_length) / 2
        if not half_len < max_half:
            add_error(
                "click_length",
                "ClickLength/2 must be less than min(xGridSize, yGridSize)/4 - "
                f"(BinOuterRadius - BaseProfileMainHalfWidth) (max half-length {_fmt_mm(max_half)})",
            )

    if params.junction_screws.enabled:
        screw_d = float(params.junction_screws.screw_diameter)
        counterbore_d = float(params.junction_screws.counterbore_diameter)
        counterbore_depth = float(params.junction_screws.counterbore_depth)
        if not screw_d > 0:
            add_error(
                "junction_screw_diameter",
                f"JunctionScrewDiameter must be greater than {_fmt_mm(0)}",
            )
        if not counterbore_d > 0:
            add_error(
                "junction_counterbore_diameter",
                f"JunctionCounterboreDiameter must be greater than {_fmt_mm(0)}",
            )
        if not counterbore_depth > 0:
            add_error(
                "junction_counterbore_depth",
                f"JunctionCounterboreDepth must be greater than {_fmt_mm(0)}",
            )
        if not counterbore_d > screw_d:
            add_error(
                "junction_counterbore_diameter",
                f"JunctionCounterboreDiameter must be greater than JunctionScrewDiameter ({_fmt_mm(screw_d)})",
            )

    if params.clip_cutouts.enabled:
        clip_length = float(params.clip_cutouts.clip_length)
        max_clip = 2 * float(params.fundamentals.base_profile_main_half_width)
        if not clip_length > 0:
            add_error("clip_length", f"ClipLength must be greater than {_fmt_mm(0)}")
        if not clip_length < max_clip:
            add_error(
                "clip_length",
                f"ClipLength must be less than 2*BaseProfileMainHalfWidth ({_fmt_mm(max_clip)})",
            )

    if params.screw_stubs.enabled:
        if not params.junction_screws.enabled:
            add_error("screw_stubs_enabled", "Screw stubs require Junction screws to be enabled")
        stub_d = float(params.junction_screws.screw_diameter) - 2 * float(
            params.screw_stubs.clearance
        )
        if not float(params.screw_stubs.clearance) >= 0:
            add_error(
                "screw_stub_clearance",
                f"ScrewStubClearance must be greater than or equal to {_fmt_mm(0)}",
            )
        if not stub_d > 0:
            add_error(
                "screw_stub_clearance", "ScrewStubClearance is too large for JunctionScrewDiameter"
            )

    x_grid_size = float(params.fundamentals.x_grid_size)
    y_grid_size = float(params.fundamentals.y_grid_size)
    x_units = int(params.core.x_grid_count)
    y_units = int(params.core.y_grid_count)

    left_present = params.fillers.left_enabled and float(params.fillers.left_width) > 0
    right_present = params.fillers.right_enabled and float(params.fillers.right_width) > 0
    top_present = params.fillers.top_enabled and float(params.fillers.top_width) > 0
    bottom_present = params.fillers.bottom_enabled and float(params.fillers.bottom_width) > 0

    if x_units == 0 and not (left_present or right_present):
        add_error("x_grid_units", "X grid units = 0 requires Left or Right filler")
    if y_units == 0 and not (top_present or bottom_present):
        add_error("y_grid_units", "Y grid units = 0 requires Top or Bottom filler")
    if x_units == 0 and y_units == 0:
        add_error("x_grid_units", "X and Y grid units cannot both be 0")
        add_error("y_grid_units", "X and Y grid units cannot both be 0")

    filler_checks = [
        (
            params.fillers.left_enabled,
            float(params.fillers.left_width),
            x_grid_size,
            "filler_left_width",
        ),
        (
            params.fillers.right_enabled,
            float(params.fillers.right_width),
            x_grid_size,
            "filler_right_width",
        ),
        (
            params.fillers.top_enabled,
            float(params.fillers.top_width),
            y_grid_size,
            "filler_top_width",
        ),
        (
            params.fillers.bottom_enabled,
            float(params.fillers.bottom_width),
            y_grid_size,
            "filler_bottom_width",
        ),
    ]
    for enabled, width, max_grid, key in filler_checks:
        if not enabled:
            continue
        if not (0 < width < max_grid):
            axis_name = (
                "xGridSize" if key in {"filler_left_width", "filler_right_width"} else "yGridSize"
            )
            field_name = {
                "filler_left_width": "FillerLeftWidth",
                "filler_right_width": "FillerRightWidth",
                "filler_top_width": "FillerTopWidth",
                "filler_bottom_width": "FillerBottomWidth",
            }[key]
            add_error(
                key,
                f"{field_name} must be > {_fmt_mm(0)} and < {axis_name} ({_fmt_mm(max_grid)})",
            )

    radius = float(params.fundamentals.bin_outer_radius)
    two_radius = 2 * radius

    if params.fillers.left_enabled:
        left_w = float(params.fillers.left_width)
        if x_units == 0 and not left_w > two_radius:
            add_error(
                "filler_left_width",
                f"With xGridUnits=0, FillerLeftWidth must be greater than 2*BinOuterRadius ({_fmt_mm(two_radius)})",
            )

    if params.fillers.right_enabled:
        right_w = float(params.fillers.right_width)
        if x_units == 0 and not right_w > two_radius:
            add_error(
                "filler_right_width",
                f"With xGridUnits=0, FillerRightWidth must be greater than 2*BinOuterRadius ({_fmt_mm(two_radius)})",
            )

    if params.fillers.top_enabled:
        top_w = float(params.fillers.top_width)
        if y_units == 0 and not top_w > two_radius:
            add_error(
                "filler_top_width",
                f"With yGridUnits=0, FillerTopWidth must be greater than 2*BinOuterRadius ({_fmt_mm(two_radius)})",
            )

    if params.fillers.bottom_enabled:
        bottom_w = float(params.fillers.bottom_width)
        if y_units == 0 and not bottom_w > two_radius:
            add_error(
                "filler_bottom_width",
                f"With yGridUnits=0, FillerBottomWidth must be greater than 2*BinOuterRadius ({_fmt_mm(two_radius)})",
            )

    if errors:
        return DialogValidationResult(params=None, errors=errors)
    return DialogValidationResult(params=params, errors={})


def params_from_obj(obj: fc.DocumentObject) -> BaseplateParams:
    x_grid_size = obj.xGridSize
    y_grid_size = obj.yGridSize
    x_grid_count = int(getattr(obj, "xGridUnits", 1))
    y_grid_count = int(getattr(obj, "yGridUnits", 1))

    zero_x = 0 * x_grid_size
    zero_y = 0 * y_grid_size
    return BaseplateParams(
        fundamentals=FundamentalsParams(
            x_grid_size=x_grid_size,
            y_grid_size=y_grid_size,
            bin_outer_radius=obj.BinOuterRadius,
            base_profile_main_half_width=obj.BaseProfileMainHalfWidth,
            base_profile_main_height=obj.BaseProfileMainHeight,
        ),
        core=BaseplateCoreParams(
            x_grid_count=x_grid_count,
            y_grid_count=y_grid_count,
            base_profile_lower_chamfer_enabled=bool(
                getattr(obj, "BaseProfileLowerChamferEnabled", False)
            ),
            base_profile_lower_chamfer_size=getattr(obj, "BaseProfileLowerChamferSize", zero_x),
            base_profile_top_crop=obj.BaseProfileTopCrop,
            clearance=getattr(obj, "Clearance", zero_x),
        ),
        fillers=BaseplateFillersParams(
            right_enabled=bool(getattr(obj, "FillerRightEnabled", False)),
            right_width=getattr(obj, "FillerRightWidth", zero_x),
            left_enabled=bool(getattr(obj, "FillerLeftEnabled", False)),
            left_width=getattr(obj, "FillerLeftWidth", zero_x),
            top_enabled=bool(getattr(obj, "FillerTopEnabled", False)),
            top_width=getattr(obj, "FillerTopWidth", zero_y),
            bottom_enabled=bool(getattr(obj, "FillerBottomEnabled", False)),
            bottom_width=getattr(obj, "FillerBottomWidth", zero_y),
        ),
        click_springs=ClickSpringParams(
            enabled=bool(getattr(obj, "ClickSpringsEnabled", False)),
            click_thickness=getattr(obj, "ClickThickness", zero_x),
            click_length=getattr(obj, "ClickLength", zero_x),
            click_offset=getattr(obj, "ClickOffset", zero_x),
        ),
        junction_screws=JunctionScrewParams(
            enabled=bool(getattr(obj, "JunctionScrewHoles", False)),
            screw_diameter=getattr(obj, "JunctionScrewDiameter", zero_x),
            counterbore_diameter=getattr(obj, "JunctionCounterboreDiameter", zero_x),
            counterbore_depth=getattr(obj, "JunctionCounterboreDepth", zero_x),
        ),
        screw_stubs=ScrewStubParams(
            enabled=bool(getattr(obj, "ScrewStubsEnabled", False)),
            clearance=getattr(obj, "ScrewStubClearance", zero_x),
        ),
        clip_cutouts=ClipCutoutParams(
            enabled=bool(getattr(obj, "ClipCutoutsEnabled", False)),
            clip_length=getattr(obj, "ClipLength", zero_x),
        ),
    )


def apply_params_to_obj(obj: fc.DocumentObject, params: BaseplateParams) -> None:
    obj.xGridUnits = params.core.x_grid_count
    obj.yGridUnits = params.core.y_grid_count
    obj.xGridSize = params.fundamentals.x_grid_size
    obj.yGridSize = params.fundamentals.y_grid_size
    obj.BaseProfileMainHalfWidth = params.fundamentals.base_profile_main_half_width
    obj.BaseProfileMainHeight = params.fundamentals.base_profile_main_height
    obj.BinOuterRadius = params.fundamentals.bin_outer_radius
    obj.BaseProfileLowerChamferEnabled = params.core.base_profile_lower_chamfer_enabled
    obj.BaseProfileLowerChamferSize = params.core.base_profile_lower_chamfer_size
    obj.BaseProfileTopCrop = params.core.base_profile_top_crop
    obj.Clearance = params.core.clearance

    obj.ClickSpringsEnabled = params.click_springs.enabled
    obj.ClickThickness = params.click_springs.click_thickness
    obj.ClickLength = params.click_springs.click_length
    obj.ClickOffset = params.click_springs.click_offset

    obj.JunctionScrewHoles = params.junction_screws.enabled
    obj.JunctionScrewDiameter = params.junction_screws.screw_diameter
    obj.JunctionCounterboreDiameter = params.junction_screws.counterbore_diameter
    obj.JunctionCounterboreDepth = params.junction_screws.counterbore_depth
    obj.ScrewStubsEnabled = params.screw_stubs.enabled
    obj.ScrewStubClearance = params.screw_stubs.clearance

    obj.ClipCutoutsEnabled = params.clip_cutouts.enabled
    obj.ClipLength = params.clip_cutouts.clip_length

    obj.FillerRightEnabled = params.fillers.right_enabled
    obj.FillerRightWidth = params.fillers.right_width
    obj.FillerLeftEnabled = params.fillers.left_enabled
    obj.FillerLeftWidth = params.fillers.left_width
    obj.FillerTopEnabled = params.fillers.top_enabled
    obj.FillerTopWidth = params.fillers.top_width
    obj.FillerBottomEnabled = params.fillers.bottom_enabled
    obj.FillerBottomWidth = params.fillers.bottom_width
