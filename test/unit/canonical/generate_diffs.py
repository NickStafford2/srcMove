#!/usr/bin/env python3
from __future__ import annotations

import itertools
import sys
from pathlib import Path


def main() -> int:
    script_path = Path(__file__).resolve()
    canonical_dir = script_path.parent
    project_root = canonical_dir.parent.parent
    test_root = project_root / "test"
    if str(test_root) not in sys.path:
        sys.path.insert(0, str(test_root))

    from tooling import find_srcdiff, run_command

    src_dir = canonical_dir / "sources"
    out_dir = canonical_dir / "generated"

    srcdiff = find_srcdiff(project_root)
    if srcdiff is None:
        print("error: 'srcdiff' was not found on PATH", file=sys.stderr)
        return 1

    same_files = [
        "same_01.cpp",
        "same_02.cpp",
        "same_03.cpp",
    ]

    diff_files = [
        "diff_name.cpp",
        "diff_literal.cpp",
        "diff_decl.cpp",
    ]

    all_files = same_files + diff_files

    if not src_dir.is_dir():
        print(f"error: source directory does not exist: {src_dir}", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)

    for old_xml in out_dir.glob("*.xml"):
        old_xml.unlink()

    generated_count = 0

    for left_name, right_name in itertools.combinations(all_files, 2):
        left_path = src_dir / left_name
        right_path = src_dir / right_name

        if not left_path.is_file():
            print(f"error: missing source file: {left_path}", file=sys.stderr)
            return 1
        if not right_path.is_file():
            print(f"error: missing source file: {right_path}", file=sys.stderr)
            return 1

        out_name = f"{left_path.stem}__{right_path.stem}.xml"
        out_path = out_dir / out_name

        cmd = [
            str(srcdiff),
            str(left_path),
            str(right_path),
            "-o",
            str(out_path),
            "--position",
        ]

        print(f"Generating {out_path.relative_to(project_root)}")
        result = run_command(cmd, capture_output=False)

        if result.returncode != 0:
            print(
                f"error: srcdiff failed for {left_name} vs {right_name}",
                file=sys.stderr,
            )
            return result.returncode

        generated_count += 1

    print(f"Done. Generated {generated_count} XML files in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
