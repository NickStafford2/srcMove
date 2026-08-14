#!/usr/bin/env python3
"""Compatibility wrapper for the renamed unified test entry point."""

from __future__ import annotations

import sys
from pathlib import Path


TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from run import main


if __name__ == "__main__":
    raise SystemExit(main())
