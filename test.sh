#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

RUN_LINT=false
RUN_UNIT=false
RUN_GUI=false
RUN_INTEGRATION=false
EXPLICIT=false

for arg in "$@"; do
  case "$arg" in
    --lint) RUN_LINT=true; EXPLICIT=true ;;
    --unit) RUN_UNIT=true; EXPLICIT=true ;;
    --gui) RUN_GUI=true; EXPLICIT=true ;;
    --integration) RUN_INTEGRATION=true; EXPLICIT=true ;;
    --help|-h)
      echo "Usage: $0 [--lint] [--unit] [--gui] [--integration]"
      echo "  --lint         Run ruff and mypy checks"
      echo "  --unit         Run unit tests"
      echo "  --gui          Run GUI tests (requires FREECAD_GUI_CMD)"
      echo "  --integration  Run integration tests (requires FREECAD_CMD/FREECAD_CMDS)"
      echo "  No flags runs all tests."
      exit 0
      ;;
  esac
done

if [[ "$EXPLICIT" == "false" ]]; then
  RUN_LINT=true
  RUN_UNIT=true
  RUN_GUI=true
  RUN_INTEGRATION=true
fi

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  source .env
fi

if [[ "$RUN_LINT" == "true" ]]; then
  echo "Running mypy..."
  uv run mypy freecad/gridfinity_workbench/
  echo "Running ruff check..."
  uv run ruff check .
  echo "Running ruff format check..."
  uv run ruff format --check .
fi

if [[ "$RUN_UNIT" == "true" ]]; then
  echo "Running unit tests..."
  python -m unittest tests.test_unit_utils
fi

if [[ "$RUN_GUI" == "true" ]]; then
  echo "Running GUI tests with xvfb..."
  if [[ -z "${FREECAD_GUI_CMD:-}" ]]; then
    echo "No FreeCAD GUI command configured. Set FREECAD_GUI_CMD in .env" >&2
    exit 1
  fi
  xvfb-run "$FREECAD_GUI_CMD" -t freecad.gridfinity_workbench.test_gridfinity
fi

if [[ "$RUN_INTEGRATION" == "true" ]]; then
  if [[ -z "${FREECAD_CMDS:-}" ]]; then
    if [[ -n "${FREECAD_CMD:-}" ]]; then
      FREECAD_CMDS="$FREECAD_CMD"
    else
      echo "No FreeCAD command configured. Set FREECAD_CMDS or FREECAD_CMD in .env" >&2
      exit 1
    fi
  fi

  for cmd in $FREECAD_CMDS; do
    if [[ ! -x "$cmd" ]]; then
      echo "Skipping missing FreeCAD command: $cmd"
      continue
    fi
    echo "Running integration test with: $cmd"
    FREECAD_CMD="$cmd" python -m unittest tests.test_integration_freecad_cmd
  done
fi

echo "All tests finished."
