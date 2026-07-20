#!/usr/bin/env bash
set -euo pipefail

# Portable, idempotent Bookworm installer for Linux, macOS, WSL, and other
# Unix-like environments with Bash and Python 3.8 or newer.

usage() {
  cat <<'EOF'
Usage: ./install.sh

Installs Bookworm into an isolated virtual environment and, by default, copies
the generated `bookworm` launcher to ~/.local/bin.

Environment overrides:
  PYTHON=/path/to/python   Python 3.8+ interpreter (default: python3, python, py -3)
  VENV_DIR=/path/to/venv  Virtual environment (default: <repository>/.venv)
  INSTALL_BIN_DIR=/path   Launcher directory (default: ~/.local/bin)
  INSTALL_LAUNCHER=0      Do not install a user-local launcher
  UPGRADE_TOOLS=0         Do not upgrade pip/setuptools/wheel before installation
  RUN_TESTS=1             Install development dependencies and run the test suite
EOF
}

note() {
  printf '%s\n' "==> $*"
}

warn() {
  printf '%s\n' "Warning: $*" >&2
}

die() {
  printf '%s\n' "Error: $*" >&2
  exit 1
}

if [ "$#" -gt 0 ]; then
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      die "Unknown argument: $1"
      ;;
  esac
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$SCRIPT_DIR"
VENV_DIR="${VENV_DIR:-$PROJECT_ROOT/.venv}"
RUN_TESTS="${RUN_TESTS:-0}"
INSTALL_LAUNCHER="${INSTALL_LAUNCHER:-1}"
UPGRADE_TOOLS="${UPGRADE_TOOLS:-1}"

case "$VENV_DIR" in
  /*|[A-Za-z]:[\\/]*) ;;
  *) VENV_DIR="$PROJECT_ROOT/$VENV_DIR" ;;
esac

declare -a PYTHON_CMD
if [ -n "${PYTHON:-}" ]; then
  PYTHON_CMD=("$PYTHON")
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD=(python3)
elif command -v python >/dev/null 2>&1; then
  PYTHON_CMD=(python)
elif command -v py >/dev/null 2>&1; then
  PYTHON_CMD=(py -3)
else
  die "Python 3.8 or newer was not found. Install Python, then rerun this script."
fi

if ! PYTHON_VERSION="$("${PYTHON_CMD[@]}" -c '
import sys

if sys.version_info < (3, 8):
    print(
        "Bookworm requires Python 3.8 or newer; found {}.{}.{}".format(*sys.version_info[:3]),
        file=sys.stderr,
    )
    raise SystemExit(1)
print("{}.{}.{}".format(*sys.version_info[:3]))
')"; then
  die "Set PYTHON to a compatible interpreter and rerun the installer."
fi

note "Installing Bookworm with Python $PYTHON_VERSION"
note "Project: $PROJECT_ROOT"
note "Virtual environment: $VENV_DIR"

CREATED_VENV=0
if [ ! -e "$VENV_DIR" ]; then
  note "Creating virtual environment"
  if ! mkdir -p "$(dirname "$VENV_DIR")"; then
    die "Could not create the parent directory for $VENV_DIR. Choose a writable VENV_DIR."
  fi
  if ! "${PYTHON_CMD[@]}" -m venv "$VENV_DIR"; then
    die "Could not create a virtual environment. Install the Python venv package (often python3-venv on Debian/Ubuntu) and retry."
  fi
  CREATED_VENV=1
fi

locate_venv() {
  if [ -x "$VENV_DIR/bin/python" ]; then
    VENV_PYTHON="$VENV_DIR/bin/python"
    VENV_COMMAND="$VENV_DIR/bin/bookworm"
  elif [ -x "$VENV_DIR/Scripts/python.exe" ]; then
    VENV_PYTHON="$VENV_DIR/Scripts/python.exe"
    VENV_COMMAND="$VENV_DIR/Scripts/bookworm.exe"
  else
    return 1
  fi
}

if ! locate_venv; then
  die "$VENV_DIR exists but is not a usable Python virtual environment. Remove it or choose another VENV_DIR."
fi

if ! VENV_PYTHON_VERSION="$("$VENV_PYTHON" -c '
import sys

if sys.version_info < (3, 8):
    raise SystemExit(1)
print("{}.{}.{}".format(*sys.version_info[:3]))
')"; then
  die "The existing virtual environment uses Python older than 3.8. Remove it or choose another VENV_DIR."
fi
if [ "$VENV_PYTHON_VERSION" != "$PYTHON_VERSION" ]; then
  note "Reusing virtual environment Python $VENV_PYTHON_VERSION"
fi

if ! "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
  note "Bootstrapping pip in the virtual environment"
  if ! "$VENV_PYTHON" -m ensurepip --upgrade >/dev/null 2>&1; then
    if [ "$CREATED_VENV" != "0" ]; then
      die "The selected Python created a virtual environment without pip or ensurepip. Install the Python venv package (often python3-venv on Debian/Ubuntu), then retry."
    fi

    VENV_BACKUP="$VENV_DIR.bookworm-backup-$(date +%Y%m%d%H%M%S)-$$"
    warn "The existing virtual environment cannot bootstrap pip."
    note "Preserving it at $VENV_BACKUP and rebuilding $VENV_DIR"
    if ! mv "$VENV_DIR" "$VENV_BACKUP"; then
      die "Could not preserve the broken virtual environment. Choose another writable VENV_DIR."
    fi

    if ! "${PYTHON_CMD[@]}" -m venv "$VENV_DIR" || ! locate_venv || ! "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
      VENV_FAILED="$VENV_DIR.bookworm-failed-$(date +%Y%m%d%H%M%S)-$$"
      if [ -e "$VENV_DIR" ]; then
        mv "$VENV_DIR" "$VENV_FAILED" || true
      fi
      if ! mv "$VENV_BACKUP" "$VENV_DIR"; then
        die "Rebuilding failed, and the original environment could not be restored. It remains at $VENV_BACKUP."
      fi
      die "Rebuilding failed; the original environment was restored. Install Python venv support or choose another PYTHON."
    fi
    note "Virtual environment repaired; the previous environment remains at $VENV_BACKUP"
  fi
fi

if [ "$UPGRADE_TOOLS" != "0" ]; then
  note "Updating Python packaging tools"
  if ! "$VENV_PYTHON" -m pip install --upgrade "pip>=23.1" "setuptools>=68" wheel; then
    die "Could not update Python packaging tools. Check network access, or set UPGRADE_TOOLS=0 when the existing tools already satisfy pyproject.toml."
  fi
fi

INSTALL_TARGET="$PROJECT_ROOT"
if [ "$RUN_TESTS" != "0" ]; then
  INSTALL_TARGET="$PROJECT_ROOT[dev]"
fi

note "Installing Bookworm and its dependencies"
if ! "$VENV_PYTHON" -m pip install --upgrade "$INSTALL_TARGET"; then
  die "Package installation failed. Check the network error above and confirm that this Python version is supported."
fi

if ! "$VENV_PYTHON" -c 'import digester'; then
  die "Installation completed without an importable digester package."
fi
if [ ! -f "$VENV_COMMAND" ]; then
  die "Installation completed without creating the bookworm console command."
fi

INSTALLED_COMMAND="$VENV_COMMAND"
if [ "$INSTALL_LAUNCHER" != "0" ]; then
  if [ -z "${INSTALL_BIN_DIR:-}" ]; then
    if [ -n "${HOME:-}" ]; then
      INSTALL_BIN_DIR="$HOME/.local/bin"
    else
      warn "HOME is unset, so no user-local launcher was installed."
      INSTALL_BIN_DIR=""
    fi
  fi

  if [ -n "$INSTALL_BIN_DIR" ]; then
    note "Installing launcher in $INSTALL_BIN_DIR"
    if ! mkdir -p "$INSTALL_BIN_DIR"; then
      die "Could not create $INSTALL_BIN_DIR. Choose a writable INSTALL_BIN_DIR or set INSTALL_LAUNCHER=0."
    fi
    case "$VENV_COMMAND" in
      *.exe) LAUNCHER_PATH="$INSTALL_BIN_DIR/bookworm.exe" ;;
      *) LAUNCHER_PATH="$INSTALL_BIN_DIR/bookworm" ;;
    esac
    TEMP_LAUNCHER="$LAUNCHER_PATH.tmp.$$"
    trap 'rm -f "${TEMP_LAUNCHER:-}"' EXIT
    cp "$VENV_COMMAND" "$TEMP_LAUNCHER"
    chmod 755 "$TEMP_LAUNCHER"
    mv -f "$TEMP_LAUNCHER" "$LAUNCHER_PATH"
    trap - EXIT
    INSTALLED_COMMAND="$LAUNCHER_PATH"

    case ":${PATH:-}:" in
      *:"$INSTALL_BIN_DIR":*) ;;
      *)
        warn "$INSTALL_BIN_DIR is not on PATH. Add this line to your shell profile:"
        warn "  export PATH=\"$INSTALL_BIN_DIR:\$PATH\""
        ;;
    esac
  fi
fi

if [ "$RUN_TESTS" != "0" ]; then
  note "Running test suite"
  (
    cd "$PROJECT_ROOT"
    "$VENV_PYTHON" -m pytest -q
  )
fi

note "Installation complete"
printf '%s\n' "Bookworm command: $INSTALLED_COMMAND"
if [ -n "${HOME:-}" ]; then
  printf '%s\n' "Optional config: $HOME/.config/bookworm/config.toml"
fi
printf '%s\n' "Try: bookworm digest <inputs> --output-dir out --model <model>"
