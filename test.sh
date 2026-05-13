#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  source .env
fi

echo "Running unit tests..."
python -m unittest tests.test_unit_utils

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

echo "All tests finished."
