"""Parameter snapshots and adapters for simple baseplate workflows."""

from __future__ import annotations

from dataclasses import dataclass

import FreeCAD as fc  # noqa: N813


@dataclass
class BaseplateParams:
    x_grid_units: float
    y_grid_units: float
    grid_size: float
    base_profile_main_half_width: float
    base_profile_main_height: float
    bin_outer_radius: float
    base_profile_lower_chamfer_enabled: bool
    base_profile_lower_chamfer_size: float
    base_profile_top_crop: float
    clearance: float
    click_springs_enabled: bool
    click_thickness: float
    click_length: float
    click_offset: float
    junction_screw_holes: bool
    junction_screw_diameter: float
    junction_counterbore_diameter: float
    junction_counterbore_depth: float
    clip_cutouts_enabled: bool
    clip_length: float


def params_from_obj(obj: fc.DocumentObject) -> BaseplateParams:
    return BaseplateParams(
        x_grid_units=float(obj.xGridUnits),
        y_grid_units=float(obj.yGridUnits),
        grid_size=float(obj.xGridSize.Value),
        base_profile_main_half_width=float(obj.BaseProfileMainHalfWidth.Value),
        base_profile_main_height=float(obj.BaseProfileMainHeight.Value),
        bin_outer_radius=float(obj.BinOuterRadius.Value),
        base_profile_lower_chamfer_enabled=bool(obj.BaseProfileLowerChamferEnabled),
        base_profile_lower_chamfer_size=float(obj.BaseProfileLowerChamferSize.Value),
        base_profile_top_crop=float(obj.BaseProfileTopCrop.Value),
        clearance=float(obj.Clearance.Value),
        click_springs_enabled=bool(obj.ClickSpringsEnabled),
        click_thickness=float(obj.ClickThickness.Value),
        click_length=float(obj.ClickLength.Value),
        click_offset=float(obj.ClickOffset.Value),
        junction_screw_holes=bool(obj.JunctionScrewHoles),
        junction_screw_diameter=float(obj.JunctionScrewDiameter.Value),
        junction_counterbore_diameter=float(obj.JunctionCounterboreDiameter.Value),
        junction_counterbore_depth=float(obj.JunctionCounterboreDepth.Value),
        clip_cutouts_enabled=bool(obj.ClipCutoutsEnabled),
        clip_length=float(obj.ClipLength.Value),
    )


def apply_params_to_obj(obj: fc.DocumentObject, params: BaseplateParams) -> None:
    obj.xGridUnits = params.x_grid_units
    obj.yGridUnits = params.y_grid_units
    obj.xGridSize = params.grid_size
    obj.yGridSize = params.grid_size
    obj.BaseProfileMainHalfWidth = params.base_profile_main_half_width
    obj.BaseProfileMainHeight = params.base_profile_main_height
    obj.BinOuterRadius = params.bin_outer_radius
    obj.BaseProfileLowerChamferEnabled = params.base_profile_lower_chamfer_enabled
    obj.BaseProfileLowerChamferSize = params.base_profile_lower_chamfer_size
    obj.BaseProfileTopCrop = params.base_profile_top_crop
    obj.Clearance = params.clearance
    obj.ClickSpringsEnabled = params.click_springs_enabled
    obj.ClickThickness = params.click_thickness
    obj.ClickLength = params.click_length
    obj.ClickOffset = params.click_offset
    obj.JunctionScrewHoles = params.junction_screw_holes
    obj.JunctionScrewDiameter = params.junction_screw_diameter
    obj.JunctionCounterboreDiameter = params.junction_counterbore_diameter
    obj.JunctionCounterboreDepth = params.junction_counterbore_depth
    obj.ClipCutoutsEnabled = params.clip_cutouts_enabled
    obj.ClipLength = params.clip_length
