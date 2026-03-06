#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CaseResult:
    name: str
    srcdiff_ok: bool
    srcmove_ok: bool
    diff_xml: Path
    diff_new_xml: Path


# def run_command(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
#     print(f"$ {' '.join(cmd)}")
#     return subprocess.run(
#         cmd,
#         cwd=str(cwd),
#         text=True,
#         capture_output=True,
#     )
def run_command(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def print_streams(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(
            result.stderr,
            end="" if result.stderr.endswith("\n") else "\n",
            file=sys.stderr,
        )


def find_case_dirs(archives_root: Path) -> list[Path]:
    case_dirs: list[Path] = []

    for child in sorted(archives_root.iterdir()):
        if not child.is_dir():
            continue

        original_dir = child / "original"
        modified_dir = child / "modified"

        if original_dir.is_dir() and modified_dir.is_dir():
            case_dirs.append(child)

    return case_dirs


def run_case(case_dir: Path, srcdiff_bin: str, srcmove_bin: str) -> CaseResult:
    original_dir = case_dir / "original"
    modified_dir = case_dir / "modified"
    diff_xml = case_dir / "diff.xml"
    diff_new_xml = case_dir / "diff_new.xml"

    print(f"\n=== CASE: {case_dir.name} ===")

    srcdiff_cmd = [
        srcdiff_bin,
        str(original_dir),
        str(modified_dir),
        "-o",
        str(diff_xml),
    ]
    srcdiff_result = run_command(srcdiff_cmd, cwd=case_dir.parent.parent)
    print_streams(srcdiff_result)

    if srcdiff_result.returncode != 0:
        print(f"[FAIL] srcdiff failed for {case_dir.name}", file=sys.stderr)
        return CaseResult(
            name=case_dir.name,
            srcdiff_ok=False,
            srcmove_ok=False,
            diff_xml=diff_xml,
            diff_new_xml=diff_new_xml,
        )

    if not diff_xml.is_file():
        print(f"[FAIL] srcdiff did not create {diff_xml}", file=sys.stderr)
        return CaseResult(
            name=case_dir.name,
            srcdiff_ok=False,
            srcmove_ok=False,
            diff_xml=diff_xml,
            diff_new_xml=diff_new_xml,
        )

    srcmove_cmd = [
        srcmove_bin,
        str(diff_xml),
        str(diff_new_xml),
    ]
    srcmove_result = run_command(srcmove_cmd, cwd=case_dir.parent.parent)
    print_streams(srcmove_result)

    srcmove_ok = srcmove_result.returncode == 0 and diff_new_xml.is_file()
    if not srcmove_ok:
        print(f"[FAIL] srcMove failed for {case_dir.name}", file=sys.stderr)
    else:
        print(f"[PASS] {case_dir.name}")

    return CaseResult(
        name=case_dir.name,
        srcdiff_ok=True,
        srcmove_ok=srcmove_ok,
        diff_xml=diff_xml,
        diff_new_xml=diff_new_xml,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run end-to-end archive tests: srcdiff original/modified, then srcMove on diff.xml."
    )
    parser.add_argument(
        "--archives-root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Path to the test/archives directory",
    )
    parser.add_argument(
        "--srcdiff",
        default="srcdiff",
        help="Path to srcdiff binary",
    )
    parser.add_argument(
        "--srcmove",
        default="srcMove",
        help="Path to srcMove binary",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete existing diff.xml and diff_new.xml before each case",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    archives_root: Path = args.archives_root.resolve()

    if not archives_root.is_dir():
        print(f"error: archives root does not exist: {archives_root}", file=sys.stderr)
        return 1

    if shutil.which(args.srcdiff) is None and not Path(args.srcdiff).exists():
        print(f"error: could not find srcdiff: {args.srcdiff}", file=sys.stderr)
        return 1

    if shutil.which(args.srcmove) is None and not Path(args.srcmove).exists():
        print(f"error: could not find srcMove: {args.srcmove}", file=sys.stderr)
        return 1

    case_dirs = find_case_dirs(archives_root)
    if not case_dirs:
        print(f"error: no archive cases found under {archives_root}", file=sys.stderr)
        return 1

    print(f"Found {len(case_dirs)} archive case(s) in {archives_root}")

    results: list[CaseResult] = []

    for case_dir in case_dirs:
        if args.clean:
            for filename in ("diff.xml", "diff_new.xml"):
                path = case_dir / filename
                if path.exists():
                    path.unlink()

        result = run_case(case_dir, args.srcdiff, args.srcmove)
        results.append(result)

    passed = [r for r in results if r.srcdiff_ok and r.srcmove_ok]
    failed = [r for r in results if not (r.srcdiff_ok and r.srcmove_ok)]

    print("\n=== SUMMARY ===")
    print(f"passed: {len(passed)}")
    print(f"failed: {len(failed)}")

    if failed:
        print("\nFailed cases:")
        for r in failed:
            print(f"  {r.name}: srcdiff_ok={r.srcdiff_ok}, srcmove_ok={r.srcmove_ok}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
