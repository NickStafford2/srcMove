#!/usr/bin/env python3
"""Publish and inspect normalized BigMoveBench case catalogs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarking.identity import canonical_json, content_identifier
from benchmarking.provenance import sha256_file, utc_now
from bigMoveBench.adapter import _fragment_relation, _type3_frame_strength
from bigMoveBench.catalog import VerifiedCompiledDataset, load_compiled_dataset
from bigMoveBench.contracts import InputPair
from bigMoveBench.generated_objects import GeneratedObject, GeneratedObjectStore
from bigMoveBench.paths import DEFAULT_CACHE_ROOT
from bigMoveBench.selection import GENERATED_INPUT_IDENTITY_VERSION, load_selection
from bigMoveBench.synthetic import (
    STABLE_DESTINATION_ROLE,
    STABLE_SOURCE_ROLE,
    STABLE_WRAPPER_VERSION,
    SYNTHETIC_DESTINATION_PATH,
    SYNTHETIC_SOURCE_PATH,
    indent_fragment,
)


BENCHMARK_CASES_SCHEMA_VERSION = 1
BENCHMARK_CASES_SQLITE_APPLICATION_ID = 0x424D4331
BENCHMARK_CASES_SQLITE_USER_VERSION = 1
PAIR_SETS = {"type1", "type2", "type3", "known-false-positive"}


@dataclass(frozen=True)
class VerifiedBenchmarkCases:
    directory: Path
    manifest: Mapping[str, Any]
    manifest_sha256: str
    data_root: Path

    @property
    def benchmark_cases_id(self) -> str:
        return str(self.manifest["benchmark_cases_id"])


def _resolve_selection(data_root: Path, selection: str | Path) -> Path:
    supplied = Path(selection)
    if supplied.is_absolute() or supplied.exists():
        return supplied.expanduser().resolve()
    return data_root / "bigclonebench" / "selections" / str(selection)


def _safe_sha256(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def _generated_input_id(original: str, modified: str) -> str:
    return content_identifier(
        "bcb-generated-input",
        {
            "version": GENERATED_INPUT_IDENTITY_VERSION,
            "original_fragment_sha256": original,
            "modified_fragment_sha256": modified,
        },
    )


def _schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        f"""
PRAGMA application_id = {BENCHMARK_CASES_SQLITE_APPLICATION_ID};
PRAGMA user_version = {BENCHMARK_CASES_SQLITE_USER_VERSION};
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = OFF;
PRAGMA synchronous = OFF;

CREATE TABLE benchmark_cases_metadata (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  benchmark_cases_id TEXT NOT NULL,
  identity_sha256 TEXT NOT NULL CHECK (length(identity_sha256) = 64)
) STRICT;

CREATE TABLE generated_objects (
  object_id TEXT PRIMARY KEY,
  wrapper_version INTEGER NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('source', 'destination')),
  fragment_sha256 TEXT CHECK (fragment_sha256 IS NULL OR length(fragment_sha256) = 64),
  object_path TEXT NOT NULL UNIQUE,
  size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
  sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
  payload_start_line INTEGER,
  payload_end_line INTEGER,
  CHECK (
    (fragment_sha256 IS NULL AND payload_start_line IS NULL AND payload_end_line IS NULL)
    OR
    (fragment_sha256 IS NOT NULL AND payload_start_line >= 1
      AND payload_end_line >= payload_start_line)
  )
) STRICT;

CREATE TABLE cases (
  ordinal INTEGER PRIMARY KEY CHECK (ordinal >= 1),
  case_id TEXT NOT NULL UNIQUE,
  frame_id TEXT NOT NULL,
  pair_set TEXT NOT NULL,
  case_kind TEXT NOT NULL CHECK (case_kind IN ('positive', 'known_false_positive')),
  syntactic_type INTEGER,
  original_fragment_sha256 TEXT NOT NULL CHECK (length(original_fragment_sha256) = 64),
  modified_fragment_sha256 TEXT NOT NULL CHECK (length(modified_fragment_sha256) = 64),
  original_source_object_id TEXT NOT NULL REFERENCES generated_objects(object_id),
  original_destination_object_id TEXT NOT NULL REFERENCES generated_objects(object_id),
  modified_source_object_id TEXT NOT NULL REFERENCES generated_objects(object_id),
  modified_destination_object_id TEXT NOT NULL REFERENCES generated_objects(object_id),
  expected_match_kind TEXT NOT NULL,
  expected_move_count INTEGER NOT NULL CHECK (expected_move_count IN (0, 1)),
  from_start_line INTEGER NOT NULL CHECK (from_start_line >= 1),
  from_end_line INTEGER NOT NULL CHECK (from_end_line >= from_start_line),
  to_start_line INTEGER NOT NULL CHECK (to_start_line >= 1),
  to_end_line INTEGER NOT NULL CHECK (to_end_line >= to_start_line),
  type3_both_similarity REAL,
  type3_strength_stratum TEXT,
  min_tokens INTEGER,
  representative_functionality_id INTEGER,
  representative_function_id_one INTEGER,
  representative_function_id_two INTEGER
) STRICT;

CREATE TABLE case_rows (
  case_id TEXT NOT NULL REFERENCES cases(case_id),
  row_ordinal INTEGER NOT NULL CHECK (row_ordinal >= 1),
  catalog_pair_id INTEGER NOT NULL,
  source_row_id TEXT NOT NULL,
  source_row_multiplicity INTEGER NOT NULL CHECK (source_row_multiplicity >= 1),
  syntactic_type INTEGER,
  functionality_id INTEGER NOT NULL,
  function_id_one INTEGER NOT NULL,
  function_id_two INTEGER NOT NULL,
  direction_disposition TEXT,
  PRIMARY KEY (case_id, row_ordinal)
) STRICT;

CREATE INDEX case_rows_catalog_pair_idx ON case_rows(catalog_pair_id);
CREATE INDEX case_rows_source_row_idx ON case_rows(source_row_id);
"""
    )


def _fragment(compiled: VerifiedCompiledDataset, fragment_sha256: str) -> str:
    fragment_sha256 = _safe_sha256(fragment_sha256, "fragment SHA-256")
    path = (
        compiled.directory
        / "fragments"
        / fragment_sha256[:2]
        / f"{fragment_sha256}.java"
    )
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"compiled fragment is unavailable: {fragment_sha256}")
    contents = path.read_bytes()
    if hashlib.sha256(contents).hexdigest() != fragment_sha256:
        raise ValueError(f"compiled fragment checksum mismatch: {fragment_sha256}")
    return contents.decode("utf-8")


def _object_record(data_root: Path, value: GeneratedObject) -> tuple[Any, ...]:
    payload_range = value.payload_range or (None, None)
    return (
        value.object_id,
        value.wrapper_version,
        value.role,
        value.fragment_sha256,
        value.path.relative_to(data_root).as_posix(),
        value.size_bytes,
        value.sha256,
        payload_range[0],
        payload_range[1],
    )


def _insert_object(
    connection: sqlite3.Connection, data_root: Path, value: GeneratedObject
) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO generated_objects VALUES (?,?,?,?,?,?,?,?,?)",
        _object_record(data_root, value),
    )


def _frames(directory: Path, manifest: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    artifact = manifest["artifacts"]["frames"]
    path = directory / artifact["path"]
    observed = 0
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                frame = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"invalid selection frame at line {line_number}: {error}"
                ) from error
            if not isinstance(frame, dict):
                raise ValueError(
                    f"invalid selection frame at line {line_number}: expected object"
                )
            observed += 1
            yield frame
    expected = manifest["counts"]["selected_frames"]
    if observed != expected:
        raise ValueError(
            "selection frame count does not match manifest: "
            f"{observed} observed, {expected} declared"
        )


def _logical_inventory_sha256(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    declarations = (
        (
            "object",
            "SELECT object_id, wrapper_version, role, fragment_sha256, object_path, "
            "size_bytes, sha256, payload_start_line, payload_end_line "
            "FROM generated_objects ORDER BY object_id",
        ),
        (
            "case",
            "SELECT * FROM cases ORDER BY ordinal",
        ),
        (
            "case_row",
            "SELECT * FROM case_rows ORDER BY case_id, row_ordinal",
        ),
    )
    for kind, query in declarations:
        for row in connection.execute(query):
            digest.update(canonical_json({"kind": kind, "values": list(row)}))
            digest.update(b"\n")
    return digest.hexdigest()


def _benchmark_cases_identity(selection: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": BENCHMARK_CASES_SCHEMA_VERSION,
        "wrapper_version": STABLE_WRAPPER_VERSION,
        "compiled_dataset_id": selection["request"]["compiled_dataset_id"],
        "compiled_manifest_sha256": selection["compiled_dataset"][
            "manifest_sha256"
        ],
        "compiled_catalog_sha256": selection["compiled_dataset"]["catalog_sha256"],
        "selection_id": selection["selection_id"],
        "selection_frames_sha256": selection["artifacts"]["frames"]["sha256"],
    }


def _resolve_benchmark_cases(
    data_root: Path, identifier_or_path: str | Path
) -> Path:
    supplied = Path(identifier_or_path)
    if supplied.is_dir():
        return supplied.expanduser().resolve()
    return data_root / "benchmark-cases" / str(identifier_or_path)


def load_benchmark_cases(
    data_root: Path,
    identifier_or_path: str | Path,
    *,
    verification: str = "full",
) -> VerifiedBenchmarkCases:
    """Load and validate one immutable normalized benchmark-case catalog."""

    if verification not in {"identity", "full"}:
        raise ValueError(f"unsupported benchmark cases verification: {verification}")
    data_root = data_root.expanduser().resolve()
    directory = _resolve_benchmark_cases(data_root, identifier_or_path)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(
            f"normalized benchmark cases directory is unavailable: {directory}"
        )
    manifest_path = directory / "manifest.json"
    database_path = directory / "benchmark_cases.sqlite"
    for artifact in (manifest_path, database_path):
        if artifact.is_symlink() or not artifact.is_file():
            raise ValueError(
                f"normalized benchmark cases artifact is unavailable: {artifact}"
            )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != BENCHMARK_CASES_SCHEMA_VERSION
    ):
        raise ValueError(
            f"invalid normalized benchmark cases manifest: {manifest_path}"
        )
    identity = manifest.get("identity")
    if not isinstance(identity, dict):
        raise ValueError("normalized benchmark cases identity is missing or invalid")
    expected_id = content_identifier("bmb-benchmark-cases", identity)
    expected_identity_sha256 = hashlib.sha256(canonical_json(identity)).hexdigest()
    if (
        manifest.get("benchmark_cases_id") != expected_id
        or directory.name != expected_id
        or manifest.get("identity_sha256") != expected_identity_sha256
    ):
        raise ValueError("normalized benchmark cases identity does not match")
    artifact = manifest.get("artifacts", {}).get("benchmark_cases", {})
    if (
        artifact.get("path") != "benchmark_cases.sqlite"
        or database_path.stat().st_size != artifact.get("size_bytes")
    ):
        raise ValueError(
            "normalized benchmark cases database declaration does not match"
        )
    if verification == "full" and sha256_file(database_path) != artifact.get("sha256"):
        raise ValueError("normalized benchmark cases database checksum does not match")

    uri = f"{database_path.resolve().as_uri()}?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        application_id = connection.execute("PRAGMA application_id").fetchone()[0]
        if application_id != BENCHMARK_CASES_SQLITE_APPLICATION_ID:
            raise ValueError("normalized benchmark cases application id is invalid")
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        if user_version != BENCHMARK_CASES_SQLITE_USER_VERSION:
            raise ValueError("normalized benchmark cases schema version is invalid")
        metadata = connection.execute(
            "SELECT benchmark_cases_id, identity_sha256 "
            "FROM benchmark_cases_metadata WHERE singleton=1"
        ).fetchone()
        if metadata != (expected_id, expected_identity_sha256):
            raise ValueError(
                "normalized benchmark cases database identity does not match"
            )
        if verification == "full":
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError(
                    "normalized benchmark cases database integrity failed: "
                    f"{integrity}"
                )
            counts = manifest["counts"]
            observed_counts = {
                "cases": connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0],
                "case_rows": connection.execute(
                    "SELECT COUNT(*) FROM case_rows"
                ).fetchone()[0],
                "generated_objects": connection.execute(
                    "SELECT COUNT(*) FROM generated_objects"
                ).fetchone()[0],
            }
            if observed_counts != {
                key: counts[key]
                for key in ("cases", "case_rows", "generated_objects")
            }:
                raise ValueError("normalized benchmark cases counts do not match")
            if _logical_inventory_sha256(connection) != manifest.get(
                "logical_inventory_sha256"
            ):
                raise ValueError(
                    "normalized benchmark cases logical inventory does not match"
                )
            for object_id, object_path, size_bytes, sha256 in connection.execute(
                "SELECT object_id, object_path, size_bytes, sha256 "
                "FROM generated_objects ORDER BY object_id"
            ):
                path = data_root / object_path
                expected_path = data_root / "generated-objects" / f"{object_id}.java"
                if (
                    path != expected_path
                    or path.is_symlink()
                    or not path.is_file()
                    or path.stat().st_size != size_bytes
                    or path.stat().st_mode & 0o222
                    or sha256_file(path) != sha256
                ):
                    raise ValueError(
                        f"normalized benchmark cases object is invalid: {object_id}"
                    )
    return VerifiedBenchmarkCases(
        directory=directory,
        manifest=manifest,
        manifest_sha256=sha256_file(manifest_path),
        data_root=data_root,
    )


def publish_benchmark_cases(
    *, data_root: Path, selection: str | Path
) -> tuple[VerifiedBenchmarkCases, str]:
    """Publish or reuse immutable normalized benchmark cases for a selection."""

    data_root = data_root.expanduser().resolve()
    selection_directory = _resolve_selection(data_root, selection)
    selection_manifest = load_selection(selection_directory, verification="identity")
    identity = _benchmark_cases_identity(selection_manifest)
    benchmark_cases_id = content_identifier("bmb-benchmark-cases", identity)
    final = data_root / "benchmark-cases" / benchmark_cases_id
    if final.is_dir():
        return load_benchmark_cases(data_root, final, verification="full"), "reused"

    selection_manifest = load_selection(selection_directory, verification="full")
    if _benchmark_cases_identity(selection_manifest) != identity:
        raise ValueError(
            "selection identity changed during benchmark cases publication"
        )
    request = selection_manifest["request"]
    pair_set = request.get("pair_set")
    if pair_set not in PAIR_SETS:
        raise ValueError(f"unsupported normalized benchmark pair set: {pair_set}")
    case_kind = (
        "known_false_positive"
        if pair_set == "known-false-positive"
        else "positive"
    )
    expected_syntactic_type = None
    if case_kind != "known_false_positive":
        expected_syntactic_type = int(pair_set.removeprefix("type"))
    compiled = load_compiled_dataset(
        request["compiled_dataset_id"], data_root=data_root, verification="identity"
    )
    if (
        compiled.manifest_sha256
        != selection_manifest["compiled_dataset"]["manifest_sha256"]
        or compiled.manifest["artifacts"]["catalog"]["sha256"]
        != selection_manifest["compiled_dataset"]["catalog_sha256"]
    ):
        raise ValueError("selection compiled-dataset checksums do not match")

    root = data_root / "benchmark-cases"
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f".staging-{uuid.uuid4().hex}"
    staging.mkdir()
    database_path = staging / "benchmark_cases.sqlite"
    object_store = GeneratedObjectStore(data_root)
    objects: dict[tuple[str, str | None], GeneratedObject] = {}

    def generated_object(role: str, fragment_sha256: str | None) -> GeneratedObject:
        key = (role, fragment_sha256)
        existing = objects.get(key)
        if existing is not None:
            return existing
        fragment = (
            _fragment(compiled, fragment_sha256)
            if fragment_sha256 is not None
            else None
        )
        published = object_store.publish(role, fragment)
        if published.fragment_sha256 != fragment_sha256:
            raise ValueError("generated object fragment identity does not match")
        objects[key] = published
        return published

    try:
        with closing(sqlite3.connect(database_path)) as connection:
            _schema(connection)
            empty_source = generated_object(STABLE_SOURCE_ROLE, None)
            empty_destination = generated_object(STABLE_DESTINATION_ROLE, None)
            _insert_object(connection, data_root, empty_source)
            _insert_object(connection, data_root, empty_destination)
            case_count = row_count = 0
            for ordinal, frame in enumerate(
                _frames(selection_directory, selection_manifest), start=1
            ):
                direction = frame.get("direction")
                if not isinstance(direction, Mapping):
                    raise ValueError("selection frame is missing direction metadata")
                original_sha = _safe_sha256(
                    direction.get("original_fragment_sha256"),
                    "original fragment SHA-256",
                )
                modified_sha = _safe_sha256(
                    direction.get("modified_fragment_sha256"),
                    "modified fragment SHA-256",
                )
                case_id = _generated_input_id(original_sha, modified_sha)
                if frame.get("generated_input_id") != case_id:
                    raise ValueError(
                        "selection frame generated-input identity does not match"
                    )
                frame_id = frame.get("frame_id")
                if not isinstance(frame_id, str) or not frame_id:
                    raise ValueError("selection frame is missing frame_id")
                rows = frame.get("rows")
                if not isinstance(rows, list) or not rows:
                    raise ValueError("selection frame contains no contributing rows")
                if any(
                    not isinstance(row, Mapping)
                    or row.get("pair_kind") != case_kind
                    or (
                        expected_syntactic_type is not None
                        and row.get("syntactic_type") != expected_syntactic_type
                    )
                    for row in rows
                ):
                    raise ValueError(
                        "selection frame rows do not match the selected pair set"
                    )

                original_object = generated_object(STABLE_SOURCE_ROLE, original_sha)
                modified_object = generated_object(
                    STABLE_DESTINATION_ROLE, modified_sha
                )
                _insert_object(connection, data_root, original_object)
                _insert_object(connection, data_root, modified_object)
                assert original_object.payload_range is not None
                assert modified_object.payload_range is not None
                syntactic_types = sorted(
                    {
                        int(row["syntactic_type"])
                        for row in rows
                        if isinstance(row.get("syntactic_type"), int)
                    }
                )
                representative_type = (
                    expected_syntactic_type
                    if expected_syntactic_type is not None
                    else syntactic_types[0] if syntactic_types else None
                )
                min_tokens = [
                    row.get("tokens", {}).get("min")
                    for row in rows
                    if isinstance(row.get("tokens"), Mapping)
                    and isinstance(row.get("tokens", {}).get("min"), int)
                ]
                type3_similarity = type3_stratum = None
                if representative_type == 3 and case_kind == "positive":
                    type3_similarity, type3_stratum = _type3_frame_strength(rows)
                functionality_ids = frame.get("functionality_ids", [])
                function_ids = frame.get("function_ids", [])
                representative_functionality = (
                    functionality_ids[0]
                    if isinstance(functionality_ids, list)
                    and len(functionality_ids) == 1
                    else None
                )
                representative_function_one = (
                    function_ids[0]
                    if isinstance(function_ids, list) and function_ids
                    else None
                )
                representative_function_two = (
                    function_ids[1]
                    if isinstance(function_ids, list) and len(function_ids) > 1
                    else None
                )
                expected_match_kind = (
                    "whole_fragment_rejection"
                    if case_kind == "known_false_positive"
                    else {1: "type1", 2: "type2", 3: "type3"}[representative_type]
                )
                connection.execute(
                    "INSERT INTO cases VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        ordinal,
                        case_id,
                        frame_id,
                        pair_set,
                        case_kind,
                        representative_type,
                        original_sha,
                        modified_sha,
                        original_object.object_id,
                        empty_destination.object_id,
                        empty_source.object_id,
                        modified_object.object_id,
                        expected_match_kind,
                        0 if case_kind == "known_false_positive" else 1,
                        original_object.payload_range[0],
                        original_object.payload_range[1],
                        modified_object.payload_range[0],
                        modified_object.payload_range[1],
                        type3_similarity,
                        type3_stratum,
                        min(min_tokens) if min_tokens else None,
                        representative_functionality,
                        representative_function_one,
                        representative_function_two,
                    ),
                )
                for row_ordinal, row in enumerate(rows, start=1):
                    first = row.get("function_one")
                    second = row.get("function_two")
                    if not isinstance(first, Mapping) or not isinstance(
                        second, Mapping
                    ):
                        raise ValueError("selection row function metadata is invalid")
                    connection.execute(
                        "INSERT INTO case_rows VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (
                            case_id,
                            row_ordinal,
                            int(row["catalog_pair_id"]),
                            str(row["source_row_id"]),
                            int(row["source_row_multiplicity"]),
                            row.get("syntactic_type"),
                            int(row["functionality_id"]),
                            int(first["function_id"]),
                            int(second["function_id"]),
                            row.get("direction_disposition"),
                        ),
                    )
                    row_count += 1
                case_count += 1

            logical_inventory_sha256 = _logical_inventory_sha256(connection)
            identity_sha256 = hashlib.sha256(canonical_json(identity)).hexdigest()
            connection.execute(
                "INSERT INTO benchmark_cases_metadata VALUES (1,?,?)",
                (benchmark_cases_id, identity_sha256),
            )
            connection.commit()
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError(
                    "normalized benchmark cases database failed integrity check"
                )

        benchmark_cases_artifact = {
            "path": "benchmark_cases.sqlite",
            "size_bytes": database_path.stat().st_size,
            "sha256": sha256_file(database_path),
        }
        manifest = {
            "schema_version": BENCHMARK_CASES_SCHEMA_VERSION,
            "benchmark_cases_id": benchmark_cases_id,
            "identity_sha256": hashlib.sha256(canonical_json(identity)).hexdigest(),
            "created_at": utc_now(),
            "identity": identity,
            "selection": {
                "selection_id": selection_manifest["selection_id"],
                "pair_set": pair_set,
                "manifest_sha256": sha256_file(selection_directory / "manifest.json"),
                "frames_sha256": selection_manifest["artifacts"]["frames"]["sha256"],
            },
            "compiled_dataset": dict(selection_manifest["compiled_dataset"]),
            "wrapper_version": STABLE_WRAPPER_VERSION,
            "logical_inventory_sha256": logical_inventory_sha256,
            "counts": {
                "cases": case_count,
                "case_rows": row_count,
                "generated_objects": len(objects),
            },
            "artifacts": {"benchmark_cases": benchmark_cases_artifact},
        }
        (staging / "manifest.json").write_bytes(canonical_json(manifest) + b"\n")
        try:
            os.replace(staging, final)
        except OSError:
            if not final.is_dir():
                raise
            shutil.rmtree(staging)
            return (
                load_benchmark_cases(data_root, final, verification="full"),
                "reused",
            )
        return load_benchmark_cases(data_root, final, verification="full"), "created"
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


class SerialBenchmarkCaseRunner:
    """Yield benchmark cases through one reusable serial scratch archive."""

    def __init__(
        self,
        benchmark_cases: VerifiedBenchmarkCases,
        *,
        scratch_root: Path | None = None,
        profile_enabled: bool = False,
    ) -> None:
        self.benchmark_cases = benchmark_cases
        self.scratch_root = scratch_root
        self.profile_enabled = profile_enabled
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self._root: Path | None = None
        self.last_profile: dict[str, Any] | None = None

    def __enter__(self) -> SerialBenchmarkCaseRunner:
        parent = None
        if self.scratch_root is not None:
            parent = self.scratch_root.expanduser().resolve()
            parent.mkdir(parents=True, exist_ok=True)
        self._temporary = tempfile.TemporaryDirectory(
            prefix="bigmovebench-benchmark-cases-", dir=parent
        )
        self._root = Path(self._temporary.name)
        for revision in ("original", "modified"):
            for relative in (SYNTHETIC_SOURCE_PATH, SYNTHETIC_DESTINATION_PATH):
                (self._root / revision / relative).parent.mkdir(
                    parents=True, exist_ok=True
                )
        return self

    def __exit__(self, *_: object) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()
        self._temporary = None
        self._root = None

    def _fragment_text(self, fragment_sha256: str) -> str:
        dataset_id = self.benchmark_cases.manifest["compiled_dataset"]["dataset_id"]
        directory = (
            self.benchmark_cases.data_root
            / "bigclonebench"
            / "compiled"
            / dataset_id
            / "fragments"
        )
        path = directory / fragment_sha256[:2] / f"{fragment_sha256}.java"
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"compiled fragment is unavailable: {fragment_sha256}")
        contents = path.read_bytes()
        if hashlib.sha256(contents).hexdigest() != fragment_sha256:
            raise ValueError(f"compiled fragment checksum mismatch: {fragment_sha256}")
        return contents.decode("utf-8")

    def _link(self, object_path: str, destination: Path) -> bool:
        source = self.benchmark_cases.data_root / object_path
        if source.is_symlink() or not source.is_file():
            raise ValueError(
                f"normalized benchmark cases object is unavailable: {source}"
            )
        try:
            os.link(source, destination)
            return True
        except OSError:
            destination.symlink_to(source)
            return False

    def clear_scratch(self) -> int:
        if self._root is None:
            raise RuntimeError(
                "serial benchmark-case runner must be used as a context manager"
            )
        removed = 0
        for revision in ("original", "modified"):
            for relative in (SYNTHETIC_SOURCE_PATH, SYNTHETIC_DESTINATION_PATH):
                path = self._root / revision / relative
                if path.exists() or path.is_symlink():
                    path.unlink()
                    removed += 1
        return removed

    def cases(self) -> Iterator[InputPair]:
        if self._root is None:
            raise RuntimeError(
                "serial benchmark-case runner must be used as a context manager"
            )
        database_path = self.benchmark_cases.directory / "benchmark_cases.sqlite"
        uri = f"{database_path.resolve().as_uri()}?mode=ro&immutable=1"
        query = """
SELECT c.*,
  (
    SELECT group_concat(syntactic_type, ',')
    FROM (
      SELECT DISTINCT syntactic_type
      FROM case_rows AS typed_rows
      WHERE typed_rows.case_id=c.case_id AND syntactic_type IS NOT NULL
      ORDER BY syntactic_type
    )
  ) AS syntactic_types,
  os.object_path AS original_source_path,
  od.object_path AS original_destination_path,
  ms.object_path AS modified_source_path,
  md.object_path AS modified_destination_path
FROM cases AS c
JOIN generated_objects AS os ON os.object_id=c.original_source_object_id
JOIN generated_objects AS od ON od.object_id=c.original_destination_object_id
JOIN generated_objects AS ms ON ms.object_id=c.modified_source_object_id
JOIN generated_objects AS md ON md.object_id=c.modified_destination_object_id
ORDER BY c.ordinal
"""
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(query)
            ordinal = 0
            while True:
                case_started_ns = (
                    time.perf_counter_ns() if self.profile_enabled else 0
                )
                lookup_started_ns = (
                    time.perf_counter_ns() if self.profile_enabled else 0
                )
                row = cursor.fetchone()
                if row is None:
                    break
                lookup_ms = (
                    (time.perf_counter_ns() - lookup_started_ns) / 1_000_000.0
                    if self.profile_enabled
                    else 0.0
                )
                self.clear_scratch()
                scratch_started_ns = (
                    time.perf_counter_ns() if self.profile_enabled else 0
                )
                original = self._root / "original"
                modified = self._root / "modified"
                original_source = original / SYNTHETIC_SOURCE_PATH
                original_destination = original / SYNTHETIC_DESTINATION_PATH
                modified_source = modified / SYNTHETIC_SOURCE_PATH
                modified_destination = modified / SYNTHETIC_DESTINATION_PATH
                hard_links = sum(
                    (
                        self._link(row["original_source_path"], original_source),
                        self._link(
                            row["original_destination_path"], original_destination
                        ),
                        self._link(row["modified_source_path"], modified_source),
                        self._link(
                            row["modified_destination_path"], modified_destination
                        ),
                    )
                )
                original_fragment = self._fragment_text(
                    row["original_fragment_sha256"]
                )
                modified_fragment = self._fragment_text(
                    row["modified_fragment_sha256"]
                )
                metadata = {
                    "source": "BigCloneBench normalized benchmark cases",
                    "case_kind": row["case_kind"],
                    "clone_type": (
                        "known_false_positive"
                        if row["case_kind"] == "known_false_positive"
                        else f"type{row['syntactic_type']}"
                    ),
                    "syntactic_type": row["syntactic_type"],
                    "syntactic_types": (
                        [int(value) for value in row["syntactic_types"].split(",")]
                        if row["syntactic_types"]
                        else []
                    ),
                    "type3_both_similarity": row["type3_both_similarity"],
                    "type3_strength_stratum": row["type3_strength_stratum"],
                    "min_tokens": row["min_tokens"],
                    "functionality_id": row["representative_functionality_id"],
                    "function_id_one": row["representative_function_id_one"],
                    "function_id_two": row["representative_function_id_two"],
                    "compiled_dataset_id": self.benchmark_cases.manifest[
                        "compiled_dataset"
                    ]["dataset_id"],
                    "selection_id": self.benchmark_cases.manifest["selection"][
                        "selection_id"
                    ],
                    "frame_id": row["frame_id"],
                    "generated_input_id": row["case_id"],
                    "synthetic_wrapper_version": STABLE_WRAPPER_VERSION,
                    "fragment_one": {
                        "sha256": row["original_fragment_sha256"],
                        "text": original_fragment,
                    },
                    "fragment_two": {
                        "sha256": row["modified_fragment_sha256"],
                        "text": modified_fragment,
                    },
                    "fragment_relation": _fragment_relation(
                        original_fragment, modified_fragment
                    ),
                    "expected": {
                        "move_count": row["expected_move_count"],
                        "from_raw_text": original_fragment,
                        "to_raw_text": modified_fragment,
                        "from_generated_text": indent_fragment(original_fragment),
                        "to_generated_text": indent_fragment(modified_fragment),
                        "from_start_line": row["from_start_line"],
                        "from_end_line": row["from_end_line"],
                        "to_start_line": row["to_start_line"],
                        "to_end_line": row["to_end_line"],
                    },
                }
                if self.profile_enabled:
                    scratch_ms = (
                        time.perf_counter_ns() - scratch_started_ns
                    ) / 1_000_000.0
                    self.last_profile = {
                        "case_id": row["case_id"],
                        "ordinal": ordinal,
                        "started_ns": case_started_ns,
                        "phases_ms": {
                            "runner.case_lookup_ms": lookup_ms,
                            "runner.scratch_prepare_ms": scratch_ms,
                        },
                        "counters": {"runner.hard_links": hard_links},
                    }
                ordinal += 1
                yield InputPair(
                    case_id=row["case_id"],
                    original=original,
                    modified=modified,
                    metadata=metadata,
                )

    def run(self, callback: Callable[[InputPair], None]) -> int:
        completed = 0
        for case in self.cases():
            callback(case)
            completed += 1
        return completed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection", help="Selection ID or directory.")
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        benchmark_cases, disposition = publish_benchmark_cases(
            data_root=args.cache_root, selection=args.selection
        )
        print(f"BigMoveBench normalized benchmark cases: {disposition}")
        print(f"benchmark_cases_id={benchmark_cases.benchmark_cases_id}")
        print(f"directory={benchmark_cases.directory}")
        print(
            f"cases={benchmark_cases.manifest['counts']['cases']} "
            f"objects={benchmark_cases.manifest['counts']['generated_objects']}"
        )
        return 0
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
