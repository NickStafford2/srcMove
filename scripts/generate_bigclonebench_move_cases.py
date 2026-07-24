#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
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
    parser.add_argument(
        "--candidate-limit",
        type=int,
        help=(
            "Maximum BigCloneBench rows to scan before dedupe. "
            "Defaults to all eligible Type-1/Type-2 rows and 10000 Type-3 rows."
        ),
    )
    parser.add_argument("--syntactic-type", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--min-tokens", type=int, default=50)
    parser.add_argument(
        "--dedupe",
        choices=("none", "raw-text-pair", "trimmed-text-pair"),
        default="raw-text-pair",
        help=(
            "Select unique generated cases by extracted fragment text. "
            "raw-text-pair preserves whitespace/comment differences. Default: raw-text-pair."
        ),
    )
    parser.add_argument(
        "--text-change",
        choices=("any", "raw-different"),
        default="any",
        help=(
            "Filter selected pairs by whether the two extracted fragments differ "
            "as raw text. Default: any."
        ),
    )
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


def trimmed_text(value: str) -> str:
    # This is only a local reporting key. It is not BigCloneBench's Type-1/Type-2
    # normalization, and it must not be the default Type-1 dedupe criterion.
    lines = value.strip().splitlines()
    return "\n".join(line.rstrip() for line in lines)


def stable_key(*parts: str) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8", errors="replace")
        hasher.update(len(encoded).to_bytes(8, byteorder="big"))
        hasher.update(encoded)
    return hasher.hexdigest()


def dedupe_metadata(fragment1: str, fragment2: str) -> dict[str, str]:
    trimmed_fragment1 = trimmed_text(fragment1)
    trimmed_fragment2 = trimmed_text(fragment2)
    return {
        # Raw text preserves Type-1 whitespace/comment differences. Those
        # differences are part of what srcMove should be tested against.
        "raw_text_pair_key": stable_key(fragment1, fragment2),
        "trimmed_text_pair_key": stable_key(trimmed_fragment1, trimmed_fragment2),
        "raw_fragment_one_key": stable_key(fragment1),
        "raw_fragment_two_key": stable_key(fragment2),
        "trimmed_fragment_one_key": stable_key(trimmed_fragment1),
        "trimmed_fragment_two_key": stable_key(trimmed_fragment2),
    }


def fragment_relation(fragment1: str, fragment2: str) -> dict[str, bool]:
    return {
        "raw_text_identical": fragment1 == fragment2,
        "trimmed_text_identical": trimmed_text(fragment1) == trimmed_text(fragment2),
    }


def row_fragments(row: CloneRow) -> tuple[str, str]:
    fragment1 = extract_lines(
        source_path(row.type1, row.name1), row.startline1, row.endline1
    )
    fragment2 = extract_lines(
        source_path(row.type2, row.name2), row.startline2, row.endline2
    )
    return fragment1, fragment2


def row_dedupe_key(row: CloneRow, dedupe: str) -> str | None:
    if dedupe == "none":
        return None

    fragment1, fragment2 = row_fragments(row)

    # Prefer raw text for generated Type-1 cases: BigCloneBench Type-1 allows
    # formatting/comment variation, and collapsing that away would erase useful
    # move-detection tests.
    if dedupe == "raw-text-pair":
        return stable_key(fragment1, fragment2)
    if dedupe == "trimmed-text-pair":
        return stable_key(trimmed_text(fragment1), trimmed_text(fragment2))

    raise ValueError(f"unsupported dedupe mode: {dedupe}")


def row_matches_text_change(row: CloneRow, text_change: str) -> bool:
    if text_change == "any":
        return True

    fragment1, fragment2 = row_fragments(row)
    if text_change == "raw-different":
        return fragment1 != fragment2

    raise ValueError(f"unsupported text-change mode: {text_change}")


def select_rows(
    rows: list[CloneRow], limit: int, dedupe: str, text_change: str
) -> list[CloneRow]:
    if dedupe == "none":
        return [row for row in rows if row_matches_text_change(row, text_change)][:limit]

    selected: list[CloneRow] = []
    seen: set[str] = set()
    for row in rows:
        if not row_matches_text_change(row, text_change):
            continue
        key = row_dedupe_key(row, dedupe)
        if key is None or key in seen:
            continue
        seen.add(key)
        selected.append(row)
        if len(selected) >= limit:
            break
    return selected


def default_candidate_limit(limit: int, syntactic_type: int) -> int:
    if syntactic_type in (1, 2):
        return 1_000_000
    return max(limit, 10_000)


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
    generated_fragment1 = indent_fragment(fragment1)
    generated_fragment2 = indent_fragment(fragment2)

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
    original_start, original_end = append_block(original_lines, generated_fragment1)
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
    modified_start, modified_end = append_block(modified_lines, generated_fragment2)
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
        "dedupe_key": stable_key(fragment1, fragment2),
        "dedupe": dedupe_metadata(fragment1, fragment2),
        "fragment_relation": fragment_relation(fragment1, fragment2),
        "expected": {
            "move_count": 1,
            "from_raw_text": fragment1,
            "to_raw_text": fragment2,
            "from_generated_text": generated_fragment1,
            "to_generated_text": generated_fragment2,
            "from_start_line": original_start,
            "from_end_line": original_end,
            "to_start_line": modified_start,
            "to_end_line": modified_end,
        },
    }
    (case_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
    )


def write_manifest(
    out_dir: Path,
    syntactic_type: int,
    dedupe: str,
    text_change: str,
    min_tokens: int,
    limit: int,
    candidate_count: int,
    case_names: list[str],
) -> None:
    manifest = {
        "syntactic_type": syntactic_type,
        "clone_type": f"type{syntactic_type}",
        "dedupe": dedupe,
        "text_change": text_change,
        "min_tokens": min_tokens,
        "requested_limit": limit,
        "candidate_count": candidate_count,
        "selected_count": len(case_names),
        "cases": case_names,
    }
    manifest_path = out_dir / f"bcb_t{syntactic_type}_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    candidate_limit = args.candidate_limit
    if candidate_limit is None:
        candidate_limit = default_candidate_limit(args.limit, args.syntactic_type)

    candidates = load_clone_rows(candidate_limit, args.syntactic_type, args.min_tokens)
    rows = select_rows(candidates, args.limit, args.dedupe, args.text_change)

    written = 0
    skipped = 0
    prefix = f"bcb_t{args.syntactic_type}"
    case_names: list[str] = []
    for index, row in enumerate(rows, start=1):
        case_dir = args.out_dir / f"{prefix}_{index:06d}"
        case_names.append(case_dir.name)
        if case_dir.exists() and not args.overwrite:
            skipped += 1
            continue
        write_case(case_dir, row)
        written += 1

    write_manifest(
        args.out_dir,
        args.syntactic_type,
        args.dedupe,
        args.text_change,
        args.min_tokens,
        args.limit,
        len(candidates),
        case_names,
    )

    print(
        f"written={written} skipped={skipped} selected={len(rows)} "
        f"candidates={len(candidates)} dedupe={args.dedupe} "
        f"text_change={args.text_change} out_dir={args.out_dir}"
    )
    if len(rows) < args.limit:
        print(
            f"warning: requested {args.limit} cases but only selected {len(rows)} "
            f"with dedupe={args.dedupe} text_change={args.text_change}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
