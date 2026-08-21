#!/usr/bin/env python3
"""Print the move-policy catalogs as compact before/after source examples."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TESTS_ROOT = SCRIPT_DIR.parents[1]
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from support.cases import CaseDefinitionError, PolicyCaseSpec, discover_policy_cases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List move-policy source examples.")
    parser.add_argument(
        "--catalog",
        choices=("main", "false-positive", "real-move", "contextual", "all"),
        default="main",
    )
    parser.add_argument("--case", action="append", dest="cases", metavar="ID")
    return parser.parse_args()


def _indent(lines: list[str], prefix: str = "    ") -> list[str]:
    return [f"{prefix}{line}" if line else prefix.rstrip() for line in lines]


def _render_file_map(files: dict[str, list[str]]) -> list[str]:
    rendered: list[str] = []
    for index, (filename, lines) in enumerate(files.items()):
        if index:
            rendered.append("")
        rendered.append(f"    {filename}")
        rendered.extend(_indent(lines, "        "))
    return rendered


def render_case(case: PolicyCaseSpec) -> str:
    definition = case.definition
    lines = [case.name]
    if case.scenario == "transfer":
        from_lines = definition["from_lines"]
        to_lines = definition["to_lines"]
        if len(from_lines) == 1 and len(to_lines) == 1:
            lines.append(f"original:  {from_lines[0]}")
            lines.append(f"modified:  {to_lines[0]}")
        else:
            lines.append("original:")
            lines.extend(_indent(from_lines))
            lines.append("modified:")
            lines.extend(_indent(to_lines))
    else:
        lines.append("original:")
        lines.extend(_render_file_map(definition["original_files"]))
        lines.append("modified:")
        lines.extend(_render_file_map(definition["modified_files"]))
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    try:
        cases = discover_policy_cases()
    except CaseDefinitionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.catalog == "main":
        cases = [case for case in cases if not case.contextual]
    elif args.catalog == "false-positive":
        cases = [case for case in cases if not case.expect_move and not case.contextual]
    elif args.catalog == "real-move":
        cases = [case for case in cases if case.expect_move and not case.contextual]
    elif args.catalog == "contextual":
        cases = [case for case in cases if case.contextual]

    if args.cases:
        requested = set(args.cases)
        available = {case.name for case in cases}
        unknown = sorted(requested - available)
        if unknown:
            print(f"error: unknown case(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        cases = [case for case in cases if case.name in requested]

    sections = (
        ("FALSE POSITIVES", [case for case in cases if not case.expect_move]),
        ("REAL MOVES / FALSE-NEGATIVE CHECKS", [case for case in cases if case.expect_move]),
    )
    rendered_sections = []
    for heading, section_cases in sections:
        if not section_cases:
            continue
        body = "\n\n".join(render_case(case) for case in section_cases)
        rendered_sections.append(f"{heading}\n\n{body}")

    print("\n\n".join(rendered_sections))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
