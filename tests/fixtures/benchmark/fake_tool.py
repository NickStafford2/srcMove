#!/usr/bin/env python3
"""Deterministic fake executable for offline orchestration tests."""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "outcome",
        choices=("success", "nonzero", "signal", "timeout", "missing-output"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    print(f"fake-tool outcome={args.outcome}")
    print("fake-tool diagnostic", file=sys.stderr)

    if args.outcome == "success":
        if args.output is not None:
            args.output.write_text("<unit revision=\"1.0.0\"/>\n", encoding="utf-8")
        return 0
    if args.outcome == "nonzero":
        return 23
    if args.outcome == "signal":
        os.kill(os.getpid(), signal.SIGTERM)
    if args.outcome == "timeout":
        time.sleep(60)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
