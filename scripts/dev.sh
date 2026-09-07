#!/usr/bin/env sh
set -eu
python -m pip install -e ".[dev]"
pytest -q

