#!/usr/bin/env python3
"""Compile BigCloneBench into a reusable SQLite catalog and fragment store."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
TESTS_ROOT = REPO_ROOT / "tests"
for import_root in (REPO_ROOT, TESTS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from benchmarks.bigclonebench.compiled import (
    compile_exports,
    find_reusable_compiled_dataset,
    load_compiled_dataset,
    record_compiled_dataset,
)
from benchmarks.bigclonebench.generate import BCE_DIR, java_identity, preflight
from benchmarks.progress import ProgressDisplay
from support.tooling import format_process_failure, run_command


DEFAULT_DATA_ROOT = REPO_ROOT / "benchmark-data"


def _limit_clause(limit_per_kind: int | None) -> str:
    if limit_per_kind is None:
        return ""
    if limit_per_kind <= 0:
        raise ValueError("limit-per-kind must be positive")
    return f"\nLIMIT {limit_per_kind}"


def _positive_query(limit_per_kind: int | None) -> str:
    return f"""
SELECT
  c.functionality_id,
  c.function_id_one,
  f1.type AS typeone, f1.name AS nameone,
  f1.startline AS startlineone, f1.endline AS endlineone,
  f1.project AS projectone, f1.tokens AS tokensone, f1.internal AS internalone,
  c.function_id_two,
  f2.type AS typetwo, f2.name AS nametwo,
  f2.startline AS startlinetwo, f2.endline AS endlinetwo,
  f2.project AS projecttwo, f2.tokens AS tokenstwo, f2.internal AS internaltwo,
  c.type AS pair_type, c.syntactic_type, c.similarity_line, c.similarity_token,
  c.min_size, c.max_size, c.min_pretty_size, c.max_pretty_size,
  c.min_tokens, c.max_tokens, c.min_judges, c.min_confidence,
  c.internal AS pair_internal
FROM clones c
JOIN functions f1 ON f1.id = c.function_id_one
JOIN functions f2 ON f2.id = c.function_id_two
WHERE c.internal = FALSE
ORDER BY c.syntactic_type, c.functionality_id, c.function_id_one, c.function_id_two
{_limit_clause(limit_per_kind)}
""".strip()


def _false_positive_query(limit_per_kind: int | None) -> str:
    return f"""
SELECT
  fp.functionality_id,
  fp.function_id_one,
  f1.type AS typeone, f1.name AS nameone,
  f1.startline AS startlineone, f1.endline AS endlineone,
  f1.project AS projectone, f1.tokens AS tokensone, f1.internal AS internalone,
  fp.function_id_two,
  f2.type AS typetwo, f2.name AS nametwo,
  f2.startline AS startlinetwo, f2.endline AS endlinetwo,
  f2.project AS projecttwo, f2.tokens AS tokenstwo, f2.internal AS internaltwo,
  fp.type AS pair_type, fp.syntactic_type,
  fp.similarity_line, fp.similarity_token,
  NULL AS min_size, NULL AS max_size,
  NULL AS min_pretty_size, NULL AS max_pretty_size,
  CASE WHEN f1.tokens < f2.tokens THEN f1.tokens ELSE f2.tokens END AS min_tokens,
  CASE WHEN f1.tokens > f2.tokens THEN f1.tokens ELSE f2.tokens END AS max_tokens,
  fp.min_judges, fp.min_confidence, FALSE AS pair_internal
FROM false_positives fp
JOIN functions f1 ON f1.id = fp.function_id_one
JOIN functions f2 ON f2.id = fp.function_id_two
WHERE f1.internal = FALSE AND f2.internal = FALSE
ORDER BY fp.syntactic_type, fp.functionality_id,
  fp.function_id_one, fp.function_id_two
{_limit_clause(limit_per_kind)}
""".strip()


def _csvwrite(path: Path, query: str) -> str:
    path_text = str(path.resolve())
    if "'" in path_text:
        raise ValueError("temporary export path contains an unsupported quote")
    return f"CALL CSVWRITE('{path_text}', '{query.replace(chr(39), chr(39) * 2)}')"


def export_h2(
    export_dir: Path,
    *,
    bce_dir: Path,
    limit_per_kind: int | None,
) -> dict[str, Path]:
    """Export both pair tables in one serial H2 process."""

    export_dir.mkdir(parents=True, exist_ok=True)
    positive = export_dir / "positive.csv"
    false_positive = export_dir / "known_false_positive.csv"
    sql = ";\n".join(
        (
            _csvwrite(positive, _positive_query(limit_per_kind)),
            _csvwrite(false_positive, _false_positive_query(limit_per_kind)),
        )
    )
    db_base = (bce_dir / "bigclonebenchdb" / "bcb").resolve()
    h2_jar = bce_dir / "libs" / "h2-1.3.176.jar"
    command = [
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
    result = run_command(command)
    if result.returncode != 0:
        raise RuntimeError(format_process_failure("BigCloneBench bulk export", result))
    for path in (positive, false_positive):
        if not path.is_file():
            raise RuntimeError(f"H2 did not create expected export: {path}")
    return {"positive": positive, "known_false_positive": false_positive}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--bce-dir", type=Path, default=BCE_DIR)
    stages = parser.add_subparsers(dest="stage", required=True)

    compile_parser = stages.add_parser("compile", help="Compile a local dataset.")
    compile_parser.add_argument(
        "--limit-per-kind",
        type=int,
        help="Developer smoke-test limit for each pair table; omit for the full frame.",
    )

    validate = stages.add_parser("validate", help="Validate a compiled dataset.")
    validate.add_argument("dataset")
    validate.add_argument(
        "--verification", choices=("catalog", "full"), default="catalog"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.stage == "validate":
            compiled = load_compiled_dataset(
                args.dataset,
                data_root=args.data_root,
                verification=args.verification,
            )
            print(f"dataset_id={compiled.dataset_id}")
            print(f"directory={compiled.directory}")
            print(f"verification={args.verification}")
            return 0

        failures = preflight() if args.bce_dir.resolve() == BCE_DIR.resolve() else []
        required = (
            args.bce_dir / "bigclonebenchdb" / "bcb.h2.db",
            args.bce_dir / "libs" / "h2-1.3.176.jar",
            args.bce_dir / "ijadataset",
        )
        failures.extend(
            f"BigCloneBench compile prerequisite not found: {path}"
            for path in required
            if not path.exists()
        )
        if failures:
            raise ValueError("\n  - ".join(failures))
        scope = {
            "pair_tables": ["clones", "false_positives"],
            "external_only": True,
            "limit_per_kind": args.limit_per_kind,
            "ordering": "syntactic_type_functionality_function_ids",
        }
        reusable = find_reusable_compiled_dataset(
            data_root=args.data_root,
            bce_dir=args.bce_dir,
            compile_scope=scope,
        )
        if reusable is not None:
            print("Compiled BigCloneBench dataset: reused")
            print(f"dataset_id={reusable.dataset_id}")
            print(f"directory={reusable.directory}")
            return 0
        with tempfile.TemporaryDirectory(prefix="srcmove-bcb-export-") as temporary:
            with ProgressDisplay("compile/export", detail="querying H2 serially") as progress:
                exports = export_h2(
                    Path(temporary),
                    bce_dir=args.bce_dir,
                    limit_per_kind=args.limit_per_kind,
                )
                progress.finish("exported positive and known-false-positive rows")
            with ProgressDisplay(
                "compile/catalog", detail="extracting unique fragments"
            ) as progress:
                compiled = compile_exports(
                    bce_dir=args.bce_dir,
                    data_root=args.data_root,
                    exports=exports,
                    compile_scope=scope,
                    java=java_identity(),
                    progress_callback=lambda completed, total, fragments: (
                        progress.set_total(total, completed=completed),
                        progress.update(
                            completed,
                            detail=f"{fragments:,} unique fragments",
                        ),
                    ),
                )
                progress.finish(
                    f"{compiled.manifest['counts']['catalog_pair_rows']:,} catalog rows, "
                    f"{compiled.manifest['counts']['unique_fragments']:,} fragments"
                )
        record_compiled_dataset(
            compiled,
            data_root=args.data_root,
            compile_scope=scope,
        )
        print(f"dataset_id={compiled.dataset_id}")
        print(f"directory={compiled.directory}")
        print(json.dumps(compiled.manifest["counts"], indent=2, sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
