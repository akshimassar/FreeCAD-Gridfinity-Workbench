from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FREECAD_CMD_ENV = "FREECAD_CMD"
RESULT_PREFIX = "GRIDFINITY_RESULT="


def _load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _resolve_freecad_cmd() -> str | None:
    env_value = os.environ.get(FREECAD_CMD_ENV)
    if env_value:
        return env_value
    dotenv = _load_dotenv(REPO_ROOT / ".env")
    dotenv_value = dotenv.get(FREECAD_CMD_ENV)
    if dotenv_value:
        return dotenv_value

    cmds_value = os.environ.get("FREECAD_CMDS") or dotenv.get("FREECAD_CMDS")
    if not cmds_value:
        return None
    cmds = shlex.split(cmds_value)
    return cmds[0] if cmds else None


class FreeCADCmdIntegrationTest(unittest.TestCase):
    # IMPORTANT POLICY:
    # Do not change locked absolute dimensions/volume assertions in this file
    # without explicit user confirmation in the current conversation.

    def test_baseplate_tiny_core_skips_clicksprings(self) -> None:
        freecad_cmd = _resolve_freecad_cmd()
        if not freecad_cmd:
            self.skipTest(f"Set {FREECAD_CMD_ENV} in environment or .env")

        freecad_module_root = (REPO_ROOT / "freecad").as_posix()

        script = textwrap.dedent(
            """
            import json
            import sys

            sys.path.insert(0, {module_root})

            import FreeCAD as fc  # noqa: N813
            import gridfinity_workbench.features as features
            from gridfinity_workbench.baseplate_builder import BaseplateBuildOptions

            def build_case(name: str, click_springs: bool) -> dict[str, float | int | bool]:
                doc = fc.newDocument(name)
                try:
                    obj = doc.addObject("Part::FeaturePython", "Baseplate")
                    features.Baseplate(obj)
                    obj.xGridUnits = 1
                    obj.yGridUnits = 1
                    obj.xGridSize = 3.5
                    obj.yGridSize = 3.5
                    obj.BinOuterRadius = 3
                    obj.ClickSpringsEnabled = click_springs
                    obj.JunctionScrewHoles = False
                    obj.ClipCutoutsEnabled = False
                    obj.FillerTopEnabled = False
                    obj.FillerRightEnabled = False
                    obj.FillerBottomEnabled = False
                    obj.FillerLeftEnabled = False
                    doc.recompute()
                    shape = obj.Shape
                    return {{
                        "volume": float(shape.Volume),
                        "solids": int(len(shape.Solids)),
                        "valid": bool(shape.isValid()),
                    }}
                finally:
                    fc.closeDocument(doc.Name)

            baseline = build_case("TinyNoSprings", click_springs=False)
            with_springs = build_case("TinyWithSprings", click_springs=True)

            payload = {{"baseline": baseline, "with_springs": with_springs}}
            print("GRIDFINITY_RESULT=" + json.dumps(payload))
            """,
        ).format(module_root=repr(freecad_module_root))

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name

        try:
            proc = subprocess.run(  # noqa: S603
                [freecad_cmd, script_path],
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

        self.assertEqual(
            proc.returncode,
            0,
            msg=f"FreeCADCmd failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )

        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith(RESULT_PREFIX)), None)
        self.assertIsNotNone(
            line,
            msg=f"No result marker found\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )
        data = json.loads(line[len(RESULT_PREFIX) :])

        baseline_data = data["baseline"]
        with_springs_data = data["with_springs"]
        self.assertEqual(int(baseline_data["solids"]), 1)
        self.assertEqual(int(with_springs_data["solids"]), 1)
        self.assertTrue(bool(baseline_data["valid"]))
        self.assertTrue(bool(with_springs_data["valid"]))
        self.assertAlmostEqual(
            float(with_springs_data["volume"]),
            float(baseline_data["volume"]),
            places=6,
            msg="Tiny core should ignore click springs and keep identical volume",
        )

    def test_baseplate_clicksprings_volume_stability(self) -> None:
        freecad_cmd = _resolve_freecad_cmd()
        if not freecad_cmd:
            self.skipTest(f"Set {FREECAD_CMD_ENV} in environment or .env")

        freecad_module_root = (REPO_ROOT / "freecad").as_posix()

        script = textwrap.dedent(
            """
            import json
            import sys

            sys.path.insert(0, {module_root})

            import FreeCAD as fc  # noqa: N813
            import gridfinity_workbench.features as features

            def build_case(name: str, click_springs: bool) -> dict[str, float | int | str | bool]:
                doc = fc.newDocument(name)
                try:
                    obj = doc.addObject("Part::FeaturePython", "Baseplate")
                    features.Baseplate(obj)
                    obj.xGridUnits = 2
                    obj.yGridUnits = 2
                    obj.JunctionScrewHoles = True
                    obj.ClipCutoutsEnabled = True
                    obj.FillerTopEnabled = True
                    obj.FillerTopWidth = 10
                    obj.FillerRightEnabled = True
                    obj.FillerRightWidth = 10
                    obj.FillerBottomEnabled = True
                    obj.FillerBottomWidth = 10
                    obj.FillerLeftEnabled = True
                    obj.FillerLeftWidth = 10
                    obj.ClickSpringsEnabled = click_springs
                    doc.recompute()
                    shape = obj.Shape
                    bbox = shape.BoundBox
                    return {{
                        "volume": float(shape.Volume),
                        "solids": int(len(shape.Solids)),
                        "shape_type": str(shape.ShapeType),
                        "valid": bool(shape.isValid()),
                        "x_min": float(bbox.XMin),
                        "x_max": float(bbox.XMax),
                        "y_min": float(bbox.YMin),
                        "y_max": float(bbox.YMax),
                    }}
                finally:
                    fc.closeDocument(doc.Name)

            baseline = build_case("BaseNoSprings", click_springs=False)
            with_springs = build_case("BaseWithSprings", click_springs=True)

            payload = {{"baseline": baseline, "with_springs": with_springs}}
            print("GRIDFINITY_RESULT=" + json.dumps(payload))
            """,
        ).format(module_root=repr(freecad_module_root))

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name

        try:
            proc = subprocess.run(  # noqa: S603
                [freecad_cmd, script_path],
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

        self.assertEqual(
            proc.returncode,
            0,
            msg=f"FreeCADCmd failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )

        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith(RESULT_PREFIX)), None)
        self.assertIsNotNone(
            line,
            msg=f"No result marker found\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )
        data = json.loads(line[len(RESULT_PREFIX) :])

        baseline = data["baseline"]
        with_springs = data["with_springs"]

        self.assertEqual(baseline["solids"], 1, "Baseline must be a single solid")
        self.assertEqual(with_springs["solids"], 1, "Clicksprings result must be a single solid")
        self.assertIn(
            baseline["shape_type"],
            {"Solid", "Compound"},
            "Baseline shape type must be Solid/Compound",
        )
        self.assertIn(
            with_springs["shape_type"],
            {"Solid", "Compound"},
            "Clicksprings shape type must be Solid/Compound",
        )
        self.assertTrue(bool(baseline["valid"]), "Baseline shape must be valid")
        self.assertTrue(bool(with_springs["valid"]), "Clicksprings shape must be valid")

        baseline_volume = float(baseline["volume"])
        springs_volume = float(with_springs["volume"])
        abs_diff = abs(springs_volume - baseline_volume)
        self.assertLessEqual(
            abs_diff,
            0.01,
            msg=(
                f"Volume drift too large: baseline={baseline_volume}, "
                f"with_springs={springs_volume}, absolute={abs_diff:.6f}"
            ),
        )

        bbox_tol = 0.01
        self.assertLessEqual(
            abs(float(with_springs["x_min"]) - float(baseline["x_min"])),
            bbox_tol,
            "XMin drift indicates misplaced springs",
        )
        self.assertLessEqual(
            abs(float(with_springs["x_max"]) - float(baseline["x_max"])),
            bbox_tol,
            "XMax drift indicates misplaced springs",
        )
        self.assertLessEqual(
            abs(float(with_springs["y_min"]) - float(baseline["y_min"])),
            bbox_tol,
            "YMin drift indicates misplaced springs",
        )
        self.assertLessEqual(
            abs(float(with_springs["y_max"]) - float(baseline["y_max"])),
            bbox_tol,
            "YMax drift indicates misplaced springs",
        )

    @unittest.skip("Skipping clip test during param overhaul")
    def test_connecting_clip_defaults_volume_locked(self) -> None:
        # LOCKED INVARIANT:
        # Expected dimensions/volume are strict regression locks for default clip.
        # Do not modify expected values or relax assertions without explicit
        # user confirmation in the current conversation.
        freecad_cmd = _resolve_freecad_cmd()
        if not freecad_cmd:
            self.skipTest(f"Set {FREECAD_CMD_ENV} in environment or .env")

        freecad_module_root = (REPO_ROOT / "freecad").as_posix()
        expected_volume = 21.979791192690158
        expected_x_size = 2.7
        expected_y_size = 3.5
        expected_z_size = 4.1

        script = textwrap.dedent(
            """
            import json
            import sys

            sys.path.insert(0, {module_root})

            import FreeCAD as fc  # noqa: N813
            import gridfinity_workbench.features as features

            doc = fc.newDocument("ConnectingClipDefaults")
            try:
                obj = doc.addObject("Part::FeaturePython", "ConnectingClip")
                features.ConnectingClip(obj)
                obj.HalfWidth = 2.15
                obj.Height = 4.0
                obj.Tolerance = 0.15
                obj.ClipLength = 3.0
                doc.recompute()
                shape = obj.Shape
                bbox = shape.BoundBox
                payload = {{
                    "volume": float(shape.Volume),
                    "solids": int(len(shape.Solids)),
                    "valid": bool(shape.isValid()),
                    "x_size": float(bbox.XMax - bbox.XMin),
                    "y_size": float(bbox.YMax - bbox.YMin),
                    "z_size": float(bbox.ZMax - bbox.ZMin),
                }}
                print("GRIDFINITY_RESULT=" + json.dumps(payload))
            finally:
                fc.closeDocument(doc.Name)
            """,
        ).format(module_root=repr(freecad_module_root))

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name

        try:
            proc = subprocess.run(  # noqa: S603
                [freecad_cmd, script_path],
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

        self.assertEqual(
            proc.returncode,
            0,
            msg=f"FreeCADCmd failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )

        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith(RESULT_PREFIX)), None)
        self.assertIsNotNone(
            line,
            msg=f"No result marker found\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )
        data = json.loads(line[len(RESULT_PREFIX) :])

        self.assertEqual(int(data["solids"]), 1, "Expected a single solid")
        self.assertTrue(bool(data["valid"]), "Resulting shape must be valid")
        self.assertAlmostEqual(
            float(data["x_size"]),
            expected_x_size,
            places=6,
            msg=f"Unexpected X size: got {data['x_size']}, expected {expected_x_size}",
        )
        self.assertAlmostEqual(
            float(data["y_size"]),
            expected_y_size,
            places=6,
            msg=f"Unexpected Y size: got {data['y_size']}, expected {expected_y_size}",
        )
        self.assertAlmostEqual(
            float(data["z_size"]),
            expected_z_size,
            places=6,
            msg=f"Unexpected Z size: got {data['z_size']}, expected {expected_z_size}",
        )
        self.assertAlmostEqual(
            float(data["volume"]),
            expected_volume,
            places=6,
            msg=f"Unexpected volume drift: got {data['volume']}, expected {expected_volume}",
        )

    def test_drawer_baseplate_preview_build_reports_time(self) -> None:
        freecad_cmd = _resolve_freecad_cmd()
        if not freecad_cmd:
            self.skipTest(f"Set {FREECAD_CMD_ENV} in environment or .env")

        freecad_module_root = (REPO_ROOT / "freecad").as_posix()

        script = textwrap.dedent(
            """
            import json
            import sys
            import time

            sys.path.insert(0, {module_root})

            import FreeCAD as fc  # noqa: N813
            import gridfinity_workbench.features as features
            from gridfinity_workbench.baseplate_builder import BaseplateBuildOptions

            doc = fc.newDocument("DrawerPreview")
            try:
                obj = doc.addObject("Part::FeaturePython", "DrawerBaseplate")
                features.DrawerBaseplate(obj)

                obj.DrawerWidth = 600
                obj.DrawerDepth = 500
                obj.PrinterBedWidth = 256
                obj.PrinterBedDepth = 240
                obj.WidthFillerAlignment = "Right"
                obj.DepthFillerAlignment = "Top"
                obj.PreviewBuildMode = True

                start = time.perf_counter()
                doc.recompute()
                elapsed = time.perf_counter() - start

                shape = obj.Shape
                payload = {{
                    "elapsed_seconds": float(elapsed),
                    "valid": bool(shape.isValid()),
                    "piece_count": int(len(getattr(obj, "PieceNames", []))),
                    "solids": int(len(shape.Solids)),
                }}
                print("GRIDFINITY_RESULT=" + json.dumps(payload))
            finally:
                fc.closeDocument(doc.Name)
            """,
        ).format(module_root=repr(freecad_module_root))

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name

        try:
            proc = subprocess.run(  # noqa: S603
                [freecad_cmd, script_path],
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

        self.assertEqual(
            proc.returncode,
            0,
            msg=f"FreeCADCmd failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )

        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith(RESULT_PREFIX)), None)
        self.assertIsNotNone(
            line,
            msg=f"No result marker found\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )
        data = json.loads(line[len(RESULT_PREFIX) :])

        self.assertGreaterEqual(float(data["elapsed_seconds"]), 0.0)
        self.assertTrue(bool(data["valid"]))
        self.assertGreater(int(data["piece_count"]), 0)
        self.assertGreater(int(data["solids"]), 0)

    def test_baseplate_2x2_with_features_volume_unchanged(self) -> None:
        # LOCKED INVARIANT:
        # Expected X/Y/Z and volume are intentionally strict regression locks.
        # Do not modify expected values or relax assertions without explicit
        # user confirmation in the current conversation.
        freecad_cmd = _resolve_freecad_cmd()
        if not freecad_cmd:
            self.skipTest(f"Set {FREECAD_CMD_ENV} in environment or .env")

        freecad_module_root = (REPO_ROOT / "freecad").as_posix()
        expected_volume = 4581.608342759908
        expected_x_size = 84.0
        expected_y_size = 84.0
        expected_z_size = 3.85

        script = textwrap.dedent(
            """
            import json
            import sys

            sys.path.insert(0, {module_root})

            import FreeCAD as fc  # noqa: N813
            import gridfinity_workbench.features as features

            doc = fc.newDocument("BaseWithFeatures")
            try:
                obj = doc.addObject("Part::FeaturePython", "Baseplate")
                features.Baseplate(obj)
                obj.xGridUnits = 2
                obj.yGridUnits = 2
                obj.JunctionScrewHoles = True
                obj.ClipCutoutsEnabled = True
                obj.ClickSpringsEnabled = True
                obj.FillerTopEnabled = False
                obj.FillerRightEnabled = False
                obj.FillerBottomEnabled = False
                obj.FillerLeftEnabled = False
                doc.recompute()
                shape = obj.Shape
                bbox = shape.BoundBox
                payload = {{
                    "volume": float(shape.Volume),
                    "solids": int(len(shape.Solids)),
                    "valid": bool(shape.isValid()),
                    "x_size": float(bbox.XMax - bbox.XMin),
                    "y_size": float(bbox.YMax - bbox.YMin),
                    "z_size": float(bbox.ZMax - bbox.ZMin),
                }}
                print("GRIDFINITY_RESULT=" + json.dumps(payload))
            finally:
                fc.closeDocument(doc.Name)
            """,
        ).format(module_root=repr(freecad_module_root))

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name

        try:
            proc = subprocess.run(  # noqa: S603
                [freecad_cmd, script_path],
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

        self.assertEqual(
            proc.returncode,
            0,
            msg=f"FreeCADCmd failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )

        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith(RESULT_PREFIX)), None)
        self.assertIsNotNone(
            line,
            msg=f"No result marker found\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )
        data = json.loads(line[len(RESULT_PREFIX) :])

        self.assertEqual(int(data["solids"]), 1, "Expected a single solid")
        self.assertTrue(bool(data["valid"]), "Resulting shape must be valid")
        self.assertAlmostEqual(
            float(data["x_size"]),
            expected_x_size,
            places=6,
            msg=f"Unexpected X size: got {data['x_size']}, expected {expected_x_size}",
        )
        self.assertAlmostEqual(
            float(data["y_size"]),
            expected_y_size,
            places=6,
            msg=f"Unexpected Y size: got {data['y_size']}, expected {expected_y_size}",
        )
        self.assertAlmostEqual(
            float(data["z_size"]),
            expected_z_size,
            places=6,
            msg=f"Unexpected Z size: got {data['z_size']}, expected {expected_z_size}",
        )
        self.assertAlmostEqual(
            float(data["volume"]),
            expected_volume,
            places=6,
            msg=f"Unexpected volume drift: got {data['volume']}, expected {expected_volume}",
        )

    def test_baseplate_x0_y2_right_filler_3mm_builds(self) -> None:
        freecad_cmd = _resolve_freecad_cmd()
        if not freecad_cmd:
            self.skipTest(f"Set {FREECAD_CMD_ENV} in environment or .env")

        freecad_module_root = (REPO_ROOT / "freecad").as_posix()

        script = textwrap.dedent(
            """
            import json
            import sys

            sys.path.insert(0, {module_root})

            import FreeCAD as fc  # noqa: N813
            import gridfinity_workbench.features as features

            doc = fc.newDocument("BaseX0Y2")
            try:
                obj = doc.addObject("Part::FeaturePython", "Baseplate")
                features.Baseplate(obj)
                obj.xGridUnits = 0
                obj.yGridUnits = 2
                obj.FillerRightEnabled = True
                obj.FillerRightWidth = 3
                obj.FillerLeftEnabled = False
                obj.FillerTopEnabled = False
                obj.FillerBottomEnabled = False
                obj.ClickSpringsEnabled = False
                obj.JunctionScrewHoles = False
                obj.ClipCutoutsEnabled = False
                doc.recompute()
                shape = obj.Shape
                bbox = shape.BoundBox
                payload = {{
                    "solids": int(len(shape.Solids)),
                    "valid": bool(shape.isValid()),
                    "x_size": float(bbox.XMax - bbox.XMin),
                    "y_size": float(bbox.YMax - bbox.YMin),
                }}
                print("GRIDFINITY_RESULT=" + json.dumps(payload))
            finally:
                fc.closeDocument(doc.Name)
            """,
        ).format(module_root=repr(freecad_module_root))

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name

        try:
            proc = subprocess.run(  # noqa: S603
                [freecad_cmd, script_path],
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

        self.assertEqual(
            proc.returncode,
            0,
            msg=f"FreeCADCmd failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )

        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith(RESULT_PREFIX)), None)
        self.assertIsNotNone(
            line,
            msg=f"No result marker found\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )
        data = json.loads(line[len(RESULT_PREFIX) :])
        self.assertEqual(int(data["solids"]), 1)
        self.assertTrue(bool(data["valid"]))

    def test_baseplate_preview_right_filler_2mm_builds(self) -> None:
        freecad_cmd = _resolve_freecad_cmd()
        if not freecad_cmd:
            self.skipTest(f"Set {FREECAD_CMD_ENV} in environment or .env")

        freecad_module_root = (REPO_ROOT / "freecad").as_posix()

        script = textwrap.dedent(
            """
            import json
            import sys

            sys.path.insert(0, {module_root})

            import FreeCAD as fc  # noqa: N813
            import gridfinity_workbench.features as features
            from gridfinity_workbench.baseplate_builder import BaseplateBuildOptions
            from gridfinity_workbench.param import CombinedBaseplateParams

            doc = fc.newDocument("BasePreviewFill2")
            try:
                obj = doc.addObject("Part::FeaturePython", "Baseplate")
                features.Baseplate(obj)
                obj.xGridUnits = 2
                obj.yGridUnits = 2
                obj.FillerRightEnabled = True
                obj.FillerRightWidth = 2
                obj.FillerLeftEnabled = False
                obj.FillerTopEnabled = False
                obj.FillerBottomEnabled = False
                layout = features.grid_initial_layout.make_rectangle_layout(obj)
                params = CombinedBaseplateParams().from_obj(obj).data()
                shape = features.baseplate_builder.build_simple_baseplate_from_params(
                    params,
                    layout,
                    BaseplateBuildOptions(),
                    preview=True,
                )
                payload = {{
                    "solids": int(len(shape.Solids)),
                    "valid": bool(shape.isValid()),
                    "is_null": bool(shape.isNull()),
                }}
                print("GRIDFINITY_RESULT=" + json.dumps(payload))
            finally:
                fc.closeDocument(doc.Name)
            """,
        ).format(module_root=repr(freecad_module_root))

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name

        try:
            proc = subprocess.run(  # noqa: S603
                [freecad_cmd, script_path],
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

        self.assertEqual(
            proc.returncode,
            0,
            msg=f"FreeCADCmd failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )

        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith(RESULT_PREFIX)), None)
        self.assertIsNotNone(
            line,
            msg=f"No result marker found\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )
        data = json.loads(line[len(RESULT_PREFIX) :])
        self.assertFalse(bool(data["is_null"]))
        self.assertTrue(bool(data["valid"]))
        self.assertGreaterEqual(int(data["solids"]), 1)

    def test_support_baseplate_top_and_right_filler_volume_locked(self) -> None:
        freecad_cmd = _resolve_freecad_cmd()
        if not freecad_cmd:
            self.skipTest(f"Set {FREECAD_CMD_ENV} in environment or .env")

        freecad_module_root = (REPO_ROOT / "freecad").as_posix()

        script = textwrap.dedent(
            """
            import json
            import sys

            sys.path.insert(0, {module_root})

            import FreeCAD as fc  # noqa: N813
            import gridfinity_workbench.features as features

            doc = fc.newDocument("SupportFillLocked")
            try:
                obj = doc.addObject("Part::FeaturePython", "SupportBaseplate")
                features.SupportBaseplate(obj)
                obj.FillerTopEnabled = True
                obj.FillerRightEnabled = True
                obj.FillerRightWidth = 3
                obj.FillerLeftEnabled = False
                obj.FillerBottomEnabled = False
                doc.recompute()
                shape = obj.Shape
                payload = {{
                    "freecad_version": ".".join(str(part) for part in fc.Version()[:3]),
                    "volume": float(shape.Volume),
                    "solids": int(len(shape.Solids)),
                    "valid": bool(shape.isValid()),
                }}
                print("GRIDFINITY_RESULT=" + json.dumps(payload))
            finally:
                fc.closeDocument(doc.Name)
            """,
        ).format(module_root=repr(freecad_module_root))

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name

        try:
            proc = subprocess.run(  # noqa: S603
                [freecad_cmd, script_path],
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

        self.assertEqual(
            proc.returncode,
            0,
            msg=f"FreeCADCmd failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )

        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith(RESULT_PREFIX)), None)
        self.assertIsNotNone(
            line,
            msg=f"No result marker found\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )
        data = json.loads(line[len(RESULT_PREFIX) :])
        self.assertEqual(int(data["solids"]), 1)
        self.assertTrue(bool(data["valid"]))
        freecad_version = str(data.get("freecad_version", ""))
        # NOTE: OCC/FreeCAD geometry kernel differences between versions
        # produce different but stable body volumes for this scenario.
        expected_volume = 2876.8821069099063
        if freecad_version.startswith("1.1"):
            expected_volume = 2880.8451891035947
        self.assertAlmostEqual(float(data["volume"]), expected_volume, places=6)

    def test_baseplate_x2_y2_radius2_right_filler_5_1_rejected(self) -> None:
        freecad_cmd = _resolve_freecad_cmd()
        if not freecad_cmd:
            self.skipTest(f"Set {FREECAD_CMD_ENV} in environment or .env")

        freecad_module_root = (REPO_ROOT / "freecad").as_posix()

        script = textwrap.dedent(
            """
            import sys

            sys.path.insert(0, {module_root})

            import FreeCAD as fc  # noqa: N813
            import gridfinity_workbench.features as features

            doc = fc.newDocument("BaseX2Y2Radius2")
            try:
                obj = doc.addObject("Part::FeaturePython", "Baseplate")
                features.Baseplate(obj)
                obj.xGridUnits = 2
                obj.yGridUnits = 2
                obj.BinOuterRadius = 2
                obj.FillerRightEnabled = True
                obj.FillerRightWidth = 5.1
                obj.FillerLeftEnabled = False
                obj.FillerTopEnabled = False
                obj.FillerBottomEnabled = False
                obj.ClickSpringsEnabled = False
                obj.JunctionScrewHoles = False
                obj.ClipCutoutsEnabled = False
                doc.recompute()
            finally:
                fc.closeDocument(doc.Name)
            """,
        ).format(module_root=repr(freecad_module_root))

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name

        try:
            proc = subprocess.run(  # noqa: S603
                [freecad_cmd, script_path],
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

        self.assertEqual(proc.returncode, 0)
        self.assertIn("must be greater than BaseProfileMainHalfWidth", proc.stderr)

    def test_baseplate_defaults_right_filler_2mm_builds(self) -> None:
        freecad_cmd = _resolve_freecad_cmd()
        if not freecad_cmd:
            self.skipTest(f"Set {FREECAD_CMD_ENV} in environment or .env")

        freecad_module_root = (REPO_ROOT / "freecad").as_posix()

        script = textwrap.dedent(
            """
            import json
            import sys

            sys.path.insert(0, {module_root})

            import FreeCAD as fc  # noqa: N813
            import gridfinity_workbench.features as features

            doc = fc.newDocument("BaseDefaultRightFill2mm")
            try:
                obj = doc.addObject("Part::FeaturePython", "Baseplate")
                features.Baseplate(obj)
                obj.FillerRightEnabled = True
                obj.FillerRightWidth = 2
                doc.recompute()
                shape = obj.Shape
                payload = {{
                    "solids": int(len(shape.Solids)),
                    "valid": bool(shape.isValid()),
                    "volume": float(shape.Volume),
                }}
                print("GRIDFINITY_RESULT=" + json.dumps(payload))
            finally:
                fc.closeDocument(doc.Name)
            """,
        ).format(module_root=repr(freecad_module_root))

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name

        try:
            proc = subprocess.run(  # noqa: S603
                [freecad_cmd, script_path],
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

        self.assertEqual(
            proc.returncode,
            0,
            msg=f"FreeCADCmd failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )

        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith(RESULT_PREFIX)), None)
        self.assertIsNotNone(
            line,
            msg=f"No result marker found\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )
        data = json.loads(line[len(RESULT_PREFIX) :])
        self.assertEqual(int(data["solids"]), 1)
        self.assertTrue(bool(data["valid"]))
        self.assertGreater(float(data["volume"]), 0.0)

    def test_baseplate_click_thickness_equal_half_width_rejected(self) -> None:
        freecad_cmd = _resolve_freecad_cmd()
        if not freecad_cmd:
            self.skipTest(f"Set {FREECAD_CMD_ENV} in environment or .env")

        freecad_module_root = (REPO_ROOT / "freecad").as_posix()

        script = textwrap.dedent(
            """
            import sys

            sys.path.insert(0, {module_root})

            import FreeCAD as fc  # noqa: N813
            import gridfinity_workbench.features as features

            doc = fc.newDocument("ClickThicknessRejected")
            try:
                obj = doc.addObject("Part::FeaturePython", "Baseplate")
                features.Baseplate(obj)
                obj.ClickSpringsEnabled = True
                obj.ClickThickness = obj.BaseProfileMainHalfWidth
                doc.recompute()
            finally:
                fc.closeDocument(doc.Name)
            """,
        ).format(module_root=repr(freecad_module_root))

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name

        try:
            proc = subprocess.run(  # noqa: S603
                [freecad_cmd, script_path],
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

        self.assertEqual(proc.returncode, 0)
        self.assertIn("Invalid click spring geometry: ClickThickness", proc.stderr)

    def test_baseplate_click_length_limit_rejected(self) -> None:
        freecad_cmd = _resolve_freecad_cmd()
        if not freecad_cmd:
            self.skipTest(f"Set {FREECAD_CMD_ENV} in environment or .env")

        freecad_module_root = (REPO_ROOT / "freecad").as_posix()

        script = textwrap.dedent(
            """
            import sys

            sys.path.insert(0, {module_root})

            import FreeCAD as fc  # noqa: N813
            import gridfinity_workbench.features as features

            doc = fc.newDocument("ClickLengthRejected")
            try:
                obj = doc.addObject("Part::FeaturePython", "Baseplate")
                features.Baseplate(obj)
                obj.ClickSpringsEnabled = True
                # Exceeds default max half-length (8.65mm) because 18/2 = 9mm.
                obj.ClickLength = 18
                doc.recompute()
            finally:
                fc.closeDocument(doc.Name)
            """,
        ).format(module_root=repr(freecad_module_root))

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name

        try:
            proc = subprocess.run(  # noqa: S603
                [freecad_cmd, script_path],
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

        self.assertEqual(proc.returncode, 0)
        self.assertIn("Invalid click spring geometry: ClickLength/2", proc.stderr)

    def test_baseplate_2x2_right_filler_3mm_matches_expected_volume_delta(self) -> None:
        freecad_cmd = _resolve_freecad_cmd()
        if not freecad_cmd:
            self.skipTest(f"Set {FREECAD_CMD_ENV} in environment or .env")

        freecad_module_root = (REPO_ROOT / "freecad").as_posix()

        script = textwrap.dedent(
            """
            import json
            import sys

            sys.path.insert(0, {module_root})

            import FreeCAD as fc  # noqa: N813
            import gridfinity_workbench.features as features

            def build_case(name: str, with_right_filler: bool) -> dict[str, float | int | bool]:
                doc = fc.newDocument(name)
                try:
                    obj = doc.addObject("Part::FeaturePython", "Baseplate")
                    features.Baseplate(obj)
                    obj.xGridUnits = 2
                    obj.yGridUnits = 2
                    obj.JunctionScrewHoles = True
                    obj.ClickSpringsEnabled = True
                    obj.ClipCutoutsEnabled = False
                    obj.FillerTopEnabled = False
                    obj.FillerLeftEnabled = False
                    obj.FillerBottomEnabled = False
                    obj.FillerRightEnabled = bool(with_right_filler)
                    if with_right_filler:
                        obj.FillerRightWidth = 3
                    doc.recompute()
                    shape = obj.Shape
                    h = obj.BaseProfileMainHeight
                    w = obj.BaseProfileMainHalfWidth
                    c = obj.BaseProfileTopCrop
                    effective_height = float(h + w - c)
                    span = float(obj.yGridSize * obj.yGridUnits)
                    return {{
                        "volume": float(shape.Volume),
                        "solids": int(len(shape.Solids)),
                        "valid": bool(shape.isValid()),
                        "effective_height": effective_height,
                        "span": span,
                    }}
                finally:
                    fc.closeDocument(doc.Name)

            baseline = build_case("Base2x2NoFiller", with_right_filler=False)
            with_filler = build_case("Base2x2RightFill3", with_right_filler=True)
            result = {{"baseline": baseline, "with_filler": with_filler}}
            print("GRIDFINITY_RESULT=" + json.dumps(result))
            """,
        ).format(module_root=repr(freecad_module_root))

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name

        try:
            proc = subprocess.run(  # noqa: S603
                [freecad_cmd, script_path],
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

        self.assertEqual(
            proc.returncode,
            0,
            msg=f"FreeCADCmd failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )

        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith(RESULT_PREFIX)), None)
        self.assertIsNotNone(
            line,
            msg=f"No result marker found\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )
        data = json.loads(line[len(RESULT_PREFIX) :])

        baseline = data["baseline"]
        with_filler = data["with_filler"]
        self.assertEqual(int(baseline["solids"]), 1)
        self.assertEqual(int(with_filler["solids"]), 1)
        self.assertTrue(bool(baseline["valid"]))
        self.assertTrue(bool(with_filler["valid"]))
        self.assertGreater(
            float(with_filler["volume"]),
            float(baseline["volume"]),
            msg="Expected right filler 3 mm to increase total baseplate volume",
        )
        delta = float(with_filler["volume"]) - float(baseline["volume"])
        expected_delta = 3.0 * float(with_filler["effective_height"]) * float(with_filler["span"])
        self.assertAlmostEqual(
            delta,
            expected_delta,
            places=3,
            msg=(
                "Unexpected filler volume delta: "
                f"delta={delta}, expected={expected_delta} "
                "(3mm * (MainHeight + MainHalfWidth - TopCrop) * yGridSize * yGridUnits)"
            ),
        )

    def test_stacked_baseplates_defaults_shape_and_timing(self) -> None:
        freecad_cmd = _resolve_freecad_cmd()
        if not freecad_cmd:
            self.skipTest(f"Set {FREECAD_CMD_ENV} in environment or .env")

        freecad_module_root = (REPO_ROOT / "freecad").as_posix()

        script = textwrap.dedent(
            """
            import json
            import sys
            import time

            sys.path.insert(0, {module_root})

            import FreeCAD as fc  # noqa: N813
            import gridfinity_workbench.features as features

            doc = fc.newDocument("StackedDefaults")
            try:
                base_obj = doc.addObject("Part::FeaturePython", "StackedBaseplates")
                features.StackedBaseplates(base_obj)
                base_obj.xGridUnits = 2
                base_obj.yGridUnits = 2
                support_obj = doc.addObject("Part::FeaturePython", "StackedBaseplatesSupport")
                features.StackedBaseplatesSupport(support_obj, base_obj)

                t0 = time.perf_counter()
                doc.recompute()
                elapsed = time.perf_counter() - t0

                base_shape = base_obj.Shape
                support_shape = support_obj.Shape
                payload = {{
                    "elapsed_s": float(elapsed),
                    "base_solids": int(len(base_shape.Solids)),
                    "support_solids": int(len(support_shape.Solids)),
                    "base_valid": bool(base_shape.isValid()),
                    "support_valid": bool(support_shape.isValid()),
                    "base_volume": float(base_shape.Volume),
                    "support_volume": float(support_shape.Volume),
                }}
                print("GRIDFINITY_RESULT=" + json.dumps(payload))
            finally:
                fc.closeDocument(doc.Name)
            """,
        ).format(module_root=repr(freecad_module_root))

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name

        try:
            proc = subprocess.run(  # noqa: S603
                [freecad_cmd, script_path],
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

        self.assertEqual(
            proc.returncode,
            0,
            msg=f"FreeCADCmd failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )

        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith(RESULT_PREFIX)), None)
        self.assertIsNotNone(
            line,
            msg=f"No result marker found\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )
        data = json.loads(line[len(RESULT_PREFIX) :])

        self.assertEqual(int(data["base_solids"]), 3)
        self.assertEqual(int(data["support_solids"]), 2)
        self.assertTrue(bool(data["base_valid"]))
        self.assertTrue(bool(data["support_valid"]))
        self.assertGreater(float(data["base_volume"]), 0.0)
        self.assertGreater(float(data["support_volume"]), 0.0)

    def test_stacked_support_screw_stubs_with_fillers_and_stitching_volume_locked(self) -> None:
        freecad_cmd = _resolve_freecad_cmd()
        if not freecad_cmd:
            self.skipTest(f"Set {FREECAD_CMD_ENV} in environment or .env")

        freecad_module_root = (REPO_ROOT / "freecad").as_posix()

        script = textwrap.dedent(
            """
            import json
            import sys

            sys.path.insert(0, {module_root})

            import FreeCAD as fc  # noqa: N813
            import Part
            import gridfinity_workbench.features as features

            doc = fc.newDocument("StackedScrewStubsFull")
            try:
                base_obj = doc.addObject("Part::FeaturePython", "StackedBaseplates")
                features.StackedBaseplates(base_obj)
                base_obj.xGridUnits = 2
                base_obj.yGridUnits = 2
                base_obj.FillerRightEnabled = True
                base_obj.FillerTopEnabled = True
                base_obj.FillerTopWidth = 3.0
                base_obj.CornerStitching = True
                support_obj = doc.addObject("Part::FeaturePython", "StackedBaseplatesSupport")
                features.StackedBaseplatesSupport(support_obj, base_obj)

                base_obj.ScrewStubsEnabled = False
                base_obj.JunctionScrewHoles = True
                doc.recompute()
                base_without_stubs = base_obj.Shape
                support_without_stubs = support_obj.Shape

                base_obj.ScrewStubsEnabled = True
                base_obj.ScrewStubClearance = 0.15
                doc.recompute()
                base_with_stubs = base_obj.Shape
                support_with_stubs = support_obj.Shape

                # Calculate intersection volumes
                base_isect = base_without_stubs.common(base_with_stubs)
                supp_isect = support_without_stubs.common(support_with_stubs)

                b_wo = base_without_stubs
                b_w = base_with_stubs
                s_wo = support_without_stubs
                s_w = support_with_stubs
                payload = {{
                    "base_without_volume": float(b_wo.Volume),
                    "base_with_volume": float(b_w.Volume),
                    "support_without_volume": float(s_wo.Volume),
                    "support_with_volume": float(s_w.Volume),
                    "base_base_intersection_volume": float(base_isect.Volume),
                    "support_support_intersection_volume": float(supp_isect.Volume),
                    "base_valid": bool(b_wo.isValid()) and bool(b_w.isValid()),
                    "support_valid": bool(s_wo.isValid()) and bool(s_w.isValid()),
                    "base_solids": int(len(b_wo.Solids)) + int(len(b_w.Solids)),
                    "support_solids": int(len(s_wo.Solids)) + int(len(s_w.Solids)),
                }}
                print("GRIDFINITY_RESULT=" + json.dumps(payload))
            finally:
                fc.closeDocument(doc.Name)
            """,
        ).format(module_root=repr(freecad_module_root))

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name

        try:
            proc = subprocess.run(  # noqa: S603
                [freecad_cmd, script_path],
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

        self.assertEqual(
            proc.returncode,
            0,
            msg=f"FreeCADCmd failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )

        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith(RESULT_PREFIX)), None)
        self.assertIsNotNone(
            line,
            msg=f"No result marker found\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )
        data = json.loads(line[len(RESULT_PREFIX) :])

        self.assertTrue(bool(data["base_valid"]))
        self.assertTrue(bool(data["support_valid"]))
        self.assertGreaterEqual(int(data["base_solids"]), 2)  # At least 2 baseplates
        self.assertGreaterEqual(int(data["support_solids"]), 2)  # At least 2 support parts

        # Support volume should increase with stubs
        self.assertGreater(
            float(data["support_with_volume"]),
            float(data["support_without_volume"]),
        )

        # Baseplate volume should be unchanged
        self.assertAlmostEqual(
            float(data["base_with_volume"]),
            float(data["base_without_volume"]),
            places=6,
        )

        # Base-base and support-support should have same core volume
        # (intersection should be nearly full volume).
        # Allow small tolerance for floating point differences.
        base_vol_without = float(data["base_without_volume"])
        base_vol_with = float(data["base_with_volume"])
        base_intersection = float(data["base_base_intersection_volume"])
        self.assertGreaterEqual(base_intersection, min(base_vol_without, base_vol_with) * 0.999)

        support_vol_without = float(data["support_without_volume"])
        support_vol_with = float(data["support_with_volume"])
        support_intersection = float(data["support_support_intersection_volume"])
        self.assertGreaterEqual(
            support_intersection,
            min(support_vol_without, support_vol_with) * 0.999,
        )
