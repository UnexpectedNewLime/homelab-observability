#!/bin/sh
# Compatibility entry point; Python 3 is required (provided by config-generator).
set -eu
exec python3 "$(dirname "$0")/generate-config.py" "$@"
