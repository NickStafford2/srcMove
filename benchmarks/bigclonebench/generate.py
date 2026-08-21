#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
TESTS_ROOT = REPO_ROOT / "tests"
for import_root in (REPO_ROOT, TESTS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from benchmarks.progress import ProgressDisplay
from benchmarks.bigclonebench.dataset import (
    extract_lines,
    source_path as resolve_source_path,
)
from support.tooling import format_process_failure, run_command

BCE_DIR = SCRIPT_DIR / "data" / "BigCloneEval"
DEFAULT_OUT = SCRIPT_DIR / "cases"


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def preflight() -> list[str]:
    """Return actionable missing-prerequisite messages without fetching data."""

    required = {
        "BigCloneBench database": BCE_DIR / "bigclonebenchdb" / "bcb.h2.db",
        "H2 driver": BCE_DIR / "libs" / "h2-1.3.176.jar",
    }
    failures = [
        f"{label} not found: {path}"
        for label, path in required.items()
        if not path.exists()
    ]
    ijadataset = BCE_DIR / "ijadataset"
    has_flat_sources = any(
        next((ijadataset / kind).glob("*.java"), None) is not None
        for kind in ("default", "sample", "selected")
    )
    has_reduced_sources = (
        next(ijadataset.glob("bcb_reduced/*/*/*.java"), None) is not None
    )
    if not has_flat_sources and not has_reduced_sources:
        failures.append(
            "IJaDataset Java corpus not found: expected either "
            f"{ijadataset}/{{default,sample,selected}}/*.java or "
            f"{ijadataset}/bcb_reduced/<functionality>/"
            "{default,sample,selected}/*.java"
        )
    if shutil.which("java") is None:
        failures.append("Java executable not found on PATH")
    return failures


def require_preflight() -> None:
    failures = preflight()
    if failures:
        joined = "\n  - ".join(failures)
        raise RuntimeError(
            "BigCloneBench is an external manual prerequisite; it will not be "
            "downloaded automatically.\n  - "
            f"{joined}\nSee benchmarks/bigclonebench/README.md for setup guidance."
        )


def java_identity() -> dict[str, str]:
    executable = shutil.which("java")
    if executable is None:
        return {"status": "unavailable"}
    result = run_command([executable, "-version"])
    version = (result.stderr or result.stdout).strip().splitlines()
    resolved = Path(executable).resolve()
    return {
        "executable": resolved.name,
        "sha256": sha256_file(resolved),
        "version": version[0] if version else "unknown",
    }


@dataclass(frozen=True)
class CloneRow:
    functionality_id: int
    function_id_one: int
    type1: str
    name1: str
    startline1: int
    endline1: int
    project1: str
    function_id_two: int
    type2: str
    name2: str
    startline2: int
    endline2: int
    project2: str
    syntactic_type: int
    similarity_line: float
    similarity_token: float
    min_tokens: int
    min_judges: int | None
    min_confidence: int | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate synthetic srcMove cases from BigCloneBench clone or "
            "known-false-positive pairs."
        )
    )
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument(
        "--candidate-limit",
        type=int,
        help=(
            "Maximum BigCloneBench rows to scan before dedupe. "
            "Defaults to all eligible Type-1/Type-2 or known-false-positive rows "
            "and 10000 Type-3 positive rows."
        ),
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--syntactic-type", type=int, choices=(1, 2, 3))
    selection.add_argument(
        "--known-false-positives",
        action="store_true",
        help="Generate negative cases from BigCloneBench's false_positives table.",
    )
    parser.add_argument("--min-judges", type=int, default=1)
    parser.add_argument("--min-confidence", type=int, default=1)
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
    parser.add_argument(
        "--selection-role",
        choices=("tuning", "evaluation"),
        default="tuning",
        help="Label selected cases as tuning or frozen evaluation data.",
    )
    args = parser.parse_args()
    if args.syntactic_type is None and not args.known_false_positives:
        args.syntactic_type = 2
    return args


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
    proc = run_command(cmd)
    if proc.returncode != 0:
        raise RuntimeError(format_process_failure("BigCloneBench database query", proc))
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


def selection_query(
    limit: int,
    syntactic_type: int | None,
    known_false_positives: bool = False,
    min_judges: int = 1,
    min_confidence: int = 1,
) -> str:
    if known_false_positives:
        return f"""
SELECT
  fp.functionality_id,
  fp.function_id_one,
  f1.type AS type1, f1.name AS name1, f1.startline AS startline1, f1.endline AS endline1,
  f1.project AS project1,
  fp.function_id_two,
  f2.type AS type2, f2.name AS name2, f2.startline AS startline2, f2.endline AS endline2,
  f2.project AS project2,
  fp.syntactic_type, fp.similarity_line, fp.similarity_token,
  fp.min_judges, fp.min_confidence,
  CASE WHEN f1.tokens < f2.tokens THEN f1.tokens ELSE f2.tokens END AS min_tokens
FROM false_positives fp
JOIN functions f1 ON f1.id = fp.function_id_one
JOIN functions f2 ON f2.id = fp.function_id_two
WHERE f1.internal = FALSE
  AND f2.internal = FALSE
  AND fp.min_judges >= {min_judges}
  AND fp.min_confidence >= {min_confidence}
ORDER BY fp.functionality_id, fp.function_id_one, fp.function_id_two
LIMIT {limit}
"""
    if syntactic_type is None:
        raise ValueError("syntactic_type is required for positive clone selection")
    return f"""
SELECT
  c.functionality_id,
  c.function_id_one,
  f1.type AS type1, f1.name AS name1, f1.startline AS startline1, f1.endline AS endline1,
  f1.project AS project1,
  c.function_id_two,
  f2.type AS type2, f2.name AS name2, f2.startline AS startline2, f2.endline AS endline2,
  f2.project AS project2,
  c.syntactic_type, c.similarity_line, c.similarity_token, c.min_tokens,
  c.min_judges, c.min_confidence
FROM clones c
JOIN functions f1 ON f1.id = c.function_id_one
JOIN functions f2 ON f2.id = c.function_id_two
WHERE c.syntactic_type = {syntactic_type}
  AND c.internal = FALSE
ORDER BY c.syntactic_type, c.functionality_id, c.function_id_one, c.function_id_two
LIMIT {limit}
"""


def load_clone_rows(
    limit: int,
    syntactic_type: int | None,
    known_false_positives: bool = False,
    min_judges: int = 1,
    min_confidence: int = 1,
) -> list[CloneRow]:
    rows = parse_h2_table(
        h2_shell(
            selection_query(
                limit,
                syntactic_type,
                known_false_positives,
                min_judges,
                min_confidence,
            )
        )
    )
    return [
        CloneRow(
            functionality_id=int(row["functionality_id"]),
            function_id_one=int(row["function_id_one"]),
            type1=row["type1"],
            name1=row["name1"],
            startline1=int(row["startline1"]),
            endline1=int(row["endline1"]),
            project1=row["project1"],
            function_id_two=int(row["function_id_two"]),
            type2=row["type2"],
            name2=row["name2"],
            startline2=int(row["startline2"]),
            endline2=int(row["endline2"]),
            project2=row["project2"],
            syntactic_type=int(row["syntactic_type"]),
            similarity_line=float(row["similarity_line"]),
            similarity_token=float(row["similarity_token"]),
            min_tokens=int(row["min_tokens"]),
            min_judges=(
                int(row["min_judges"])
                if row.get("min_judges") not in (None, "", "NULL")
                else None
            ),
            min_confidence=(
                int(row["min_confidence"])
                if row.get("min_confidence") not in (None, "", "NULL")
                else None
            ),
        )
        for row in rows
    ]


def indent_fragment(fragment: str) -> str:
    return "\n".join(f"  {line}" if line else "" for line in fragment.splitlines()) + "\n"


def dedent_fragment(fragment: str) -> str:
    return textwrap.dedent(fragment).rstrip() + "\n"


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
        source_path(row.type1, row.name1, row.functionality_id),
        row.startline1,
        row.endline1,
    )
    fragment2 = extract_lines(
        source_path(row.type2, row.name2, row.functionality_id),
        row.startline2,
        row.endline2,
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
    rows: list[CloneRow],
    limit: int,
    dedupe: str,
    text_change: str,
    activity_callback: Callable[[int, int], None] | None = None,
) -> list[CloneRow]:
    selected: list[CloneRow] = []
    if limit <= 0:
        if activity_callback is not None:
            activity_callback(0, 0)
        return selected
    seen: set[str] = set()
    scanned = 0
    for scanned, row in enumerate(rows, start=1):
        if not row_matches_text_change(row, text_change):
            if activity_callback is not None and scanned % 100 == 0:
                activity_callback(len(selected), scanned)
            continue
        if dedupe != "none":
            key = row_dedupe_key(row, dedupe)
            if key is None or key in seen:
                if activity_callback is not None and scanned % 100 == 0:
                    activity_callback(len(selected), scanned)
                continue
            seen.add(key)
        selected.append(row)
        if activity_callback is not None:
            activity_callback(len(selected), scanned)
        if len(selected) >= limit:
            break
    if activity_callback is not None:
        activity_callback(len(selected), scanned)
    return selected


def default_candidate_limit(
    limit: int, syntactic_type: int | None, known_false_positives: bool = False
) -> int:
    if known_false_positives:
        return 1_000_000
    if syntactic_type in (1, 2):
        return 1_000_000
    return max(limit, 10_000)


def append_block(lines: list[str], block: str) -> tuple[int, int]:
    block_lines = block.rstrip("\n").splitlines()
    start_line = len(lines) + 1
    lines.extend(block_lines)
    return start_line, len(lines)


def source_path(kind: str, name: str, functionality_id: int) -> Path:
    return resolve_source_path(BCE_DIR, kind, name, functionality_id)


def build_synthetic_move_sources(
    class_name: str, generated_fragment1: str, generated_fragment2: str
) -> tuple[str, str, tuple[int, int], tuple[int, int]]:
    # Put the payload under different parent shapes so srcDiff exposes it as
    # delete/insert content instead of aligning two synthetic wrappers.
    original_lines: list[str] = []
    append_block(
        original_lines,
        f"""public class {class_name} {{
  private static final int SOURCE_CONTEXT = 100;
""",
    )
    original_range = append_block(original_lines, generated_fragment1)
    append_block(original_lines, "}")

    modified_lines: list[str] = []
    append_block(
        modified_lines,
        f"""public class {class_name} {{
  private static final int SOURCE_CONTEXT = 100;
}}
""",
    )
    modified_range = append_block(modified_lines, generated_fragment2)

    original = "\n".join(original_lines) + "\n"
    modified = "\n".join(modified_lines) + "\n"
    return original, modified, original_range, modified_range


def write_case(case_dir: Path, row: CloneRow, case_kind: str = "positive") -> None:
    src1 = source_path(row.type1, row.name1, row.functionality_id)
    src2 = source_path(row.type2, row.name2, row.functionality_id)
    fragment1 = extract_lines(src1, row.startline1, row.endline1)
    fragment2 = extract_lines(src2, row.startline2, row.endline2)
    generated_fragment1 = indent_fragment(fragment1)
    generated_fragment2 = dedent_fragment(fragment2)

    class_name = f"BCBMove{row.function_id_one}_{row.function_id_two}"
    original, modified, original_range, modified_range = build_synthetic_move_sources(
        class_name, generated_fragment1, generated_fragment2
    )
    original_start, original_end = original_range
    modified_start, modified_end = modified_range

    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "original.java").write_text(original, encoding="utf-8")
    (case_dir / "modified.java").write_text(modified, encoding="utf-8")
    metadata = {
        "source": "BigCloneBench",
        "case_kind": case_kind,
        "function_id_one": row.function_id_one,
        "function_id_two": row.function_id_two,
        "functionality_id": row.functionality_id,
        "project_one": row.project1,
        "project_two": row.project2,
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
        "min_judges": row.min_judges,
        "min_confidence": row.min_confidence,
        "dedupe_key": stable_key(fragment1, fragment2),
        "dedupe": dedupe_metadata(fragment1, fragment2),
        "fragment_relation": fragment_relation(fragment1, fragment2),
        "expected": {
            "move_count": 0 if case_kind == "known_false_positive" else 1,
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
    syntactic_type: int | None,
    case_kind: str,
    dedupe: str,
    text_change: str,
    min_judges: int,
    min_confidence: int,
    limit: int,
    candidate_count: int,
    case_names: list[str],
    candidate_limit: int,
    rows: list[CloneRow],
    selection_role: str,
    known_false_positives: bool = False,
    activity_callback: Callable[[str], None] | None = None,
) -> int:
    database = BCE_DIR / "bigclonebenchdb" / "bcb.h2.db"
    h2_jar = BCE_DIR / "libs" / "h2-1.3.176.jar"
    source_files = sorted(
        {
            source_path(kind, name, row.functionality_id).resolve()
            for row in rows
            for kind, name in ((row.type1, row.name1), (row.type2, row.name2))
        }
    )
    if activity_callback is not None:
        database_gib = database.stat().st_size / (1024**3)
        activity_callback(
            f"hashing BigCloneBench database ({database_gib:.1f} GiB)"
        )
    database_sha256 = sha256_file(database)
    if activity_callback is not None:
        activity_callback("recording H2 and Java identity")
    h2_jar_sha256 = sha256_file(h2_jar)
    java = java_identity()
    if activity_callback is not None:
        activity_callback(
            f"hashing {len(source_files):,} selected source files"
        )
    selected_source_files = [
        {
            "path": path.relative_to(BCE_DIR.resolve()).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in source_files
    ]
    manifest = {
        "schema_version": 4,
        "dataset": "BigCloneBench",
        "case_kind": case_kind,
        "dataset_identity": {
            "database_sha256": database_sha256,
            "h2_jar_sha256": h2_jar_sha256,
            "java": java,
        },
        "syntactic_type": syntactic_type,
        "clone_type": (
            "known_false_positive"
            if known_false_positives
            else f"type{syntactic_type}"
        ),
        "dedupe": dedupe,
        "text_change": text_change,
        **(
            {"min_judges": min_judges, "min_confidence": min_confidence}
            if known_false_positives
            else {}
        ),
        "requested_limit": limit,
        "candidate_count": candidate_count,
        "candidate_limit": candidate_limit,
        "row_count_before_deduplication": candidate_count,
        "distinct_raw_text_pair_count": len(
            {row_dedupe_key(row, "raw-text-pair") for row in rows}
        ),
        "selected_count": len(case_names),
        "functionality_group_count": len({row.functionality_id for row in rows}),
        "cases": case_names,
        "selection": {
            "role": selection_role,
            "method": "ordered_deterministic_convenience_slice",
            "population_claim": "none",
            "eligibility_query": selection_query(
                candidate_limit,
                syntactic_type,
                known_false_positives,
                min_judges,
                min_confidence,
            ).strip(),
            "query_parameters": {
                "syntactic_type": syntactic_type,
                "source_table": (
                    "false_positives" if known_false_positives else "clones"
                ),
                **(
                    {
                        "min_judges": min_judges,
                        "min_confidence": min_confidence,
                    }
                    if known_false_positives
                    else {}
                ),
                "internal": False,
                "candidate_limit": candidate_limit,
            },
            "pair_direction": "fragment_one_deleted_fragment_two_inserted",
            "ordered_selected_row_ids": [
                [row.function_id_one, row.function_id_two] for row in rows
            ],
        },
        "selected_source_files": selected_source_files,
        "versions": {
            "generator_sha256": sha256_file(Path(__file__)),
            "scoring_oracle_sha256": sha256_file(SCRIPT_DIR / "evaluate.py"),
            "semantic_oracle_sha256": sha256_file(SCRIPT_DIR / "adapter.py"),
        },
    }
    manifest_name = (
        "bcb_fp_manifest.json"
        if known_false_positives
        else f"bcb_t{syntactic_type}_manifest.json"
    )
    manifest_path = out_dir / manifest_name
    if activity_callback is not None:
        activity_callback("writing selection manifest")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return len(source_files)


def main() -> int:
    args = parse_args()
    try:
        require_preflight()
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    candidate_limit = args.candidate_limit
    if candidate_limit is None:
        candidate_limit = default_candidate_limit(
            args.limit, args.syntactic_type, args.known_false_positives
        )

    with ProgressDisplay(
        "cases/query",
        detail=f"scanning up to {candidate_limit:,} eligible rows",
    ) as progress:
        candidates = load_clone_rows(
            candidate_limit,
            args.syntactic_type,
            args.known_false_positives,
            args.min_judges,
            args.min_confidence,
        )
        progress.finish(f"found {len(candidates):,} candidates")
    with ProgressDisplay(
        "cases/select",
        total=args.limit,
        detail=f"scanned 0/{len(candidates):,} candidates",
    ) as progress:
        rows = select_rows(
            candidates,
            args.limit,
            args.dedupe,
            args.text_change,
            activity_callback=lambda selected, scanned: progress.update(
                selected,
                detail=f"scanned {scanned:,}/{len(candidates):,} candidates",
            ),
        )
        progress.finish(f"selected {len(rows)} cases")

    written = 0
    skipped = 0
    case_kind = (
        "known_false_positive" if args.known_false_positives else "positive"
    )
    prefix = "bcb_fp" if args.known_false_positives else f"bcb_t{args.syntactic_type}"
    case_names: list[str] = []
    with ProgressDisplay("cases/write", total=len(rows)) as progress:
        for index, row in enumerate(rows, start=1):
            case_dir = args.out_dir / f"{prefix}_{index:06d}"
            case_names.append(case_dir.name)
            progress.update(index - 1, detail=case_dir.name)
            if case_dir.exists() and not args.overwrite:
                skipped += 1
            else:
                write_case(case_dir, row, case_kind)
                written += 1
            progress.update(index, detail=case_dir.name)
        progress.finish(f"wrote {written}, reused {skipped}")

    database = BCE_DIR / "bigclonebenchdb" / "bcb.h2.db"
    database_gib = database.stat().st_size / (1024**3)
    with ProgressDisplay(
        "cases/manifest",
        detail=f"hashing BigCloneBench database ({database_gib:.1f} GiB)",
    ) as progress:
        source_file_count = write_manifest(
            args.out_dir,
            args.syntactic_type,
            case_kind,
            args.dedupe,
            args.text_change,
            args.min_judges,
            args.min_confidence,
            args.limit,
            len(candidates),
            case_names,
            candidate_limit,
            rows,
            args.selection_role,
            args.known_false_positives,
            activity_callback=lambda detail: progress.update(detail=detail),
        )
        progress.finish(
            f"recorded dataset identity and {source_file_count:,} source files"
        )

    print(f"Generated cases: {args.out_dir}")
    print()
    if len(rows) < args.limit:
        print(
            f"warning: requested {args.limit} cases but only selected {len(rows)} "
            f"with dedupe={args.dedupe} text_change={args.text_change}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
