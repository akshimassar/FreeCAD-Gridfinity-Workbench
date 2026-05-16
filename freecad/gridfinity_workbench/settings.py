"""Persisted default settings for Gridfinity workbench."""

from __future__ import annotations

from dataclasses import dataclass

import FreeCAD as fc  # noqa: N813

from . import baseplate_builder


@dataclass
class Defaults:
    prefs_path: str = "User parameter:BaseApp/Preferences/Mod/GridfinityWorkbench"
    grid_size: float = 42.0
    base_profile_main_half_width: float = 2.15
    base_profile_main_height: float = 2.5
    base_profile_lower_chamfer_size: float = 0.7
    baseplate_lower_chamfer_enabled: bool = False
    baseplate_top_crop: float = 0.8
    bin_outer_radius: float = 4.0
    clearance: float = 0.25
    half_grid_size: bool = False

    click_springs_enabled: bool = True
    click_thickness: float = 0.8
    click_length: float = 12.0
    click_offset: float = 0.55

    junction_screw_holes: bool = True
    junction_screw_diameter: float = 3.3
    junction_counterbore_diameter: float = 6.0
    junction_counterbore_depth: float = 1.5

    clip_cutouts_enabled: bool = True
    clip_length: float = 3.0
    baseplate_cache_size: int = 32

    def load(self) -> None:
        prefs = fc.ParamGet(self.prefs_path)
        self.grid_size = prefs.GetFloat("GridSize", self.grid_size)
        self.base_profile_main_half_width = prefs.GetFloat(
            "BaseProfileMainHalfWidth",
            self.base_profile_main_half_width,
        )
        self.base_profile_main_height = prefs.GetFloat(
            "BaseProfileMainHeight",
            self.base_profile_main_height,
        )
        self.base_profile_lower_chamfer_size = prefs.GetFloat(
            "BaseProfileLowerChamferSize",
            self.base_profile_lower_chamfer_size,
        )
        self.baseplate_lower_chamfer_enabled = prefs.GetBool(
            "BaseplateLowerChamferEnabled",
            self.baseplate_lower_chamfer_enabled,
        )
        self.baseplate_top_crop = prefs.GetFloat("BaseplateTopCrop", self.baseplate_top_crop)
        self.bin_outer_radius = prefs.GetFloat("BinOuterRadius", self.bin_outer_radius)
        self.clearance = prefs.GetFloat("Clearance", self.clearance)
        self.half_grid_size = prefs.GetBool("HalfGridSize", self.half_grid_size)

        self.click_springs_enabled = prefs.GetBool(
            "ClickSpringsEnabled", self.click_springs_enabled
        )
        self.click_thickness = prefs.GetFloat("ClickThickness", self.click_thickness)
        self.click_length = prefs.GetFloat("ClickLength", self.click_length)
        self.click_offset = prefs.GetFloat("ClickOffset", self.click_offset)

        self.junction_screw_holes = prefs.GetBool("JunctionScrewHoles", self.junction_screw_holes)
        self.junction_screw_diameter = prefs.GetFloat(
            "JunctionScrewDiameter",
            self.junction_screw_diameter,
        )
        self.junction_counterbore_diameter = prefs.GetFloat(
            "JunctionCounterboreDiameter",
            self.junction_counterbore_diameter,
        )
        self.junction_counterbore_depth = prefs.GetFloat(
            "JunctionCounterboreDepth",
            self.junction_counterbore_depth,
        )

        self.clip_cutouts_enabled = prefs.GetBool("ClipCutoutsEnabled", self.clip_cutouts_enabled)
        self.clip_length = prefs.GetFloat("ClipLength", self.clip_length)
        self.baseplate_cache_size = prefs.GetInt("BaseplateCacheSize", self.baseplate_cache_size)
        baseplate_builder.set_baseplate_shape_cache_max_entries(self.baseplate_cache_size)

    def save(self) -> None:
        prefs = fc.ParamGet(self.prefs_path)
        prefs.SetFloat("GridSize", self.grid_size)
        prefs.SetFloat("BaseProfileMainHalfWidth", self.base_profile_main_half_width)
        prefs.SetFloat("BaseProfileMainHeight", self.base_profile_main_height)
        prefs.SetFloat("BaseProfileLowerChamferSize", self.base_profile_lower_chamfer_size)
        prefs.SetBool("BaseplateLowerChamferEnabled", self.baseplate_lower_chamfer_enabled)
        prefs.SetFloat("BaseplateTopCrop", self.baseplate_top_crop)
        prefs.SetFloat("BinOuterRadius", self.bin_outer_radius)
        prefs.SetFloat("Clearance", self.clearance)
        prefs.SetBool("HalfGridSize", self.half_grid_size)

        prefs.SetBool("ClickSpringsEnabled", self.click_springs_enabled)
        prefs.SetFloat("ClickThickness", self.click_thickness)
        prefs.SetFloat("ClickLength", self.click_length)
        prefs.SetFloat("ClickOffset", self.click_offset)

        prefs.SetBool("JunctionScrewHoles", self.junction_screw_holes)
        prefs.SetFloat("JunctionScrewDiameter", self.junction_screw_diameter)
        prefs.SetFloat("JunctionCounterboreDiameter", self.junction_counterbore_diameter)
        prefs.SetFloat("JunctionCounterboreDepth", self.junction_counterbore_depth)

        prefs.SetBool("ClipCutoutsEnabled", self.clip_cutouts_enabled)
        prefs.SetFloat("ClipLength", self.clip_length)
        prefs.SetInt("BaseplateCacheSize", int(self.baseplate_cache_size))
        baseplate_builder.set_baseplate_shape_cache_max_entries(self.baseplate_cache_size)


factory_defaults = Defaults()

defaults = Defaults()
defaults.load()
