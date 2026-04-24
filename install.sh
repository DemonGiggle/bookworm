#!/usr/bin/env bash
set -euo pipefail

# install.sh - build and install the Bookworm package
# Usage:
#   ./install.sh            # creates .venv, installs package + dev deps
#   RUN_TESTS=1 ./install.sh # also run tests after install
#   VENV_DIR=/path/to/venv ./install.sh # custom venv location

echo "Installing Bookworm (console script: bookworm)"

PYTHON=${PYTHON:-python3}
$PYTHON --version || (echo "python3 required" >&2; exit 1)

VENV_DIR=${VENV_DIR:-.venv}
if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtualenv in $VENV_DIR"
  $PYTHON -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1090
. "$VENV_DIR/bin/activate"

echo "Upgrading pip and installing build deps"
pip install --upgrade pip setuptools wheel

# Install package and development dependencies.
# Prefer a normal install to avoid editable-mode issues on older pip/setuptools setups.
if pip install --no-cache-dir ".[dev]"; then
  echo "Package installed successfully."
else
  echo "Install failed; retrying a minimal install without dev deps."
  pip install --no-cache-dir .
fi

echo "Installed package. The console script 'bookworm' should be available in $VENV_DIR/bin or in the virtualenv PATH."

if [ "${RUN_TESTS:-0}" != "0" ]; then
  echo "Running test suite"
  pytest -q
fi

echo "Install complete. To use:"
echo "  source $VENV_DIR/bin/activate"
echo "  bookworm digest <inputs> --output-dir out --model <model> [--provider-kind openai|ollama|openai-compatible]"

exit 0
