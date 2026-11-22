#!/usr/bin/env bash
# macOS / Linux launcher. Usage:  ./run.sh setup   |   ./run.sh demo   |   ./run.sh evaluate
set -e
cd "$(dirname "$0")"
if [ ! -f .venv/installed.ok ]; then
  echo "[setup] Creating Python virtual environment in .venv ..."
  [ -x .venv/bin/python ] || python3 -m venv .venv
  echo "[setup] Installing packages - first time only, this can take a few minutes ..."
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  echo ok > .venv/installed.ok
fi
.venv/bin/python run.py "${@:-demo}"
