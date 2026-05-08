"""Batch STEP export helpers for Gridfinity baseplates."""

from __future__ import annotations

from pathlib import Path

import FreeCAD as fc  # noqa: N813
import Part

from . import features, utils


def export_rect_baseplates_step(
    output_root: str = "/tmp/gridfinity-clickbase-printable",
    *,
    x_max: int = 5,
    y_max: int = 6,
) -> list[str]:
    """Export unique rectangular baseplates as STEP files.

    The export keeps only one orientation of each rectangle (x <= y), so 2x1 is skipped
    because 1x2 is already exported.
    """
    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        fc.Console.PrintMessage(msg + "\n")

    previous_doc = fc.ActiveDocument
    doc = fc.newDocument("GridfinityBatchExport")
    exported: list[str] = []

    log(f"[gridfinity-export] Output root: {out_root}")

    try:
        for x_units in range(1, x_max + 1):
            subdir = out_root / f"{x_units}-by-N"
            subdir.mkdir(parents=True, exist_ok=True)

            for y_units in range(x_units, y_max + 1):
                obj = utils.new_object("Baseplate")
                features.Baseplate(obj)
                obj.xGridUnits = x_units
                obj.yGridUnits = y_units

                doc.recompute()

                file_path = subdir / f"baseplate-CP-{x_units}x{y_units}.step"
                Part.export([obj], str(file_path))
                exported.append(str(file_path))
                log(f"[gridfinity-export] Exported {x_units}x{y_units} -> {file_path}")

                doc.removeObject(obj.Name)
                doc.recompute()
    finally:
        fc.closeDocument(doc.Name)
        if previous_doc is not None:
            fc.setActiveDocument(previous_doc.Name)

    log(f"[gridfinity-export] Done. Exported {len(exported)} files.")

    return exported
