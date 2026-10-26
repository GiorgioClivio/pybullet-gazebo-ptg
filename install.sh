#!/usr/bin/env sh
# Install PTG's dependencies in a local virtual environment (.venv) and run the self-check.
#   ./install.sh              # python3 from PATH
#   PYTHON=python3.11 ./install.sh
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
"$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
# Where no PyBullet wheel exists for this Python version, pip builds it from source (C++ compiler needed).
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python selfcheck.py
