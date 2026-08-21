#!/usr/bin/env python3
"""Compile BigCloneBench into a reusable SQLite catalog and fragment store."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
TESTS_ROOT = REPO_ROOT / "tests"
for import_root in (REPO_ROOT, TESTS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from benchmarks.bigclonebench.compiled import (
    VerifiedCompiledDataset,
    compile_exports,
    compile_request_id,
    find_reusable_compiled_dataset,
    load_compiled_dataset,
    record_compiled_dataset,
    verify_upstream_sources,
)
from benchmarks.bigclonebench.generate import BCE_DIR, java_identity, preflight
from benchmarks.process import write_json_atomic
from benchmarks.progress import ProgressDisplay
from benchmarks.provenance import sha256_file
from support.tooling import format_process_failure, run_command


DEFAULT_DATA_ROOT = REPO_ROOT / "benchmark-data"
EXPORT_CACHE_SCHEMA_VERSION = 1


def _limit_clause(limit_per_kind: int | None) -> str:
    if limit_per_kind is None:
        return ""
    if limit_per_kind <= 0:
        raise ValueError("limit-per-kind must be positive")
    return f"\nLIMIT {limit_per_kind}"


def _ordering_clause(limit_per_kind: int | None, expression: str) -> str:
    """Sort only deterministic smoke-test prefixes, not complete exports."""

    return f"\nORDER BY {expression}" if limit_per_kind is not None else ""


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
{_ordering_clause(limit_per_kind, 'c.syntactic_type, c.functionality_id, c.function_id_one, c.function_id_two')}
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
{_ordering_clause(limit_per_kind, 'fp.syntactic_type, fp.functionality_id, fp.function_id_one, fp.function_id_two')}
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


def _quick_identity(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {
        "size_bytes": stat.st_size,
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "mtime_ns": stat.st_mtime_ns,
    }


def _export_cache_directory(data_root: Path, compile_scope: dict[str, object]) -> Path:
    return (
        data_root.expanduser().resolve()
        / "bigclonebench"
        / "work"
        / compile_request_id(compile_scope)
    )


def _load_cached_exports(
    cache: Path,
    *,
    bce_dir: Path,
    compile_scope: dict[str, object],
    activity_callback: Callable[[str], None] | None = None,
) -> dict[str, Path] | None:
    manifest_path = cache / "exports.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        database = bce_dir / "bigclonebenchdb" / "bcb.h2.db"
        h2_jar = bce_dir / "libs" / "h2-1.3.176.jar"
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != EXPORT_CACHE_SCHEMA_VERSION
            or manifest.get("compile_scope") != compile_scope
            or manifest.get("upstream")
            != {
                "database": _quick_identity(database),
                "h2_jar": _quick_identity(h2_jar),
            }
        ):
            return None
        exports: dict[str, Path] = {}
        declared = manifest.get("exports")
        if not isinstance(declared, dict):
            return None
        for kind, filename in (
            ("positive", "positive.csv"),
            ("known_false_positive", "known_false_positive.csv"),
        ):
            if activity_callback is not None:
                label = kind.replace("_", "-")
                activity_callback(f"verifying saved {label} export")
            path = cache / filename
            item = declared.get(kind)
            if (
                not isinstance(item, dict)
                or item.get("path") != filename
                or path.is_symlink()
                or not path.is_file()
                or path.stat().st_size != item.get("size_bytes")
                or sha256_file(path) != item.get("sha256")
            ):
                return None
            exports[kind] = path
        return exports
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def cached_or_export_h2(
    *,
    data_root: Path,
    bce_dir: Path,
    compile_scope: dict[str, object],
    limit_per_kind: int | None,
    activity_callback: Callable[[str], None] | None = None,
) -> tuple[dict[str, Path], Path, bool]:
    """Reuse complete checked exports after an interrupted catalog compile."""

    cache = _export_cache_directory(data_root, compile_scope)
    if activity_callback is not None:
        activity_callback("checking for reusable exports")
    cached = _load_cached_exports(
        cache,
        bce_dir=bce_dir,
        compile_scope=compile_scope,
        activity_callback=activity_callback,
    )
    if cached is not None:
        return cached, cache, True

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".exporting-", dir=cache.parent) as temporary:
        if activity_callback is not None:
            activity_callback("querying H2 serially")
        exports = export_h2(
            Path(temporary),
            bce_dir=bce_dir,
            limit_per_kind=limit_per_kind,
        )
        published: dict[str, Path] = {}
        declarations: dict[str, dict[str, object]] = {}
        for kind, source in exports.items():
            if activity_callback is not None:
                label = kind.replace("_", "-")
                activity_callback(f"checksumming {label} export")
            filename = source.name
            target = cache / filename
            os.replace(source, target)
            published[kind] = target
            declarations[kind] = {
                "path": filename,
                "size_bytes": target.stat().st_size,
                "sha256": sha256_file(target),
            }
        database = bce_dir / "bigclonebenchdb" / "bcb.h2.db"
        h2_jar = bce_dir / "libs" / "h2-1.3.176.jar"
        write_json_atomic(
            cache / "exports.json",
            {
                "schema_version": EXPORT_CACHE_SCHEMA_VERSION,
                "compile_scope": compile_scope,
                "upstream": {
                    "database": _quick_identity(database),
                    "h2_jar": _quick_identity(h2_jar),
                },
                "exports": declarations,
            },
        )
    return published, cache, False


class CatalogProgress:
    """Translate compiler phase events into separate terminal progress lines."""

    def __init__(self) -> None:
        self.active: ProgressDisplay | None = None

    def __call__(
        self,
        event: str,
        phase: str,
        completed: int,
        total: int | None,
        detail: str,
    ) -> None:
        if event == "start":
            if self.active is not None:
                self.active.finish("compiler phase changed unexpectedly", success=False)
            self.active = ProgressDisplay(
                f"compile/{phase}", total=total, detail=detail
            )
            self.active.start()
            return
        if self.active is None:
            raise RuntimeError(f"compiler progress phase {phase} was not started")
        if total is not None:
            self.active.set_total(total, completed=completed)
        self.active.update(completed, detail=detail)
        if event == "finish":
            self.active.finish(detail)
            self.active = None

    def fail(self, error: BaseException) -> None:
        if self.active is not None:
            self.active.finish(f"failed: {error}", success=False)
            self.active = None


def ensure_compiled_dataset(
    *,
    data_root: Path,
    bce_dir: Path = BCE_DIR,
    limit_per_kind: int | None = None,
    verify_source: bool = False,
) -> tuple[VerifiedCompiledDataset, bool]:
    """Return the requested compiled dataset, building it only when necessary."""

    data_root = data_root.expanduser().resolve()
    bce_dir = bce_dir.expanduser().resolve()
    failures = preflight() if bce_dir == BCE_DIR.resolve() else []
    required = (
        bce_dir / "bigclonebenchdb" / "bcb.h2.db",
        bce_dir / "libs" / "h2-1.3.176.jar",
        bce_dir / "ijadataset",
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
        "limit_per_kind": limit_per_kind,
        "ordering": "syntactic_type_functionality_function_ids",
    }
    reusable = find_reusable_compiled_dataset(
        data_root=data_root,
        bce_dir=bce_dir,
        compile_scope=scope,
    )
    if reusable is not None and verify_source:
        verification = verify_upstream_sources(
            reusable, bce_dir=bce_dir, verification="full"
        )
        if verification.get("status") != "verified":
            reusable = None
    if reusable is not None:
        return reusable, True

    with ProgressDisplay(
        "compile/export", detail="checking for reusable exports"
    ) as progress:
        exports, export_cache, export_reused = cached_or_export_h2(
            data_root=data_root,
            bce_dir=bce_dir,
            compile_scope=scope,
            limit_per_kind=limit_per_kind,
            activity_callback=lambda detail: progress.update(detail=detail),
        )
        progress.finish(
            "reused checked exports"
            if export_reused
            else "exported positive and known-false-positive rows"
        )
    catalog_progress = CatalogProgress()
    try:
        compiled = compile_exports(
            bce_dir=bce_dir,
            data_root=data_root,
            exports=exports,
            compile_scope=scope,
            java=java_identity(),
            progress_callback=catalog_progress,
        )
    except BaseException as error:
        catalog_progress.fail(error)
        raise
    record_compiled_dataset(
        compiled,
        data_root=data_root,
        compile_scope=scope,
    )
    export_work_root = data_root / "bigclonebench" / "work"
    if (
        export_cache.parent == export_work_root
        and not export_cache.is_symlink()
        and export_cache.is_dir()
    ):
        shutil.rmtree(export_cache)
    return compiled, False


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

        scope_label = (
            "full external pair frame"
            if args.limit_per_kind is None
            else f"developer sample, up to {args.limit_per_kind:,} rows per pair table"
        )
        print(f"BigCloneBench compile: {scope_label}", flush=True)
        print(f"data_root={args.data_root.expanduser().resolve()}", flush=True)
        compiled, reused = ensure_compiled_dataset(
            data_root=args.data_root,
            bce_dir=args.bce_dir,
            limit_per_kind=args.limit_per_kind,
        )
        if reused:
            print("Compiled BigCloneBench dataset: reused")
            print(f"dataset_id={compiled.dataset_id}")
            print(f"directory={compiled.directory}")
            return 0
        print(f"dataset_id={compiled.dataset_id}")
        print(f"directory={compiled.directory}")
        print(json.dumps(compiled.manifest["counts"], indent=2, sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
