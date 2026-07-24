#!/usr/bin/env bash
set -euo pipefail

python3 test/run_all.py --build "$@"
