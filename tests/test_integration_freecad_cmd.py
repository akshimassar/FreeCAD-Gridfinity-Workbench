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
            """
        ).format(module_root=repr(freecad_module_root))

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name

        try:
            proc = subprocess.run(
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
        self.assertIsNotNone(line, msg=f"No result marker found\nSTDOUT:\n{proc.stdout}")
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
                f"Volume drift too large: baseline={baseline_volume}, with_springs={springs_volume}, "
                f"absolute={abs_diff:.6f}"
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

    def test_baseplate_2x2_with_features_volume_unchanged(self) -> None:
        freecad_cmd = _resolve_freecad_cmd()
        if not freecad_cmd:
            self.skipTest(f"Set {FREECAD_CMD_ENV} in environment or .env")

        freecad_module_root = (REPO_ROOT / "freecad").as_posix()
        expected_volume = 4526.426777362498

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
                payload = {{
                    "volume": float(shape.Volume),
                    "solids": int(len(shape.Solids)),
                    "valid": bool(shape.isValid()),
                }}
                print("GRIDFINITY_RESULT=" + json.dumps(payload))
            finally:
                fc.closeDocument(doc.Name)
            """
        ).format(module_root=repr(freecad_module_root))

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name

        try:
            proc = subprocess.run(
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
        self.assertIsNotNone(line, msg=f"No result marker found\nSTDOUT:\n{proc.stdout}")
        data = json.loads(line[len(RESULT_PREFIX) :])

        self.assertEqual(int(data["solids"]), 1, "Expected a single solid")
        self.assertTrue(bool(data["valid"]), "Resulting shape must be valid")
        self.assertAlmostEqual(
            float(data["volume"]),
            expected_volume,
            places=6,
            msg=f"Unexpected volume drift: got {data['volume']}, expected {expected_volume}",
        )

    def test_baseplate_x0_y2_right_filler_3mm_rejected(self) -> None:
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
            """
        ).format(module_root=repr(freecad_module_root))

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name

        try:
            proc = subprocess.run(
                [freecad_cmd, script_path],
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

        self.assertEqual(proc.returncode, 0)
        self.assertIn("must be greater than BinOuterRadius", proc.stderr)

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
            """
        ).format(module_root=repr(freecad_module_root))

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(script)
            script_path = tmp.name

        try:
            proc = subprocess.run(
                [freecad_cmd, script_path],
                check=False,
                capture_output=True,
                text=True,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

        self.assertEqual(proc.returncode, 0)
        self.assertIn("must be greater than BaseProfileMainHalfWidth", proc.stderr)
