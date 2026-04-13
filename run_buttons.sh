#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export PYTHONPATH="src:reference/hailo-apps"
export hailort_version="5.2.0"

exec .venv/bin/python -m buttons.__main__
