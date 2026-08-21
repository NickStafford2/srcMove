"""Compile and validate a reusable BigCloneBench SQLite/fragment dataset."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from benchmarks.bigclonebench.dataset import (
    EXTRACTION_POLICY_VERSION,
    extract_bytes,
    source_path,
)
from benchmarks.contracts import canonical_json, content_identifier
from benchmarks.process import write_json_atomic
from benchmarks.provenance import sha256_file, utc_now


COMPILED_DATASET_SCHEMA_VERSION = 2
QUERY_SCHEMA_VERSION = 1
PAIR_IDENTITY_VERSION = 1
SQLITE_APPLICATION_ID = 0x42434231
SQLITE_USER_VERSION = 2


@dataclass(frozen=True)
class VerifiedCompiledDataset:
    directory: Path
    manifest: Mapping[str, Any]
    manifest_sha256: str

    @property
    def dataset_id(self) -> str:
        return str(self.manifest["dataset_id"])


def _normalized_row(row: Mapping[str, str]) -> dict[str, str]:
    return {str(key).strip().lower(): (value or "").strip() for key, value in row.items()}


def _integer(value: str, *, nullable: bool = False) -> int | None:
    if nullable and value.upper() in {"", "NULL"}:
        return None
    return int(value)


def _boolean(value: str) -> int:
    normalized = value.strip().lower()
    if normalized in {"true", "1"}:
        return 1
    if normalized in {"false", "0"}:
        return 0
    raise ValueError(f"invalid Boolean value in BigCloneBench export: {value!r}")


def _schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        f"""
PRAGMA application_id = {SQLITE_APPLICATION_ID};
PRAGMA user_version = {SQLITE_USER_VERSION};
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = DELETE;
PRAGMA synchronous = FULL;

CREATE TABLE catalog_metadata (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  dataset_id TEXT,
  identity_sha256 TEXT,
  source_files_identity_sha256 TEXT,
  function_inventory_sha256 TEXT,
  pair_inventory_sha256 TEXT
) STRICT;

CREATE TABLE source_files (
  source_path TEXT PRIMARY KEY,
  size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
  device INTEGER NOT NULL,
  inode INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL,
  sha256 TEXT NOT NULL CHECK (length(sha256) = 64)
) STRICT;

CREATE TABLE fragments (
  fragment_sha256 TEXT PRIMARY KEY CHECK (length(fragment_sha256) = 64),
  size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
  line_count INTEGER NOT NULL CHECK (line_count > 0),
  object_path TEXT NOT NULL UNIQUE
) STRICT;

CREATE TABLE functions (
  function_id INTEGER PRIMARY KEY,
  source_type TEXT NOT NULL,
  source_name TEXT NOT NULL,
  start_line INTEGER NOT NULL CHECK (start_line >= 1),
  end_line INTEGER NOT NULL CHECK (end_line >= start_line),
  project TEXT NOT NULL,
  tokens INTEGER NOT NULL CHECK (tokens >= 0),
  internal INTEGER NOT NULL CHECK (internal IN (0, 1))
) STRICT;

CREATE TABLE function_materializations (
  functionality_id INTEGER NOT NULL,
  function_id INTEGER NOT NULL REFERENCES functions(function_id),
  expected_source_path TEXT NOT NULL,
  source_path TEXT REFERENCES source_files(source_path),
  fragment_sha256 TEXT REFERENCES fragments(fragment_sha256),
  extraction_status TEXT NOT NULL
    CHECK (extraction_status IN ('pending', 'success', 'missing', 'invalid')),
  extraction_error TEXT,
  PRIMARY KEY (functionality_id, function_id),
  CHECK (
    (extraction_status = 'success' AND source_path IS NOT NULL
      AND fragment_sha256 IS NOT NULL AND extraction_error IS NULL)
    OR extraction_status != 'success'
  )
) STRICT;

CREATE TABLE pair_rows (
  pair_id INTEGER PRIMARY KEY,
  pair_kind TEXT NOT NULL
    CHECK (pair_kind IN ('positive', 'known_false_positive')),
  source_row_hash TEXT NOT NULL CHECK (length(source_row_hash) = 64),
  source_row_multiplicity INTEGER NOT NULL DEFAULT 1
    CHECK (source_row_multiplicity >= 1),
  functionality_id INTEGER NOT NULL,
  function_id_one INTEGER NOT NULL REFERENCES functions(function_id),
  function_id_two INTEGER NOT NULL REFERENCES functions(function_id),
  pair_type TEXT NOT NULL,
  syntactic_type INTEGER NOT NULL,
  similarity_line REAL NOT NULL,
  similarity_token REAL NOT NULL,
  min_size INTEGER,
  max_size INTEGER,
  min_pretty_size INTEGER,
  max_pretty_size INTEGER,
  min_tokens INTEGER NOT NULL,
  max_tokens INTEGER,
  min_judges INTEGER,
  min_confidence INTEGER,
  pair_internal INTEGER NOT NULL CHECK (pair_internal IN (0, 1)),
  fragment_one_sha256 TEXT REFERENCES fragments(fragment_sha256),
  fragment_two_sha256 TEXT REFERENCES fragments(fragment_sha256),
  ordered_pair_id TEXT,
  unordered_pair_id TEXT,
  canonical_direction TEXT
    CHECK (canonical_direction IN ('forward', 'reverse', 'equal')),
  source_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (source_status IN ('pending', 'available', 'unavailable')),
  UNIQUE (pair_kind, source_row_hash)
) STRICT;

CREATE INDEX pair_selection_idx
  ON pair_rows(pair_kind, syntactic_type, min_tokens, min_judges, min_confidence);
CREATE INDEX pair_functionality_idx ON pair_rows(functionality_id);
CREATE INDEX pair_function_one_idx ON pair_rows(function_id_one);
CREATE INDEX pair_function_two_idx ON pair_rows(function_id_two);
CREATE INDEX pair_ordered_idx ON pair_rows(ordered_pair_id);
CREATE INDEX pair_unordered_idx ON pair_rows(unordered_pair_id);
CREATE INDEX materialization_fragment_idx
  ON function_materializations(fragment_sha256);
"""
    )


def _function_value(row: Mapping[str, str], side: str) -> tuple[Any, ...]:
    return (
        row[f"type{side}"],
        row[f"name{side}"],
        int(row[f"startline{side}"]),
        int(row[f"endline{side}"]),
        row[f"project{side}"],
        int(row[f"tokens{side}"]),
        _boolean(row[f"internal{side}"]),
    )


def _upsert_function(
    connection: sqlite3.Connection,
    row: Mapping[str, str],
    side: str,
    functionality_id: int,
) -> None:
    function_id = int(row[f"function_id_{side}"])
    values = _function_value(row, side)
    existing = connection.execute(
        "SELECT source_type, source_name, start_line, end_line, project, tokens, internal "
        "FROM functions WHERE function_id = ?",
        (function_id,),
    ).fetchone()
    if existing is not None and tuple(existing) != values:
        raise ValueError(f"conflicting metadata for BigCloneBench function {function_id}")
    connection.execute(
        "INSERT OR IGNORE INTO functions "
        "(function_id, source_type, source_name, start_line, end_line, project, tokens, internal) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (function_id, *values),
    )
    connection.execute(
        "INSERT OR IGNORE INTO function_materializations "
        "(functionality_id, function_id, expected_source_path, extraction_status) "
        "VALUES (?, ?, '', 'pending')",
        (functionality_id, function_id),
    )


def _pair_values(row: Mapping[str, str], pair_kind: str) -> tuple[Any, ...]:
    tokens_one = int(row["tokensone"])
    tokens_two = int(row["tokenstwo"])
    if pair_kind == "positive":
        min_tokens = int(row["min_tokens"])
        max_tokens = _integer(row.get("max_tokens", ""), nullable=True)
        pair_internal = _boolean(row["pair_internal"])
    else:
        min_tokens = min(tokens_one, tokens_two)
        max_tokens = max(tokens_one, tokens_two)
        pair_internal = 0
    return (
        int(row["functionality_id"]),
        int(row["function_id_one"]),
        int(row["function_id_two"]),
        row["pair_type"],
        int(row["syntactic_type"]),
        float(row["similarity_line"]),
        float(row["similarity_token"]),
        _integer(row.get("min_size", ""), nullable=True),
        _integer(row.get("max_size", ""), nullable=True),
        _integer(row.get("min_pretty_size", ""), nullable=True),
        _integer(row.get("max_pretty_size", ""), nullable=True),
        min_tokens,
        max_tokens,
        _integer(row.get("min_judges", ""), nullable=True),
        _integer(row.get("min_confidence", ""), nullable=True),
        pair_internal,
    )


def _import_export(
    connection: sqlite3.Connection,
    export_path: Path,
    pair_kind: str,
) -> int:
    imported = 0
    with export_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError(f"BigCloneBench export has no header: {export_path}")
        for raw_row in reader:
            row = _normalized_row(raw_row)
            functionality_id = int(row["functionality_id"])
            _upsert_function(connection, row, "one", functionality_id)
            _upsert_function(connection, row, "two", functionality_id)
            values = _pair_values(row, pair_kind)
            row_hash = hashlib.sha256(
                canonical_json(
                    {
                        "pair_kind": pair_kind,
                        "values": list(values),
                    }
                )
            ).hexdigest()
            connection.execute(
                "INSERT INTO pair_rows "
                "(pair_kind, source_row_hash, functionality_id, function_id_one, "
                "function_id_two, pair_type, syntactic_type, similarity_line, "
                "similarity_token, min_size, max_size, min_pretty_size, "
                "max_pretty_size, min_tokens, max_tokens, min_judges, "
                "min_confidence, pair_internal) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(pair_kind, source_row_hash) DO UPDATE SET "
                "source_row_multiplicity = source_row_multiplicity + 1",
                (pair_kind, row_hash, *values),
            )
            imported += 1
    return imported


def _fragment_object_path(fragment_sha256: str) -> Path:
    return Path("fragments") / fragment_sha256[:2] / f"{fragment_sha256}.java"


def _materialize_fragments(
    connection: sqlite3.Connection,
    *,
    bce_dir: Path,
    staging: Path,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> None:
    source_records: dict[Path, dict[str, Any]] = {}
    last_path: Path | None = None
    last_source_bytes = b""
    total = int(
        connection.execute("SELECT COUNT(*) FROM function_materializations").fetchone()[0]
    )
    unique_fragments = 0
    if progress_callback is not None:
        progress_callback(0, total, unique_fragments)
    rows = connection.execute(
        "SELECT m.functionality_id, f.function_id, f.source_type, f.source_name, "
        "f.start_line, f.end_line FROM function_materializations m "
        "JOIN functions f ON f.function_id = m.function_id "
        "ORDER BY f.source_type, f.source_name, m.functionality_id, f.function_id"
    )
    for completed, (
        functionality_id,
        function_id,
        source_type,
        name,
        startline,
        endline,
    ) in enumerate(rows, start=1):
        path = source_path(bce_dir, source_type, name, functionality_id).resolve()
        source_root = (bce_dir / "ijadataset").resolve()
        expected_relative = (
            path.relative_to(bce_dir.resolve()).as_posix()
            if path.is_relative_to(bce_dir.resolve())
            else "unsafe"
        )
        connection.execute(
            "UPDATE function_materializations SET expected_source_path=? "
            "WHERE functionality_id=? AND function_id=?",
            (expected_relative, functionality_id, function_id),
        )
        if not path.is_relative_to(source_root) or not path.is_file():
            connection.execute(
                "UPDATE function_materializations SET extraction_status='missing', "
                "extraction_error=? WHERE functionality_id=? AND function_id=?",
                ("source file not found", functionality_id, function_id),
            )
            if progress_callback is not None and (
                completed % 1000 == 0 or completed == total
            ):
                progress_callback(completed, total, unique_fragments)
            continue
        if path == last_path:
            source_bytes = last_source_bytes
            source_record = source_records[path]
        else:
            stat_before = path.stat()
            source_bytes = path.read_bytes()
            source_record = source_records.get(path)
            if source_record is None:
                stat = path.stat()
                before_identity = (
                    stat_before.st_dev,
                    stat_before.st_ino,
                    stat_before.st_size,
                    stat_before.st_mtime_ns,
                )
                after_identity = (
                    stat.st_dev,
                    stat.st_ino,
                    stat.st_size,
                    stat.st_mtime_ns,
                )
                if before_identity != after_identity or len(source_bytes) != stat.st_size:
                    raise ValueError(f"BigCloneBench source changed during compile: {path}")
                relative = path.relative_to(bce_dir.resolve()).as_posix()
                source_record = {
                    "source_path": relative,
                    "size_bytes": len(source_bytes),
                    "device": stat.st_dev,
                    "inode": stat.st_ino,
                    "mtime_ns": stat.st_mtime_ns,
                    "sha256": hashlib.sha256(source_bytes).hexdigest(),
                }
                connection.execute(
                    "INSERT INTO source_files VALUES (?, ?, ?, ?, ?, ?)",
                    tuple(source_record.values()),
                )
                source_records[path] = source_record
            elif hashlib.sha256(source_bytes).hexdigest() != source_record["sha256"]:
                raise ValueError(f"BigCloneBench source changed during compile: {path}")
            last_path = path
            last_source_bytes = source_bytes
        try:
            fragment = extract_bytes(
                source_bytes,
                startline,
                endline,
                source=path,
            )
        except ValueError as error:
            connection.execute(
                "UPDATE function_materializations SET source_path=?, "
                "extraction_status='invalid', extraction_error=? "
                "WHERE functionality_id=? AND function_id=?",
                (
                    source_record["source_path"],
                    str(error).replace(str(path), "<source>"),
                    functionality_id,
                    function_id,
                ),
            )
            if progress_callback is not None and (
                completed % 1000 == 0 or completed == total
            ):
                progress_callback(completed, total, unique_fragments)
            continue
        fragment_bytes = fragment.encode("utf-8")
        fragment_sha256 = hashlib.sha256(fragment_bytes).hexdigest()
        object_path = _fragment_object_path(fragment_sha256)
        target = staging / object_path
        inserted = connection.execute(
            "INSERT OR IGNORE INTO fragments VALUES (?, ?, ?, ?)",
            (
                fragment_sha256,
                len(fragment_bytes),
                len(fragment.splitlines()),
                object_path.as_posix(),
            ),
        ).rowcount
        if inserted:
            unique_fragments += 1
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(fragment_bytes)
        else:
            existing = connection.execute(
                "SELECT size_bytes, object_path FROM fragments "
                "WHERE fragment_sha256=?",
                (fragment_sha256,),
            ).fetchone()
            if existing is None or tuple(existing) != (
                len(fragment_bytes),
                object_path.as_posix(),
            ):
                raise ValueError(f"fragment hash collision: {fragment_sha256}")
        connection.execute(
            "UPDATE function_materializations SET source_path=?, fragment_sha256=?, "
            "extraction_status='success', extraction_error=NULL "
            "WHERE functionality_id=? AND function_id=?",
            (
                source_record["source_path"],
                fragment_sha256,
                functionality_id,
                function_id,
            ),
        )
        if progress_callback is not None and (completed % 1000 == 0 or completed == total):
            progress_callback(completed, total, unique_fragments)

    if progress_callback is not None:
        progress_callback(total, total, unique_fragments)

    # A global function should materialize to the same canonical fragment in
    # every functionality-specific reduced-corpus location where it appears.
    conflicts = connection.execute(
        "SELECT function_id FROM function_materializations "
        "WHERE extraction_status='success' GROUP BY function_id "
        "HAVING COUNT(DISTINCT fragment_sha256) > 1 LIMIT 1"
    ).fetchone()
    if conflicts is not None:
        raise ValueError(
            f"function {conflicts[0]} materialized to conflicting source fragments"
        )

    pair_rows = connection.execute(
        "SELECT p.pair_id, m1.fragment_sha256, m2.fragment_sha256 "
        "FROM pair_rows p "
        "LEFT JOIN function_materializations m1 ON "
        "m1.functionality_id=p.functionality_id AND m1.function_id=p.function_id_one "
        "LEFT JOIN function_materializations m2 ON "
        "m2.functionality_id=p.functionality_id AND m2.function_id=p.function_id_two"
    )
    for pair_id, fragment_one, fragment_two in pair_rows:
        if fragment_one is None or fragment_two is None:
            connection.execute(
                "UPDATE pair_rows SET source_status='unavailable' WHERE pair_id=?",
                (pair_id,),
            )
            continue
        ordered = content_identifier(
            "bcb-ordered-pair", {"one": fragment_one, "two": fragment_two}
        )
        low, high = sorted((fragment_one, fragment_two))
        unordered = content_identifier(
            "bcb-unordered-pair", {"low": low, "high": high}
        )
        direction = (
            "equal"
            if fragment_one == fragment_two
            else "forward"
            if fragment_one == low
            else "reverse"
        )
        connection.execute(
            "UPDATE pair_rows SET fragment_one_sha256=?, fragment_two_sha256=?, "
            "ordered_pair_id=?, unordered_pair_id=?, canonical_direction=?, "
            "source_status='available' WHERE pair_id=?",
            (fragment_one, fragment_two, ordered, unordered, direction, pair_id),
        )


def _logical_inventory_sha256(
    connection: sqlite3.Connection, query: str
) -> str:
    hasher = hashlib.sha256()
    for row in connection.execute(query):
        encoded = canonical_json(list(row))
        hasher.update(len(encoded).to_bytes(8, "big"))
        hasher.update(encoded)
    return hasher.hexdigest()


def _fragment_inventory(connection: sqlite3.Connection) -> tuple[str, int, int]:
    """Hash the fragment catalog without materializing it in Python."""

    hasher = hashlib.sha256()
    count = 0
    total_bytes = 0
    for fragment_sha, size_bytes, object_path in connection.execute(
        "SELECT fragment_sha256, size_bytes, object_path "
        "FROM fragments ORDER BY fragment_sha256"
    ):
        encoded = canonical_json(
            {"sha256": fragment_sha, "size_bytes": size_bytes, "path": object_path}
        )
        hasher.update(len(encoded).to_bytes(8, "big"))
        hasher.update(encoded)
        count += 1
        total_bytes += size_bytes
    return hasher.hexdigest(), count, total_bytes


def _counts(connection: sqlite3.Connection, imported: Mapping[str, int]) -> dict[str, int]:
    scalar = lambda query: int(connection.execute(query).fetchone()[0])
    return {
        "positive_source_rows": imported["positive"],
        "known_false_positive_source_rows": imported["known_false_positive"],
        "catalog_pair_rows": scalar("SELECT COUNT(*) FROM pair_rows"),
        "duplicate_source_rows": scalar(
            "SELECT COALESCE(SUM(source_row_multiplicity - 1), 0) FROM pair_rows"
        ),
        "functions": scalar("SELECT COUNT(*) FROM functions"),
        "source_files": scalar("SELECT COUNT(*) FROM source_files"),
        "function_materializations": scalar(
            "SELECT COUNT(*) FROM function_materializations"
        ),
        "extracted_functions": scalar(
            "SELECT COUNT(*) FROM function_materializations WHERE extraction_status='success'"
        ),
        "extraction_failures": scalar(
            "SELECT COUNT(*) FROM function_materializations WHERE extraction_status!='success'"
        ),
        "unique_fragments": scalar("SELECT COUNT(*) FROM fragments"),
        "available_pairs": scalar(
            "SELECT COUNT(*) FROM pair_rows WHERE source_status='available'"
        ),
        "unique_ordered_pairs": scalar(
            "SELECT COUNT(DISTINCT ordered_pair_id) FROM pair_rows WHERE source_status='available'"
        ),
        "unique_unordered_pairs": scalar(
            "SELECT COUNT(DISTINCT unordered_pair_id) FROM pair_rows "
            "WHERE source_status='available'"
        ),
        "positive_negative_label_conflicts": scalar(
            "SELECT COUNT(*) FROM (SELECT unordered_pair_id FROM pair_rows "
            "WHERE source_status='available' GROUP BY unordered_pair_id "
            "HAVING COUNT(DISTINCT pair_kind) > 1)"
        ),
    }


def _database_quick_identity(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "size_bytes": stat.st_size,
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "mtime_ns": stat.st_mtime_ns,
    }


def compile_exports(
    *,
    bce_dir: Path,
    data_root: Path,
    exports: Mapping[str, Path],
    compile_scope: Mapping[str, Any],
    java: Mapping[str, Any] | None = None,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> VerifiedCompiledDataset:
    """Compile deterministic CSV exports into an immutable local dataset."""

    bce_dir = bce_dir.expanduser().resolve()
    database = bce_dir / "bigclonebenchdb" / "bcb.h2.db"
    h2_jar = bce_dir / "libs" / "h2-1.3.176.jar"
    for required in (database, h2_jar, *exports.values()):
        if not required.is_file():
            raise FileNotFoundError(required)

    compiled_root = data_root.expanduser().resolve() / "bigclonebench" / "compiled"
    compiled_root.mkdir(parents=True, exist_ok=True)
    staging = compiled_root / f".staging-{uuid.uuid4().hex}"
    staging.mkdir()
    catalog_path = staging / "catalog.sqlite"
    try:
        connection = sqlite3.connect(catalog_path)
        connection.row_factory = sqlite3.Row
        try:
            _schema(connection)
            imported = {
                "positive": _import_export(connection, exports["positive"], "positive"),
                "known_false_positive": _import_export(
                    connection,
                    exports["known_false_positive"],
                    "known_false_positive",
                ),
            }
            _materialize_fragments(
                connection,
                bce_dir=bce_dir,
                staging=staging,
                progress_callback=progress_callback,
            )
            counts = _counts(connection, imported)
            source_inventory_sha256 = _logical_inventory_sha256(
                connection,
                "SELECT source_path, size_bytes, sha256 FROM source_files ORDER BY source_path",
            )
            function_inventory_sha256 = _logical_inventory_sha256(
                connection,
                "SELECT functionality_id, function_id, expected_source_path, source_path, fragment_sha256, "
                "extraction_status, extraction_error FROM function_materializations "
                "ORDER BY functionality_id, function_id",
            )
            pair_inventory_sha256 = _logical_inventory_sha256(
                connection,
                "SELECT pair_kind, source_row_hash, source_row_multiplicity, "
                "fragment_one_sha256, fragment_two_sha256 FROM pair_rows "
                "ORDER BY pair_kind, source_row_hash",
            )
            identity = {
                "schema_version": COMPILED_DATASET_SCHEMA_VERSION,
                "query_schema_version": QUERY_SCHEMA_VERSION,
                "extraction_policy_version": EXTRACTION_POLICY_VERSION,
                "pair_identity_version": PAIR_IDENTITY_VERSION,
                "compile_scope": dict(compile_scope),
                "database": {
                    "size_bytes": database.stat().st_size,
                    "sha256": sha256_file(database),
                },
                "h2_jar": {
                    "size_bytes": h2_jar.stat().st_size,
                    "sha256": sha256_file(h2_jar),
                },
                "source_inventory_sha256": source_inventory_sha256,
                "function_inventory_sha256": function_inventory_sha256,
                "pair_inventory_sha256": pair_inventory_sha256,
            }
            dataset_id = content_identifier("bcb-dataset", identity)
            identity_sha256 = hashlib.sha256(canonical_json(identity)).hexdigest()
            connection.execute(
                "INSERT INTO catalog_metadata VALUES (1, ?, ?, ?, ?, ?)",
                (
                    dataset_id,
                    identity_sha256,
                    source_inventory_sha256,
                    function_inventory_sha256,
                    pair_inventory_sha256,
                ),
            )
            connection.commit()
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_keys:
                raise ValueError("compiled catalog has foreign-key violations")
            quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
            if quick_check != "ok":
                raise ValueError(f"compiled catalog failed quick_check: {quick_check}")
            connection.execute("VACUUM")
        finally:
            connection.close()

        with closing(sqlite3.connect(f"file:{catalog_path}?mode=ro", uri=True)) as reader:
            fragments_inventory_sha256, fragment_count, fragment_bytes = (
                _fragment_inventory(reader)
            )
        manifest = {
            "schema_version": COMPILED_DATASET_SCHEMA_VERSION,
            "dataset": "BigCloneBench",
            "dataset_id": dataset_id,
            "identity_sha256": identity_sha256,
            "identity": identity,
            "created_at": utc_now(),
            "compiler": {
                "query_schema_version": QUERY_SCHEMA_VERSION,
                "extraction_policy_version": EXTRACTION_POLICY_VERSION,
                "pair_identity_version": PAIR_IDENTITY_VERSION,
                "extraction_policy": "utf8-replace_lf-ranges_strip-terminal-cr_rstrip_one-lf",
            },
            "upstream": {
                "database": {
                    "relative_path": "bigclonebenchdb/bcb.h2.db",
                    "quick_identity": _database_quick_identity(database),
                    **identity["database"],
                },
                "h2_jar": {
                    "relative_path": "libs/h2-1.3.176.jar",
                    "quick_identity": _database_quick_identity(h2_jar),
                    **identity["h2_jar"],
                },
                "java": dict(java or {}),
                "source_files": {
                    "count": counts["source_files"],
                    "identity_sha256": source_inventory_sha256,
                    "inventory_location": "catalog.sqlite:source_files",
                },
            },
            "compile_scope": dict(compile_scope),
            "artifacts": {
                "catalog": {
                    "path": "catalog.sqlite",
                    "size_bytes": catalog_path.stat().st_size,
                    "quick_identity": _database_quick_identity(catalog_path),
                    "sha256": sha256_file(catalog_path),
                },
                "fragments": {
                    "path": "fragments",
                    "count": fragment_count,
                    "total_bytes": fragment_bytes,
                    "inventory_sha256": fragments_inventory_sha256,
                },
            },
            "counts": counts,
        }
        manifest_path = staging / "manifest.json"
        write_json_atomic(manifest_path, manifest)
        final = compiled_root / dataset_id
        if final.exists():
            verified = load_compiled_dataset(final, verification="full")
            shutil.rmtree(staging)
            return verified
        try:
            os.replace(staging, final)
        except OSError:
            # Another compiler may have published the same content-addressed
            # directory after our existence check. Validate and reuse it.
            if not final.is_dir():
                raise
            shutil.rmtree(staging)
            return load_compiled_dataset(final, verification="full")
        return load_compiled_dataset(final, verification="full")
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def _manifest_identity(manifest: Mapping[str, Any]) -> None:
    identity = manifest.get("identity")
    if not isinstance(identity, dict):
        raise ValueError("compiled dataset manifest identity is missing or invalid")
    expected_id = content_identifier("bcb-dataset", identity)
    expected_sha = hashlib.sha256(canonical_json(identity)).hexdigest()
    if manifest.get("dataset_id") != expected_id or manifest.get("identity_sha256") != expected_sha:
        raise ValueError("compiled dataset manifest identity does not match")
    compiler = manifest.get("compiler")
    upstream = manifest.get("upstream")
    if not isinstance(compiler, dict) or not isinstance(upstream, dict):
        raise ValueError("compiled dataset manifest contract is invalid")
    if manifest.get("compile_scope") != identity.get("compile_scope"):
        raise ValueError("compiled dataset compile scope does not match identity")
    for key in (
        "query_schema_version",
        "extraction_policy_version",
        "pair_identity_version",
    ):
        if compiler.get(key) != identity.get(key):
            raise ValueError(f"compiled dataset compiler {key} does not match identity")
    for key in ("database", "h2_jar"):
        item = upstream.get(key)
        if not isinstance(item, dict) or any(
            item.get(field) != identity.get(key, {}).get(field)
            for field in ("size_bytes", "sha256")
        ):
            raise ValueError(f"compiled dataset upstream {key} does not match identity")
    sources = upstream.get("source_files")
    if not isinstance(sources, dict) or sources.get("identity_sha256") != identity.get(
        "source_inventory_sha256"
    ):
        raise ValueError("compiled source inventory does not match identity")


def load_compiled_dataset(
    identifier_or_path: str | Path,
    *,
    data_root: Path | None = None,
    verification: str = "catalog",
) -> VerifiedCompiledDataset:
    """Load an immutable compiled dataset with catalog or full CAS verification."""

    if verification not in {"catalog", "full"}:
        raise ValueError(f"unsupported compiled dataset verification: {verification}")
    candidate = Path(identifier_or_path)
    if candidate.is_absolute() or candidate.exists():
        directory = candidate.expanduser().resolve()
    elif data_root is not None:
        directory = (
            data_root.expanduser().resolve()
            / "bigclonebench"
            / "compiled"
            / str(identifier_or_path)
        )
    else:
        directory = candidate.expanduser().resolve()
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"compiled dataset directory is unavailable: {directory}")
    manifest_path = directory / "manifest.json"
    catalog_path = directory / "catalog.sqlite"
    fragments_root = directory / "fragments"
    for artifact in (manifest_path, catalog_path):
        if artifact.is_symlink() or not artifact.is_file():
            raise ValueError(f"compiled dataset artifact is unavailable: {artifact}")
    if fragments_root.is_symlink() or not fragments_root.is_dir():
        raise ValueError(f"compiled fragment store is unavailable: {fragments_root}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != COMPILED_DATASET_SCHEMA_VERSION
    ):
        raise ValueError(f"invalid compiled dataset manifest: {manifest_path}")
    _manifest_identity(manifest)
    if directory.name != manifest["dataset_id"]:
        raise ValueError("compiled dataset directory name does not match dataset id")
    artifacts = manifest.get("artifacts")
    counts = manifest.get("counts")
    if not isinstance(artifacts, dict) or not isinstance(counts, dict):
        raise ValueError("compiled dataset manifest artifacts or counts are invalid")
    catalog = artifacts.get("catalog")
    declared_fragments = artifacts.get("fragments")
    if not isinstance(catalog, dict) or not isinstance(declared_fragments, dict):
        raise ValueError("compiled dataset artifact declarations are invalid")
    if catalog.get("path") != "catalog.sqlite" or sha256_file(
        catalog_path
    ) != catalog.get("sha256"):
        raise ValueError("compiled catalog checksum does not match manifest")
    uri = f"file:{catalog_path}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        if connection.execute("PRAGMA application_id").fetchone()[0] != SQLITE_APPLICATION_ID:
            raise ValueError("compiled catalog application id is invalid")
        if connection.execute("PRAGMA user_version").fetchone()[0] != SQLITE_USER_VERSION:
            raise ValueError("compiled catalog schema version is invalid")
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("compiled catalog integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("compiled catalog foreign-key check failed")
        metadata = connection.execute(
            "SELECT dataset_id, identity_sha256, source_files_identity_sha256, "
            "function_inventory_sha256, pair_inventory_sha256 "
            "FROM catalog_metadata WHERE singleton=1"
        ).fetchone()
        if metadata is None or tuple(metadata) != (
            manifest["dataset_id"],
            manifest["identity_sha256"],
            manifest["identity"]["source_inventory_sha256"],
            manifest["identity"]["function_inventory_sha256"],
            manifest["identity"]["pair_inventory_sha256"],
        ):
            raise ValueError("compiled catalog metadata does not match manifest")
        observed_inventories = {
            "source_inventory_sha256": _logical_inventory_sha256(
                connection,
                "SELECT source_path, size_bytes, sha256 FROM source_files ORDER BY source_path",
            ),
            "function_inventory_sha256": _logical_inventory_sha256(
                connection,
                "SELECT functionality_id, function_id, expected_source_path, source_path, "
                "fragment_sha256, extraction_status, extraction_error "
                "FROM function_materializations ORDER BY functionality_id, function_id",
            ),
            "pair_inventory_sha256": _logical_inventory_sha256(
                connection,
                "SELECT pair_kind, source_row_hash, source_row_multiplicity, "
                "fragment_one_sha256, fragment_two_sha256 FROM pair_rows "
                "ORDER BY pair_kind, source_row_hash",
            ),
        }
        if any(
            observed != manifest["identity"].get(key)
            for key, observed in observed_inventories.items()
        ):
            raise ValueError("compiled catalog logical inventory does not match identity")
        source_rows_by_kind = {
            kind: int(total)
            for kind, total in connection.execute(
                "SELECT pair_kind, SUM(source_row_multiplicity) "
                "FROM pair_rows GROUP BY pair_kind"
            )
        }
        observed_counts = _counts(
            connection,
            {
                "positive": source_rows_by_kind.get("positive", 0),
                "known_false_positive": source_rows_by_kind.get(
                    "known_false_positive", 0
                ),
            },
        )
        if observed_counts != counts:
            raise ValueError("compiled catalog counts do not match manifest")
        observed_fragment_inventory = _fragment_inventory(connection)
    if observed_fragment_inventory != (
        declared_fragments.get("inventory_sha256"),
        declared_fragments.get("count"),
        declared_fragments.get("total_bytes"),
    ):
        raise ValueError("compiled fragment inventory does not match manifest")
    if verification == "full":
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            for fragment_sha, size_bytes, object_path in connection.execute(
                "SELECT fragment_sha256, size_bytes, object_path FROM fragments"
            ):
                relative = Path(object_path)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("compiled fragment path is unsafe")
                artifact = directory / relative
                if artifact.is_symlink() or not artifact.is_file():
                    raise ValueError(f"compiled fragment is unavailable: {artifact}")
                if artifact.stat().st_size != size_bytes or sha256_file(
                    artifact
                ) != fragment_sha:
                    raise ValueError(f"compiled fragment checksum mismatch: {artifact}")
        actual_count = sum(
            1
            for path in fragments_root.rglob("*")
            if path.is_file() or path.is_symlink()
        )
        if actual_count != declared_fragments.get("count"):
            raise ValueError("compiled fragment store contains missing or extra objects")
    return VerifiedCompiledDataset(
        directory=directory,
        manifest=manifest,
        manifest_sha256=sha256_file(manifest_path),
    )


def verify_upstream_sources(
    compiled: VerifiedCompiledDataset,
    *,
    bce_dir: Path,
    verification: str = "metadata",
) -> dict[str, Any]:
    """Compare current BigCloneBench inputs with a compiled dataset."""

    if verification not in {"metadata", "full"}:
        raise ValueError(f"unsupported upstream verification: {verification}")
    bce_dir = bce_dir.expanduser().resolve()
    upstream = compiled.manifest["upstream"]
    database = bce_dir / upstream["database"]["relative_path"]
    h2_jar = bce_dir / upstream["h2_jar"]["relative_path"]
    if not database.is_file() or not h2_jar.is_file():
        return {"status": "mismatch", "reason": "database_or_h2_missing"}
    if verification == "metadata":
        if _database_quick_identity(database) != upstream["database"]["quick_identity"]:
            return {"status": "mismatch", "reason": "database_metadata_changed"}
        if _database_quick_identity(h2_jar) != upstream["h2_jar"]["quick_identity"]:
            return {"status": "mismatch", "reason": "h2_metadata_changed"}
    uri = f"file:{compiled.directory / 'catalog.sqlite'}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        for relative, size, device, inode, mtime_ns, expected_sha in connection.execute(
            "SELECT source_path, size_bytes, device, inode, mtime_ns, sha256 "
            "FROM source_files ORDER BY source_path"
        ):
            path = (bce_dir / relative).resolve()
            if not path.is_relative_to(bce_dir) or not path.is_file():
                return {"status": "mismatch", "reason": "source_missing", "path": relative}
            stat = path.stat()
            if verification == "metadata" and (
                stat.st_size,
                stat.st_dev,
                stat.st_ino,
                stat.st_mtime_ns,
            ) != (size, device, inode, mtime_ns):
                return {
                    "status": "mismatch",
                    "reason": "source_metadata_changed",
                    "path": relative,
                }
            if verification == "full" and sha256_file(path) != expected_sha:
                return {
                    "status": "mismatch",
                    "reason": "source_checksum_changed",
                    "path": relative,
                }
        for (relative,) in connection.execute(
            "SELECT DISTINCT expected_source_path FROM function_materializations "
            "WHERE extraction_status='missing' ORDER BY expected_source_path"
        ):
            path = (bce_dir / relative).resolve()
            if not path.is_relative_to(bce_dir) or path.exists():
                return {
                    "status": "mismatch",
                    "reason": "previously_missing_source_changed",
                    "path": relative,
                }
    if verification == "full":
        if sha256_file(database) != upstream["database"]["sha256"]:
            return {"status": "mismatch", "reason": "database_checksum_changed"}
        if sha256_file(h2_jar) != upstream["h2_jar"]["sha256"]:
            return {"status": "mismatch", "reason": "h2_checksum_changed"}
        return {"status": "verified", "verification": "full"}
    return {"status": "metadata_match", "verification": "metadata"}


def compile_request_id(compile_scope: Mapping[str, Any]) -> str:
    """Identify the compiler contract and requested source frame."""

    return content_identifier(
        "bcb-compile-request",
        {
            "schema_version": COMPILED_DATASET_SCHEMA_VERSION,
            "query_schema_version": QUERY_SCHEMA_VERSION,
            "extraction_policy_version": EXTRACTION_POLICY_VERSION,
            "pair_identity_version": PAIR_IDENTITY_VERSION,
            "compile_scope": dict(compile_scope),
        },
    )


def record_compiled_dataset(
    compiled: VerifiedCompiledDataset,
    *,
    data_root: Path,
    compile_scope: Mapping[str, Any],
) -> None:
    """Update the small mutable lookup index after immutable publication."""

    compiled_root = data_root.expanduser().resolve() / "bigclonebench" / "compiled"
    index_path = compiled_root / "index.json"
    index: dict[str, Any] = {"schema_version": 1, "entries": {}}
    if index_path.is_file():
        value = json.loads(index_path.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 1
            or not isinstance(value.get("entries"), dict)
        ):
            raise ValueError(f"invalid compiled dataset index: {index_path}")
        index = value
    index["entries"][compile_request_id(compile_scope)] = compiled.dataset_id
    write_json_atomic(index_path, index)


def _load_for_reuse(directory: Path) -> VerifiedCompiledDataset:
    """Load only the immutable identity needed by the development fast path."""

    directory = directory.resolve()
    manifest_path = directory / "manifest.json"
    catalog_path = directory / "catalog.sqlite"
    if (
        directory.is_symlink()
        or not directory.is_dir()
        or manifest_path.is_symlink()
        or not manifest_path.is_file()
        or catalog_path.is_symlink()
        or not catalog_path.is_file()
    ):
        raise ValueError("compiled reuse candidate is unavailable")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get(
        "schema_version"
    ) != COMPILED_DATASET_SCHEMA_VERSION:
        raise ValueError("compiled reuse manifest is invalid")
    _manifest_identity(manifest)
    if directory.name != manifest.get("dataset_id"):
        raise ValueError("compiled reuse directory does not match dataset id")
    catalog = manifest.get("artifacts", {}).get("catalog", {})
    if catalog.get("path") != "catalog.sqlite" or catalog.get(
        "quick_identity"
    ) != _database_quick_identity(catalog_path):
        raise ValueError("compiled reuse catalog metadata changed")
    with closing(sqlite3.connect(f"file:{catalog_path}?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA application_id").fetchone()[0] != SQLITE_APPLICATION_ID:
            raise ValueError("compiled reuse catalog application id is invalid")
        if connection.execute("PRAGMA user_version").fetchone()[0] != SQLITE_USER_VERSION:
            raise ValueError("compiled reuse catalog schema version is invalid")
        metadata = connection.execute(
            "SELECT dataset_id, identity_sha256 FROM catalog_metadata WHERE singleton=1"
        ).fetchone()
        if metadata is None or tuple(metadata) != (
            manifest["dataset_id"],
            manifest["identity_sha256"],
        ):
            raise ValueError("compiled reuse catalog metadata does not match")
    return VerifiedCompiledDataset(
        directory=directory,
        manifest=manifest,
        manifest_sha256=sha256_file(manifest_path),
    )


def find_reusable_compiled_dataset(
    *,
    data_root: Path,
    bce_dir: Path,
    compile_scope: Mapping[str, Any],
) -> VerifiedCompiledDataset | None:
    """Return a catalog whose saved upstream file metadata still matches."""

    data_root = data_root.expanduser().resolve()
    compiled_root = data_root / "bigclonebench" / "compiled"
    index_path = compiled_root / "index.json"
    candidate_ids: list[str] = []
    if index_path.is_file():
        value = json.loads(index_path.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 1
            or not isinstance(value.get("entries"), dict)
        ):
            raise ValueError(f"invalid compiled dataset index: {index_path}")
        indexed = value["entries"].get(compile_request_id(compile_scope))
        if isinstance(indexed, str):
            candidate_ids.append(indexed)
    if compiled_root.is_dir():
        candidate_ids.extend(
            path.name
            for path in sorted(compiled_root.glob("bcb-dataset-sha256-*"))
            if path.is_dir() and path.name not in candidate_ids
        )
    for dataset_id in candidate_ids:
        try:
            compiled = _load_for_reuse(compiled_root / dataset_id)
        except (OSError, ValueError, sqlite3.Error):
            continue
        if compiled.manifest.get("compile_scope") != dict(compile_scope):
            continue
        try:
            observation = verify_upstream_sources(
                compiled,
                bce_dir=bce_dir,
                verification="metadata",
            )
        except (KeyError, TypeError, ValueError, sqlite3.Error):
            continue
        if observation.get("status") == "metadata_match":
            record_compiled_dataset(
                compiled,
                data_root=data_root,
                compile_scope=compile_scope,
            )
            return compiled
    return None
