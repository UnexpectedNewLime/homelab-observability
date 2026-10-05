#!/bin/sh
# Equivalent to make test, including hosts without Make installed.
set -eu
cd "$(dirname "$0")/.."
python3 -B -m unittest discover -s tests -p 'test_*.py' -v
python3 -B -m unittest discover -s ntfy-bridge -p 'test_*.py' -v
python3 -B scripts/check-repo-safety.py
python3 -B tests/run-config-tests.py
