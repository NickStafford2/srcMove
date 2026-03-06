#!/usr/bin/env bash
set -e

python3 test/canonical/generate_diffs.py

cmake -S . -B build
ninja -C build

cd build
ctest --output-on-failure -V
