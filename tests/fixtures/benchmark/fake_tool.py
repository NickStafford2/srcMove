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
    if "--results-only" in arguments:
        return None
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
        if destination is not None and "--results-only" not in arguments:
            write_xml(destination, archive=outcome == "valid-archive")
        if "--results" in arguments:
            results = Path(arguments[arguments.index("--results") + 1])
            # Standalone copied fake tool: keep a complete schema-3 empty result.
            import json
            kinds = {kind: 0 for kind in ('type1', 'type2c', 'type3')}
            payload = {
                'results_schema_version': 3,
                'summary': {'output_item_count': 0, 'atomic_move_group_count': 0,
                            'sequence_move_group_count': 0, 'pair_capacity': 0,
                            'endpoint_count': 0, 'atomic_content_relationships': kinds,
                            'output_content_relationships': kinds},
                'atomic_move_groups': [], 'output_items': [],
                'configuration': {'min_granularity': 'statement', 'sequence_policy': 'ordered_adjacent_v1'},
                'pipeline_statistics': {'srcdiff_region_count': 0, 'grouped_candidate_entry_count': 0,
                                        'processing_group_count': 0, 'processing_group_kinds': {
                                            kind: 0 for kind in ('move_1_to_1','moves_many','delete_only','insert_only','copy_or_repeat','ambiguous')}},
                'xpath_context': {'document': 'input_srcdiff', 'convention': 'srcreader_file_units_v1',
                                  'namespaces': {'src': 'http://www.srcML.org/srcML/src', 'diff': 'http://www.srcML.org/srcDiff'}},
            }
            results.write_text(json.dumps(payload) + '\n', encoding='utf-8')
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
