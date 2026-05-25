#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

RUN_LINT=false
RUN_UNIT=false
RUN_GUI=false
RUN_INTEGRATION=false
EXPLICIT=false
TEST_NAME=""
FREECAD_VERSION=""
RUN_BENCHMARKS=false

# Default FreeCAD paths (can be overridden by .env or env vars)
DEFAULT_FREECAD_1_1_CMD="/home/akshi/opencode-tmp/freecad-1.1-rootfs/AppRun"
DEFAULT_FREECAD_LINK_CMD="/home/akshi/opencode-tmp/freecad-link-root/AppRun"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lint) RUN_LINT=true; EXPLICIT=true; shift ;;
    --unit) RUN_UNIT=true; EXPLICIT=true; shift ;;
    --gui) RUN_GUI=true; EXPLICIT=true; shift ;;
    --integration) RUN_INTEGRATION=true; EXPLICIT=true; shift ;;
    --benchmarks) RUN_BENCHMARKS=true; shift ;;
    --freecad|-f)
      if [[ -z "${2:-}" ]]; then
        echo "Error: --freecad requires a version argument (1.1, link, or all)" >&2
        exit 1
      fi
      case "$2" in
        1.1|link|all) FREECAD_VERSION="$2" ;;
        *)
          echo "Error: --freecad accepts: 1.1, link, or all" >&2
          exit 1
          ;;
      esac
      shift 2
      ;;
    --test|-t)
      if [[ -z "${2:-}" ]]; then
        echo "Error: --test requires a test name argument" >&2
        exit 1
      fi
      TEST_NAME="$2"
      shift 2
      ;;
    --help|-h)
      echo "Usage: $0 [--lint] [--unit] [--gui] [--integration] [--benchmarks] [--freecad <version>] [--test <name>]"
      echo "  --lint                  Run ruff and mypy checks"
      echo "  --unit                  Run unit tests"
      echo "  --gui                   Run GUI tests (requires FreeCAD)"
      echo "  --integration           Run integration tests (requires FreeCAD)"
      echo "  --benchmarks            Enable benchmark tests (skipped by default)"
      echo "  --freecad|-f <version>  FreeCAD version: 1.1, link, or all"
      echo "  --test|-t <name>        Run only the specified test method"
      echo "  No flags runs all tests."
      echo ""
      echo "Environment variables:"
      echo "  FREECAD_1_1_CMD         Path to FreeCAD 1.1 AppRun"
      echo "  FREECAD_LINK_CMD        Path to FreeCAD LinkBranch AppRun"
      echo "  FREECAD_CMD             Legacy: single FreeCAD command"
      echo "  FREECAD_GUI_CMD         Legacy: FreeCAD GUI command"
      echo "  FREECAD_VERSION         Default version when --freecad not specified"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
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

# Resolve FreeCAD paths from env vars or defaults
FREECAD_1_1_CMD="${FREECAD_1_1_CMD:-$DEFAULT_FREECAD_1_1_CMD}"
FREECAD_LINK_CMD="${FREECAD_LINK_CMD:-$DEFAULT_FREECAD_LINK_CMD}"

# Use FREECAD_VERSION from env if not set via flag
if [[ -z "$FREECAD_VERSION" ]]; then
  FREECAD_VERSION="${FREECAD_VERSION:-1.1}"
fi

# Helper to get FreeCAD command for a version
get_freecad_cmd() {
  local version="$1"
  case "$version" in
    1.1) echo "$FREECAD_1_1_CMD" ;;
    link) echo "$FREECAD_LINK_CMD" ;;
    *) echo "" ;;
  esac
}

# Helper to get FreeCAD Mod directory for a version
get_freecad_mod_dir() {
  local version="$1"
  case "$version" in
    1.1) echo "$HOME/.local/share/FreeCAD/v1-1/Mod" ;;
    link) echo "$HOME/.local/share/FreeCAD/Mod" ;;
    *) echo "" ;;
  esac
}

# Build list of versions to test
get_versions_to_test() {
  case "$FREECAD_VERSION" in
    all) echo "1.1 link" ;;
    *) echo "$FREECAD_VERSION" ;;
  esac
}

# Ensure plugin is symlinked for a FreeCAD version
ensure_plugin_symlink() {
  local version="$1"
  local mod_dir
  mod_dir="$(get_freecad_mod_dir "$version")"
  mkdir -p "$mod_dir"
  local plugin_link="$mod_dir/Gridfinity"
  if [[ ! -L "$plugin_link" ]] || [[ "$(readlink -f "$plugin_link")" != "$ROOT_DIR" ]]; then
    rm -rf "$plugin_link"
    ln -s "$ROOT_DIR" "$plugin_link"
    echo "Symlinked plugin to $plugin_link"
  fi
}

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
  if [[ -n "$TEST_NAME" ]]; then
    python -m unittest "tests.test_unit_utils.TestUnitUtils.$TEST_NAME"
  else
    python -m unittest tests.test_unit_utils
  fi
fi

if [[ "$RUN_GUI" == "true" ]]; then
  for version in $(get_versions_to_test); do
    freecad_cmd="$(get_freecad_cmd "$version")"
    
    # Fall back to legacy FREECAD_GUI_CMD if version command not available
    if [[ ! -x "$freecad_cmd" ]] && [[ -n "${FREECAD_GUI_CMD:-}" ]]; then
      freecad_cmd="$FREECAD_GUI_CMD"
      echo "Running GUI tests with xvfb (legacy FREECAD_GUI_CMD)..."
    else
      echo "Running GUI tests with xvfb [FreeCAD $version]..."
    fi
    
    if [[ ! -x "$freecad_cmd" ]]; then
      echo "Skipping GUI tests for $version: $freecad_cmd not found or not executable" >&2
      continue
    fi

    ensure_plugin_symlink "$version"
    # Use -a for auto display selection, -e to capture errors, set Qt to use X11 via xvfb
    GUI_ERROR_FILE=$(mktemp)
    if ! xvfb-run -a -e "$GUI_ERROR_FILE" -s "-screen 0 1280x1024x24" env QT_QPA_PLATFORM=xcb "$freecad_cmd" -t freecad.gridfinity_workbench.test_gridfinity; then
      echo "GUI tests failed. Xvfb/FreeCAD errors:"
      cat "$GUI_ERROR_FILE"
      rm -f "$GUI_ERROR_FILE"
      exit 1
    fi
    ls -la "$GUI_ERROR_FILE"
  done
fi

if [[ "$RUN_INTEGRATION" == "true" ]]; then
  ran_any=false
  
  for version in $(get_versions_to_test); do
    freecad_cmd="$(get_freecad_cmd "$version")"
    
    if [[ ! -x "$freecad_cmd" ]]; then
      echo "Skipping integration tests for $version: $freecad_cmd not found or not executable"
      continue
    fi
    
    echo "Running integration tests [FreeCAD $version]: $freecad_cmd"
    if [[ -n "$TEST_NAME" ]]; then
      FREECAD_CMD="$freecad_cmd" RUN_BENCHMARKS="$RUN_BENCHMARKS" python -m unittest "tests.test_integration_freecad_cmd.FreeCADCmdIntegrationTest.$TEST_NAME"
    else
      FREECAD_CMD="$freecad_cmd" RUN_BENCHMARKS="$RUN_BENCHMARKS" python -m unittest tests.test_integration_freecad_cmd
    fi
    ran_any=true
  done
  
  # Fall back to legacy FREECAD_CMDS/FREECAD_CMD if no version-specific commands worked
  if [[ "$ran_any" == "false" ]]; then
    if [[ -z "${FREECAD_CMDS:-}" ]]; then
      if [[ -n "${FREECAD_CMD:-}" ]]; then
        FREECAD_CMDS="$FREECAD_CMD"
      else
        echo "No FreeCAD command configured. Set FREECAD_1_1_CMD, FREECAD_LINK_CMD, or legacy FREECAD_CMD in .env" >&2
        exit 1
      fi
    fi

    for cmd in $FREECAD_CMDS; do
      if [[ ! -x "$cmd" ]]; then
        echo "Skipping missing FreeCAD command: $cmd"
        continue
      fi
      echo "Running integration tests (legacy): $cmd"
      if [[ -n "$TEST_NAME" ]]; then
        FREECAD_CMD="$cmd" RUN_BENCHMARKS="$RUN_BENCHMARKS" python -m unittest "tests.test_integration_freecad_cmd.FreeCADCmdIntegrationTest.$TEST_NAME"
      else
        FREECAD_CMD="$cmd" RUN_BENCHMARKS="$RUN_BENCHMARKS" python -m unittest tests.test_integration_freecad_cmd
      fi
    done
  fi
fi

echo "All tests finished."
