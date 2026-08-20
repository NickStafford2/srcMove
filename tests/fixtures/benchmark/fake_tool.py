#!/usr/bin/env python3
"""Deterministic fake executable for offline orchestration tests."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


OUTCOMES = {
    "success",
    "valid-single",
    "valid-archive",
    "nonzero",
    "nonzero-valid",
    "signal",
    "sigkill",
    "timeout",
    "timeout-tree",
    "missing-output",
    "empty-output",
    "malformed",
    "invalid-structure",
}


def selected_outcome(arguments: list[str]) -> tuple[str, list[str]]:
    if arguments and arguments[0] in OUTCOMES:
        return arguments[0], arguments[1:]
    executable_name = Path(sys.argv[0]).name
    for outcome in sorted(OUTCOMES, key=len, reverse=True):
        if outcome in executable_name:
            return outcome, arguments
    return "success", arguments


def output_path(arguments: list[str]) -> Path | None:
    for option in ("--output", "-o"):
        if option in arguments:
            index = arguments.index(option)
            return Path(arguments[index + 1])
    if "--results" in arguments and len(arguments) >= 2:
        return Path(arguments[1])
    return None


def write_xml(path: Path, archive: bool) -> None:
    child = "<unit language='C++'/>" if archive else ""
    path.write_text(
        "<unit xmlns='http://www.srcML.org/srcML/src' "
        "xmlns:diff='http://www.srcML.org/srcDiff' revision='1.0.0'>"
        f"{child}</unit>\n",
        encoding="utf-8",
    )


def main() -> int:
    arguments = sys.argv[1:]
    outcome, arguments = selected_outcome(arguments)
    destination = output_path(arguments)

    print(f"fake-tool outcome={outcome}")
    print("fake-tool diagnostic", file=sys.stderr)

    if outcome in {"success", "valid-single", "valid-archive"}:
        if destination is not None:
            write_xml(destination, archive=outcome == "valid-archive")
        if "--results" in arguments:
            results = Path(arguments[arguments.index("--results") + 1])
            results.write_text('{"move_count": 0}\n', encoding="utf-8")
        return 0
    if outcome == "nonzero-valid":
        if destination is not None:
            write_xml(destination, archive=True)
        return 23
    if outcome == "nonzero":
        return 23
    if outcome == "signal":
        os.kill(os.getpid(), signal.SIGTERM)
    if outcome == "sigkill":
        os.kill(os.getpid(), signal.SIGKILL)
    if outcome == "timeout":
        time.sleep(60)
        return 0
    if outcome == "timeout-tree":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal,time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "time.sleep(60)",
            ]
        )
        time.sleep(60)
        return 0
    if outcome == "empty-output" and destination is not None:
        destination.write_bytes(b"")
    if outcome == "malformed" and destination is not None:
        destination.write_text("<unit>", encoding="utf-8")
    if outcome == "invalid-structure" and destination is not None:
        destination.write_text("<not-unit/>", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
