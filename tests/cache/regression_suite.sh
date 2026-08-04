#!/usr/bin/env bash
# Regression suite runner for Latarnia unit tests.
# Spec hash is computed from all test entry lines in TESTS.md.
# Run from repo root.
set -euo pipefail

if [ "${ENV:-dev}" = "prod" ]; then
  echo "ERROR: ENV=prod — refusing to run tests against production." >&2
  exit 2
fi

PYTHONPATH=src ENV=dev .venv/bin/python -m pytest tests/unit/ -x -q
