#!/usr/bin/env bash
set -euo pipefail

echo "=== Configuring project ==="
cmake -S . -B build -G Ninja

echo "=== Building with Ninja ==="
ninja -C build

echo "=== Running end-to-end tests ==="
python test/archives/run_end_to_end.py

echo "=== Done ==="
