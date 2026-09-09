#!/usr/bin/env bash
# Regression suite runner for Latarnia.
# Spec hash is computed from all "- **test_name:**" entry lines in TESTS.md
# (via `grep -E '^-\s+\*\*test_' TESTS.md | sha256sum`).
# Run from repo root.
set -euo pipefail

if [ "${ENV:-dev}" = "prod" ]; then
  echo "ERROR: ENV=prod — refusing to run tests against production." >&2
  exit 2
fi

# Local Postgres is reachable in this environment, so integration tests
# (tests/integration/) are included rather than skipped. -x is intentionally
# omitted so the full suite runs and every failure is visible in one pass.
PYTHONPATH=src ENV=dev .venv/bin/python -m pytest tests/unit/ tests/integration/ --no-cov -q
