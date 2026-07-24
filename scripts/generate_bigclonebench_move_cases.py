#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
BCE_DIR = REPO_ROOT / "test" / "BigCloneEval"
DEFAULT_OUT = REPO_ROOT / "test" / "e2e_bigclonebench" / "cases"


@dataclass(frozen=True)
class CloneRow:
    function_id_one: int
    type1: str
    name1: str
    startline1: int
    endline1: int
    function_id_two: int
    type2: str
    name2: str
    startline2: int
    endline2: int
    syntactic_type: int
    similarity_line: float
    similarity_token: float
    min_tokens: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate synthetic srcMove cases from BigCloneBench clone pairs."
    )
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--syntactic-type", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--min-tokens", type=int, default=50)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def h2_shell(sql: str) -> str:
    db_base = (BCE_DIR / "bigclonebenchdb" / "bcb").resolve()
    h2_jar = BCE_DIR / "libs" / "h2-1.3.176.jar"
    cmd = [
        "java",
        "-cp",
        str(h2_jar),
        "org.h2.tools.Shell",
        "-url",
        f"jdbc:h2:{db_base};IFEXISTS=TRUE",
        "-user",
        "sa",
        "-password",
        "",
        "-sql",
        sql,
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout


def parse_h2_table(output: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    useful = [line for line in output.splitlines() if "|" in line]
    if not useful:
        return rows

    headers = [part.strip().lower() for part in useful[0].split("|")]
    for line in useful[1:]:
        if line.startswith("("):
            continue
        values = [part.strip() for part in line.split("|")]
        if len(values) != len(headers):
            continue
        rows.append(dict(zip(headers, values)))
    return rows


def load_clone_rows(limit: int, syntactic_type: int, min_tokens: int) -> list[CloneRow]:
    sql = f"""
SELECT
  c.function_id_one,
  f1.type AS type1, f1.name AS name1, f1.startline AS startline1, f1.endline AS endline1,
  c.function_id_two,
  f2.type AS type2, f2.name AS name2, f2.startline AS startline2, f2.endline AS endline2,
  c.syntactic_type, c.similarity_line, c.similarity_token, c.min_tokens
FROM clones c
JOIN functions f1 ON f1.id = c.function_id_one
JOIN functions f2 ON f2.id = c.function_id_two
WHERE c.syntactic_type = {syntactic_type}
  AND c.min_tokens >= {min_tokens}
  AND c.internal = FALSE
ORDER BY c.syntactic_type, c.functionality_id, c.function_id_one, c.function_id_two
LIMIT {limit}
"""
    rows = parse_h2_table(h2_shell(sql))
    return [
        CloneRow(
            function_id_one=int(row["function_id_one"]),
            type1=row["type1"],
            name1=row["name1"],
            startline1=int(row["startline1"]),
            endline1=int(row["endline1"]),
            function_id_two=int(row["function_id_two"]),
            type2=row["type2"],
            name2=row["name2"],
            startline2=int(row["startline2"]),
            endline2=int(row["endline2"]),
            syntactic_type=int(row["syntactic_type"]),
            similarity_line=float(row["similarity_line"]),
            similarity_token=float(row["similarity_token"]),
            min_tokens=int(row["min_tokens"]),
        )
        for row in rows
    ]


def extract_lines(path: Path, startline: int, endline: int) -> str:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    fragment = lines[startline - 1 : endline]
    return "\n".join(fragment).rstrip() + "\n"


def indent_fragment(fragment: str) -> str:
    return "\n".join(f"  {line}" if line else "" for line in fragment.splitlines()) + "\n"


def append_block(lines: list[str], block: str) -> tuple[int, int]:
    block_lines = block.rstrip("\n").splitlines()
    start_line = len(lines) + 1
    lines.extend(block_lines)
    return start_line, len(lines)


def source_path(kind: str, name: str) -> Path:
    return BCE_DIR / "ijadataset" / kind / name


def write_case(case_dir: Path, row: CloneRow) -> None:
    src1 = source_path(row.type1, row.name1)
    src2 = source_path(row.type2, row.name2)
    fragment1 = extract_lines(src1, row.startline1, row.endline1)
    fragment2 = extract_lines(src2, row.startline2, row.endline2)

    class_name = f"BCBMove{row.function_id_one}_{row.function_id_two}"
    original_lines: list[str] = []
    append_block(
        original_lines,
        f"""public class {class_name} {{
  public void beforeAnchor() {{
    System.out.println("before");
  }}
""",
    )
    original_start, original_end = append_block(original_lines, indent_fragment(fragment1))
    append_block(
        original_lines,
        """
  public void middleAnchor() {
    System.out.println("middle");
  }

  public void targetAnchor() {
    System.out.println("target");
  }

  public void afterAnchor() {
    System.out.println("after");
  }
}""",
    )

    modified_lines: list[str] = []
    append_block(
        modified_lines,
        f"""public class {class_name} {{
  public void beforeAnchor() {{
    System.out.println("before");
  }}

  public void middleAnchor() {{
    System.out.println("middle");
  }}

  public void targetAnchor() {{
    System.out.println("target");
  }}

  public void afterAnchor() {{
    System.out.println("after");
  }}
""",
    )
    modified_start, modified_end = append_block(modified_lines, indent_fragment(fragment2))
    append_block(modified_lines, "}")

    original = "\n".join(original_lines) + "\n"
    modified = "\n".join(modified_lines) + "\n"

    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "original.java").write_text(original, encoding="utf-8")
    (case_dir / "modified.java").write_text(modified, encoding="utf-8")
    metadata = {
        "source": "BigCloneBench",
        "function_id_one": row.function_id_one,
        "function_id_two": row.function_id_two,
        "fragment_one": {
            "file": str(src1.relative_to(BCE_DIR)),
            "startline": row.startline1,
            "endline": row.endline1,
            "text": fragment1,
        },
        "fragment_two": {
            "file": str(src2.relative_to(BCE_DIR)),
            "startline": row.startline2,
            "endline": row.endline2,
            "text": fragment2,
        },
        "syntactic_type": row.syntactic_type,
        "similarity_line": row.similarity_line,
        "similarity_token": row.similarity_token,
        "min_tokens": row.min_tokens,
        "expected": {
            "move_count": 1,
            "from_raw_text": fragment1,
            "to_raw_text": fragment2,
            "from_start_line": original_start,
            "from_end_line": original_end,
            "to_start_line": modified_start,
            "to_end_line": modified_end,
        },
    }
    (case_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
    )


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = load_clone_rows(args.limit, args.syntactic_type, args.min_tokens)

    written = 0
    skipped = 0
    prefix = f"bcb_t{args.syntactic_type}"
    for index, row in enumerate(rows, start=1):
        case_dir = args.out_dir / f"{prefix}_{index:06d}"
        if case_dir.exists() and not args.overwrite:
            skipped += 1
            continue
        write_case(case_dir, row)
        written += 1

    print(f"written={written} skipped={skipped} out_dir={args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
