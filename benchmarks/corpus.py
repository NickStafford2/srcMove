"""Immutable input snapshot, srcDiff corpus, and srcMove run stages."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from benchmarks.contracts import (
    canonical_json,
    DatasetAdapter,
    InputPair,
    SnapshotMaterializingAdapter,
    RunMode,
    SemanticResult,
    SemanticStatus,
    content_identifier,
)
from benchmarks.process import (
    execute_attempt,
    recover_interrupted_attempts,
    set_attempt_output_retention,
    validate_srcdiff_xml,
    write_json_atomic,
)
from benchmarks.provenance import (
    collect_run_observation,
    observe_executable,
    sha256_file,
    utc_now,
)


INPUT_SNAPSHOT_SCHEMA_VERSION = 1
GENERATION_BATCH_SCHEMA_VERSION = 2
CORPUS_SCHEMA_VERSION = 4
RUN_SCHEMA_VERSION = 3
DEFAULT_EXCLUDED_SUFFIXES = (".py",)
TimingCallback = Callable[[str, float], None]


@dataclass(frozen=True)
class VerifiedSnapshot:
    """An input snapshot verified while loading or trusted after creation."""

    directory: Path
    manifest: dict[str, Any]
    manifest_sha256: str

    @property
    def snapshot_id(self) -> str:
        return self.manifest["input_snapshot_id"]

    def __iter__(self) -> Iterator[Path | dict[str, Any]]:
        """Preserve tuple unpacking for callers migrating to the typed API."""

        yield self.directory
        yield self.manifest


@dataclass(frozen=True)
class VerifiedCorpus:
    """A srcDiff corpus verified while loading or trusted after promotion."""

    directory: Path
    manifest: dict[str, Any]
    manifest_sha256: str

    @property
    def corpus_id(self) -> str:
        return self.manifest["corpus_id"]

    def __iter__(self) -> Iterator[Path | dict[str, Any]]:
        """Preserve tuple unpacking for callers migrating to the typed API."""

        yield self.directory
        yield self.manifest


@contextmanager
def _timed(
    callback: TimingCallback | None, name: str
) -> Iterator[None]:
    started = time.monotonic()
    try:
        yield
    finally:
        if callback is not None:
            callback(name, time.monotonic() - started)


def _validate_case_id(case_id: str) -> None:
    if not case_id or case_id in {".", ".."}:
        raise ValueError("case id must not be empty")
    if Path(case_id).name != case_id or "/" in case_id or "\\" in case_id:
        raise ValueError("case id must be one safe path component")


def _normalized_excluded_suffixes(
    filter_configuration: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    raw = (filter_configuration or {}).get("excluded_suffixes", [])
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ValueError("filter_configuration.excluded_suffixes must be a string list")
    normalized = set(DEFAULT_EXCLUDED_SUFFIXES) | {
        (item if item.startswith(".") else f".{item}").lower() for item in raw
    }
    if "." in normalized:
        raise ValueError("excluded suffix must contain characters after the dot")
    return tuple(sorted(normalized))


def _inventory(
    path: Path, excluded_suffixes: Sequence[str] = ()
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    resolved = path.expanduser().resolve()
    if resolved.is_symlink():
        raise ValueError(f"input snapshot source must not be a symbolic link: {resolved}")
    if resolved.is_file():
        if resolved.suffix.lower() in excluded_suffixes:
            return "file", [], [{"path": resolved.name, "reason": "excluded_suffix"}]
        return "file", [
            {
                "path": resolved.name,
                "size_bytes": resolved.stat().st_size,
                "sha256": sha256_file(resolved),
            }
        ], []
    if not resolved.is_dir():
        raise ValueError(f"input snapshot source not found: {resolved}")

    files = []
    excluded = []
    for candidate in sorted(resolved.rglob("*")):
        if candidate.is_symlink():
            raise ValueError(
                "input snapshot source tree must not contain symbolic links: "
                f"{candidate}"
            )
        if candidate.is_file():
            relative_path = candidate.relative_to(resolved).as_posix()
            if candidate.suffix.lower() in excluded_suffixes:
                excluded.append({"path": relative_path, "reason": "excluded_suffix"})
                continue
            files.append(
                {
                    "path": relative_path,
                    "size_bytes": candidate.stat().st_size,
                    "sha256": sha256_file(candidate),
                }
            )
    return "directory", files, excluded


def _input_identity(
    path: Path, excluded_suffixes: Sequence[str] = ()
) -> dict[str, Any]:
    kind, files, excluded = _inventory(path, excluded_suffixes)
    return {"kind": kind, "files": files, "excluded": excluded}


def _copy_input(source: Path, destination: Path, identity: Mapping[str, Any]) -> str:
    destination.mkdir(parents=True, exist_ok=False)
    if identity["kind"] == "file":
        if not identity["files"]:
            raise ValueError(f"filter excluded the complete file input: {source}")
        target = destination / source.name
        shutil.copy2(source, target)
        return target.name
    for entry in identity["files"]:
        relative = Path(entry["path"])
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)
    return "."


def _snapshot_identity_payload(
    *,
    adapter: DatasetAdapter | SnapshotMaterializingAdapter,
    source: Mapping[str, Any],
    filter_configuration: Mapping[str, Any] | None,
    excluded_suffixes: Sequence[str],
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": INPUT_SNAPSHOT_SCHEMA_VERSION,
        "adapter": {"name": adapter.name, "version": adapter.version},
        "source": dict(source),
        "filter_configuration": {
            **dict(filter_configuration or {}),
            "excluded_suffixes": list(excluded_suffixes),
        },
        "cases": [
            {
                key: case[key]
                for key in ("case_id", "original", "modified", "metadata")
            }
            for case in cases
        ],
    }


def _snapshot_manifest(
    identity_payload: Mapping[str, Any], manifest_cases: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    return {
        "schema_version": INPUT_SNAPSHOT_SCHEMA_VERSION,
        "input_snapshot_id": content_identifier(
            "input-snapshot", dict(identity_payload)
        ),
        "identity_sha256": hashlib.sha256(
            canonical_json(dict(identity_payload))
        ).hexdigest(),
        "created_at": utc_now(),
        "adapter": identity_payload["adapter"],
        "source": identity_payload["source"],
        "filter_configuration": identity_payload["filter_configuration"],
        "counts": {
            "selected": len(manifest_cases),
            "included_files": sum(
                len(case[side]["files"])
                for case in manifest_cases
                for side in ("original", "modified")
            ),
            "excluded_files": sum(
                len(case[side]["excluded"])
                for case in manifest_cases
                for side in ("original", "modified")
            ),
        },
        "cases": list(manifest_cases),
    }


def _manifest_value_checksum(value: Mapping[str, Any]) -> str:
    serialized = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _verified_snapshot(
    directory: Path,
    manifest: dict[str, Any],
    manifest_sha256: str | None = None,
) -> VerifiedSnapshot:
    return VerifiedSnapshot(
        directory=directory,
        manifest=manifest,
        manifest_sha256=manifest_sha256 or _manifest_value_checksum(manifest),
    )


def _verified_corpus(
    directory: Path,
    manifest: dict[str, Any],
    manifest_sha256: str | None = None,
) -> VerifiedCorpus:
    return VerifiedCorpus(
        directory=directory,
        manifest=manifest,
        manifest_sha256=manifest_sha256 or _manifest_value_checksum(manifest),
    )


def _observe_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "missing"}
    observation = {
        "path": path.name,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return {"status": "malformed", "error": str(error), **observation}
    if not isinstance(value, dict):
        return {
            "status": "malformed",
            "error": "results root must be an object",
            **observation,
        }
    return {"status": "valid", **observation}


def _resolve_manifest(root: Path, kind: str, identifier_or_path: str | Path) -> Path:
    supplied = Path(identifier_or_path)
    if supplied.is_file():
        return supplied.resolve()
    if supplied.is_dir():
        candidate = supplied / "manifest.json"
        if candidate.is_file():
            return candidate.resolve()
    candidate = root / kind / os.fspath(identifier_or_path) / "manifest.json"
    if not candidate.is_file():
        label = {"input-snapshots": "input snapshot", "corpora": "corpus"}.get(
            kind, kind
        )
        raise FileNotFoundError(f"{label} manifest not found: {identifier_or_path}")
    return candidate.resolve()


def _load_manifest(path: Path, schema_version: int, id_field: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != schema_version:
        raise ValueError(f"unsupported or malformed manifest: {path}")
    if not isinstance(value.get(id_field), str):
        raise ValueError(f"manifest is missing {id_field}: {path}")
    return value


def _verify_input_snapshot(
    directory: Path,
    manifest: Mapping[str, Any],
    *,
    verification: str = "full",
) -> None:
    if verification not in {"identity", "full"}:
        raise ValueError(f"unsupported input snapshot verification: {verification}")
    identity_payload = {
        "schema_version": INPUT_SNAPSHOT_SCHEMA_VERSION,
        "adapter": manifest["adapter"],
        "source": manifest["source"],
        "filter_configuration": manifest["filter_configuration"],
        "cases": [
            {
                key: case[key]
                for key in ("case_id", "original", "modified", "metadata")
            }
            for case in manifest["cases"]
        ],
    }
    expected_id = content_identifier("input-snapshot", identity_payload)
    expected_identity_checksum = hashlib.sha256(
        canonical_json(identity_payload)
    ).hexdigest()
    if manifest["input_snapshot_id"] != expected_id:
        raise ValueError("input snapshot identity does not match its manifest")
    if manifest["identity_sha256"] != expected_identity_checksum:
        raise ValueError("input snapshot identity checksum does not match its manifest")
    if verification == "identity":
        return
    for case in manifest["cases"]:
        original = directory / case["original_path"]
        modified = directory / case["modified_path"]
        if _input_identity(original) != {**case["original"], "excluded": []}:
            raise ValueError(
                f"input snapshot original checksum mismatch: {case['case_id']}"
            )
        if _input_identity(modified) != {**case["modified"], "excluded": []}:
            raise ValueError(
                f"input snapshot modified checksum mismatch: {case['case_id']}"
            )


def _verify_corpus(
    directory: Path,
    manifest: Mapping[str, Any],
    *,
    verification: str = "full",
) -> None:
    if verification not in {"identity", "full"}:
        raise ValueError(f"unsupported corpus verification: {verification}")
    artifact = manifest["srcdiff"].get("artifact", {})
    accepted_checksums = [
        {"case_id": case["case_id"], "sha256": case["xml"]["sha256"]}
        for case in manifest["cases"]
        if case["generation_status"] == "accepted"
    ]
    expected_id = content_identifier(
        "corpus",
        {
            "schema_version": CORPUS_SCHEMA_VERSION,
            "input_snapshot_identity_sha256": manifest[
                "input_snapshot_identity_sha256"
            ],
            "srcdiff_sha256": artifact.get("sha256"),
            "generation_configuration": manifest["generation_configuration"],
            "accepted_xml": accepted_checksums,
        },
    )
    if manifest["corpus_id"] != expected_id:
        raise ValueError("corpus identity does not match its manifest")
    if verification == "identity":
        return
    for case in manifest["cases"]:
        if case["generation_status"] != "accepted":
            continue
        input_path = directory / case["input_path"]
        if not input_path.is_file() or sha256_file(input_path) != case["xml"]["sha256"]:
            raise ValueError(f"corpus input checksum mismatch: {case['case_id']}")


def load_input_snapshot(
    data_root: Path,
    identifier_or_path: str | Path,
    *,
    verification: str = "full",
) -> VerifiedSnapshot:
    """Load and checksum-verify one current-schema input snapshot."""

    manifest_path = _resolve_manifest(
        data_root, "input-snapshots", identifier_or_path
    )
    manifest = _load_manifest(
        manifest_path, INPUT_SNAPSHOT_SCHEMA_VERSION, "input_snapshot_id"
    )
    directory = manifest_path.parent
    _verify_input_snapshot(directory, manifest, verification=verification)
    return _verified_snapshot(directory, manifest, sha256_file(manifest_path))


def load_corpus(
    data_root: Path,
    identifier_or_path: str | Path,
    *,
    verification: str = "full",
) -> VerifiedCorpus:
    """Load and checksum-verify one current-schema corpus."""

    manifest_path = _resolve_manifest(data_root, "corpora", identifier_or_path)
    manifest = _load_manifest(
        manifest_path, CORPUS_SCHEMA_VERSION, "corpus_id"
    )
    directory = manifest_path.parent
    _verify_corpus(directory, manifest, verification=verification)
    return _verified_corpus(directory, manifest, sha256_file(manifest_path))


def _create_materialized_input_snapshot(
    *,
    data_root: Path,
    adapter: SnapshotMaterializingAdapter,
    source: Mapping[str, Any],
    filter_configuration: Mapping[str, Any] | None,
    excluded_suffixes: Sequence[str],
    status_callback: Callable[[str], None] | None,
) -> VerifiedSnapshot:
    snapshots_root = data_root / "input-snapshots"
    staging = snapshots_root / f".staging-{uuid.uuid4()}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        materialized = list(
            adapter.materialize_input_pairs(
                staging / "sources", excluded_suffixes
            )
        )
        if not materialized:
            raise ValueError("snapshot materializer produced no cases")
        manifest_cases = []
        for case in materialized:
            _validate_case_id(case.case_id)
            manifest_cases.append(
                {
                    "case_id": case.case_id,
                    "original": dict(case.original),
                    "modified": dict(case.modified),
                    "metadata": dict(case.metadata),
                    "original_path": (
                        Path("sources") / case.case_id / "original"
                    ).as_posix(),
                    "modified_path": (
                        Path("sources") / case.case_id / "modified"
                    ).as_posix(),
                }
            )
        identity_payload = _snapshot_identity_payload(
            adapter=adapter,
            source=source,
            filter_configuration=filter_configuration,
            excluded_suffixes=excluded_suffixes,
            cases=manifest_cases,
        )
        manifest = _snapshot_manifest(identity_payload, manifest_cases)
        final_dir = snapshots_root / manifest["input_snapshot_id"]
        if final_dir.is_dir():
            shutil.rmtree(staging)
            existing = _load_manifest(
                final_dir / "manifest.json",
                INPUT_SNAPSHOT_SCHEMA_VERSION,
                "input_snapshot_id",
            )
            _verify_input_snapshot(final_dir, existing)
            if status_callback is not None:
                status_callback("reused")
            return _verified_snapshot(
                final_dir, existing, sha256_file(final_dir / "manifest.json")
            )

        write_json_atomic(staging / "manifest.json", manifest)
        snapshots_root.mkdir(parents=True, exist_ok=True)
        os.replace(staging, final_dir)
        if status_callback is not None:
            status_callback("created")
        return _verified_snapshot(final_dir, manifest)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def create_input_snapshot(
    *,
    data_root: Path,
    adapter: DatasetAdapter | SnapshotMaterializingAdapter,
    source: Mapping[str, Any],
    filter_configuration: Mapping[str, Any] | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> VerifiedSnapshot:
    """Freeze and checksum old/new source pairs for later srcDiff execution."""

    excluded_suffixes = _normalized_excluded_suffixes(filter_configuration)
    if isinstance(adapter, SnapshotMaterializingAdapter):
        return _create_materialized_input_snapshot(
            data_root=data_root,
            adapter=adapter,
            source=source,
            filter_configuration=filter_configuration,
            excluded_suffixes=excluded_suffixes,
            status_callback=status_callback,
        )

    cases = list(adapter.input_pairs())
    if not cases:
        raise ValueError("dataset adapter produced no cases")

    identities = []
    for case in cases:
        _validate_case_id(case.case_id)
        identities.append(
            {
                "case_id": case.case_id,
                "original": _input_identity(case.original, excluded_suffixes),
                "modified": _input_identity(case.modified, excluded_suffixes),
                "metadata": dict(case.metadata),
            }
        )
    identity_payload = _snapshot_identity_payload(
        adapter=adapter,
        source=source,
        filter_configuration=filter_configuration,
        excluded_suffixes=excluded_suffixes,
        cases=identities,
    )
    input_snapshot_id = content_identifier("input-snapshot", identity_payload)
    final_dir = data_root / "input-snapshots" / input_snapshot_id
    if final_dir.is_dir():
        manifest = _load_manifest(
            final_dir / "manifest.json",
            INPUT_SNAPSHOT_SCHEMA_VERSION,
            "input_snapshot_id",
        )
        _verify_input_snapshot(final_dir, manifest)
        if status_callback is not None:
            status_callback("reused")
        return _verified_snapshot(
            final_dir, manifest, sha256_file(final_dir / "manifest.json")
        )

    staging = data_root / "input-snapshots" / f".staging-{uuid.uuid4()}"
    staging.mkdir(parents=True, exist_ok=False)
    manifest_cases = []
    try:
        for case, identity in zip(cases, identities, strict=True):
            case_root = staging / "sources" / case.case_id
            original_path = _copy_input(
                case.original, case_root / "original", identity["original"]
            )
            modified_path = _copy_input(
                case.modified, case_root / "modified", identity["modified"]
            )
            manifest_cases.append(
                {
                    **identity,
                    "original_path": (
                        Path("sources") / case.case_id / "original" / original_path
                    ).as_posix(),
                    "modified_path": (
                        Path("sources") / case.case_id / "modified" / modified_path
                    ).as_posix(),
                }
            )
        manifest = _snapshot_manifest(identity_payload, manifest_cases)
        write_json_atomic(staging / "manifest.json", manifest)
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, final_dir)
        if status_callback is not None:
            status_callback("created")
        return _verified_snapshot(final_dir, manifest)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def generate_corpus(
    *,
    data_root: Path,
    input_snapshot: VerifiedSnapshot | str | Path,
    srcdiff: Path,
    timeout_seconds: float,
    use_position: bool = False,
    use_archive: bool = True,
    source_encoding: str = "UTF-8",
    retry_failed: bool = False,
    selected_case_ids: Sequence[str] = (),
    semantic_validator: Callable[[InputPair, Path], SemanticResult] | None = None,
    semantic_oracle: Mapping[str, Any] | None = None,
    activity_callback: Callable[[str, str], None] | None = None,
    timing_callback: TimingCallback | None = None,
    srcdiff_observation: Mapping[str, Any] | None = None,
) -> VerifiedCorpus:
    if isinstance(input_snapshot, VerifiedSnapshot):
        snapshot = input_snapshot
        if timing_callback is not None:
            timing_callback("srcdiff_input_snapshot_verification_seconds", 0.0)
    else:
        with _timed(timing_callback, "srcdiff_input_snapshot_verification_seconds"):
            snapshot = load_input_snapshot(data_root, input_snapshot)
    input_snapshot_manifest = snapshot.manifest
    input_snapshot_dir = snapshot.directory
    attempts_root = data_root / "attempts"
    attempts_root.mkdir(parents=True, exist_ok=True)
    with _timed(timing_callback, "srcdiff_executable_observation_seconds"):
        resolved_srcdiff_observation = (
            dict(srcdiff_observation)
            if srcdiff_observation is not None
            else observe_executable(srcdiff)
        )
    generation_configuration = {
        "position": use_position,
        "archive": use_archive,
        "source_encoding": source_encoding,
        "timeout_seconds": timeout_seconds,
        "semantic_oracle": dict(semantic_oracle or {}),
    }
    artifact = resolved_srcdiff_observation.get("artifact", {})
    batch_identity = {
        "input_snapshot_identity_sha256": input_snapshot_manifest["identity_sha256"],
        "srcdiff_sha256": artifact.get("sha256"),
        "generation_configuration": generation_configuration,
    }
    batch_id = content_identifier("generation", batch_identity)
    batch_path = data_root / "generation-batches" / batch_id / "batch.json"
    batch_existed = batch_path.is_file()
    if batch_existed:
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
        if batch.get("identity") != batch_identity:
            raise ValueError(f"generation batch identity mismatch: {batch_path}")
    else:
        batch = {
            "schema_version": GENERATION_BATCH_SCHEMA_VERSION,
            "generation_id": batch_id,
            "identity": batch_identity,
            "created_at": utc_now(),
            "cases": [],
        }
        # Establish the generation before execution so a later invocation can
        # distinguish an interrupted batch from a genuinely new one.
        with _timed(timing_callback, "srcdiff_generation_checkpoint_seconds"):
            write_json_atomic(batch_path, batch)
    records_by_id = {record["case_id"]: record for record in batch["cases"]}
    input_snapshot_cases = {
        case["case_id"]: case for case in input_snapshot_manifest["cases"]
    }
    known_ids = set(input_snapshot_cases)
    selected = set(selected_case_ids) if selected_case_ids else known_ids
    unknown = selected - known_ids
    if unknown:
        raise ValueError(
            f"unknown input snapshot case(s): {', '.join(sorted(unknown))}"
        )

    def validate_semantics(case_id: str, xml_path: Path) -> dict[str, Any]:
        if semantic_validator is None:
            return {
                "semantic_status": SemanticStatus.NOT_APPLICABLE.value,
                "semantic_details": {},
            }
        snapshot_case = input_snapshot_cases[case_id]
        result = semantic_validator(
            InputPair(
                case_id=case_id,
                original=input_snapshot_dir / snapshot_case["original_path"],
                modified=input_snapshot_dir / snapshot_case["modified_path"],
                metadata=snapshot_case["metadata"],
            ),
            xml_path,
        )
        return {
            "semantic_status": result.status.value,
            "semantic_details": dict(result.details),
        }
    retry_may_be_interrupted = retry_failed and any(
        case_id in selected
        and record.get("generation_status") == "failed"
        for case_id, record in records_by_id.items()
    )
    needs_reconciliation = batch_existed and (
        not known_ids.issubset(records_by_id) or retry_may_be_interrupted
    )
    if needs_reconciliation:
        with _timed(timing_callback, "srcdiff_attempt_recovery_seconds"):
            recover_interrupted_attempts(attempts_root)
        terminal_paths = attempts_root.glob("attempt-*/attempt.json")
    else:
        if timing_callback is not None:
            timing_callback("srcdiff_attempt_recovery_seconds", 0.0)
        terminal_paths = ()

    # Only an existing incomplete generation can contain terminal evidence that
    # is absent from its batch checkpoint. Normal fresh and cached runs avoid the
    # global attempt scan.
    with _timed(timing_callback, "srcdiff_attempt_reconciliation_seconds"):
        for terminal_path in terminal_paths:
            try:
                terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if terminal.get("context", {}).get("generation_id") != batch_id:
                continue
            case_id = terminal.get("case_id")
            if not isinstance(case_id, str):
                continue
            previous = records_by_id.get(case_id)
            ordinal = terminal.get("retry_ordinal", 0)
            if previous is not None and previous.get("retry_ordinal", 0) >= ordinal:
                continue
            semantic = (
                validate_semantics(
                    case_id, terminal_path.parent / "partial.srcdiff.xml"
                )
                if terminal.get("admitted")
                else {
                    "semantic_status": SemanticStatus.NOT_CHECKED.value,
                    "semantic_details": {},
                }
            )
            records_by_id[case_id] = {
                "case_id": case_id,
                "metadata": input_snapshot_cases[case_id]["metadata"],
                "attempt_id": terminal["attempt_id"],
                "parent_attempt_id": terminal.get("parent_attempt_id"),
                "retry_ordinal": ordinal,
                "generation_status": (
                    "accepted" if terminal.get("admitted") else "failed"
                ),
                "xml": terminal.get("xml", {"status": "not_checked"}),
                **semantic,
                "attempt_path": str(terminal_path.parent.relative_to(data_root)),
            }
    for case in input_snapshot_manifest["cases"]:
        case_id = case["case_id"]
        previous = records_by_id.get(case_id)
        should_retry = (
            previous is not None
            and previous["generation_status"] == "failed"
            and retry_failed
            and case_id in selected
        )
        if previous is not None and not should_retry:
            if activity_callback is not None:
                activity_callback("reused", case_id)
            continue
        original = input_snapshot_dir / case["original_path"]
        modified = input_snapshot_dir / case["modified_path"]

        def command(output: Path) -> Sequence[str]:
            value = [str(srcdiff)]
            if use_position:
                value.append("--position")
            if use_archive:
                value.append("--archive")
            if source_encoding:
                value.extend(["--src-encoding", source_encoding])
            value.extend([str(original), str(modified), "-o", str(output)])
            return value

        if activity_callback is not None:
            activity_callback("running", case_id)
        with _timed(timing_callback, "srcdiff_attempt_wall_seconds"):
            attempt_dir, attempt = execute_attempt(
                attempts_root=attempts_root,
                stage="srcdiff",
                case_id=case_id,
                command_factory=command,
                cwd=input_snapshot_dir,
                timeout_seconds=timeout_seconds,
                xml_validator=lambda path: validate_srcdiff_xml(
                    path, "archive" if use_archive else "single_file"
                ),
                output_filename="partial.srcdiff.xml",
                parent_attempt_id=previous["attempt_id"] if should_retry else None,
                retry_ordinal=(
                    previous.get("retry_ordinal", 0) + 1 if should_retry else 0
                ),
                context={
                    "generation_id": batch_id,
                    "input_snapshot_id": snapshot.snapshot_id,
                    "input_snapshot_manifest_sha256": snapshot.manifest_sha256,
                    "original_path": case["original_path"],
                    "modified_path": case["modified_path"],
                    "expected_shape": "archive" if use_archive else "single_file",
                    "srcdiff_sha256": artifact.get("sha256"),
                },
            )
        semantic = (
            validate_semantics(case_id, attempt_dir / "partial.srcdiff.xml")
            if attempt["admitted"]
            else {
                "semantic_status": SemanticStatus.NOT_CHECKED.value,
                "semantic_details": {},
            }
        )
        case_record = {
            "case_id": case_id,
            "metadata": case["metadata"],
            "attempt_id": attempt["attempt_id"],
            "parent_attempt_id": attempt["parent_attempt_id"],
            "retry_ordinal": attempt["retry_ordinal"],
            "generation_status": "accepted" if attempt["admitted"] else "failed",
            "xml": attempt["xml"],
            **semantic,
            "attempt_path": str(attempt_dir.relative_to(data_root)),
        }
        records_by_id[case_id] = case_record
        if activity_callback is not None:
            activity_callback(
                "accepted"
                if case_record["generation_status"] == "accepted"
                else "failed",
                case_id,
            )
        batch["cases"] = [
            records_by_id[item["case_id"]]
            for item in input_snapshot_manifest["cases"]
            if item["case_id"] in records_by_id
        ]
        batch["updated_at"] = utc_now()
        with _timed(timing_callback, "srcdiff_generation_checkpoint_seconds"):
            write_json_atomic(batch_path, batch)

    case_records = [
        records_by_id[case["case_id"]] for case in input_snapshot_manifest["cases"]
    ]
    accepted_checksums = [
        {"case_id": record["case_id"], "sha256": record["xml"]["sha256"]}
        for record in case_records
        if record["generation_status"] == "accepted"
    ]
    identity_payload = {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "input_snapshot_identity_sha256": input_snapshot_manifest["identity_sha256"],
        "srcdiff_sha256": artifact.get("sha256"),
        "generation_configuration": generation_configuration,
        "accepted_xml": accepted_checksums,
    }
    corpus_id = content_identifier("corpus", identity_payload)
    final_dir = data_root / "corpora" / corpus_id
    if final_dir.is_dir():
        manifest = _load_manifest(
            final_dir / "manifest.json", CORPUS_SCHEMA_VERSION, "corpus_id"
        )
        with _timed(timing_callback, "srcdiff_corpus_verification_seconds"):
            _verify_corpus(final_dir, manifest, verification="identity")
        if timing_callback is not None:
            timing_callback("srcdiff_attempt_compaction_seconds", 0.0)
        return _verified_corpus(
            final_dir, manifest, sha256_file(final_dir / "manifest.json")
        )

    staging = data_root / "corpora" / f".staging-{uuid.uuid4()}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        with _timed(timing_callback, "srcdiff_corpus_promotion_seconds"):
            promoted_cases = []
            records_by_id = {record["case_id"]: record for record in case_records}
            for case in input_snapshot_manifest["cases"]:
                record = records_by_id[case["case_id"]]
                promoted = dict(record)
                if record["generation_status"] == "accepted":
                    source_xml = (
                        data_root
                        / record["attempt_path"]
                        / "partial.srcdiff.xml"
                    )
                    case_dir = staging / "cases" / case["case_id"]
                    case_dir.mkdir(parents=True)
                    destination_xml = case_dir / "input.srcdiff.xml"
                    try:
                        os.link(source_xml, destination_xml)
                    except OSError:
                        shutil.copy2(source_xml, destination_xml)
                    promoted["input_path"] = (
                        Path("cases") / case["case_id"] / "input.srcdiff.xml"
                    ).as_posix()
                    write_json_atomic(case_dir / "case.json", promoted)
                promoted_cases.append(promoted)
            manifest = {
                "schema_version": CORPUS_SCHEMA_VERSION,
                "corpus_id": corpus_id,
                "created_at": utc_now(),
                "input_snapshot_id": input_snapshot_manifest["input_snapshot_id"],
                "adapter": input_snapshot_manifest["adapter"],
                "source": input_snapshot_manifest["source"],
                "filter_configuration": input_snapshot_manifest[
                    "filter_configuration"
                ],
                "input_snapshot_identity_sha256": identity_payload[
                    "input_snapshot_identity_sha256"
                ],
                "observed_input_snapshot_manifest_sha256": snapshot.manifest_sha256,
                "srcdiff": resolved_srcdiff_observation,
                "generation_configuration": generation_configuration,
                "generation_id": batch_id,
                "counts": {
                    "selected": len(promoted_cases),
                    "accepted": sum(
                        case["generation_status"] == "accepted"
                        for case in promoted_cases
                    ),
                    "failed": sum(
                        case["generation_status"] == "failed"
                        for case in promoted_cases
                    ),
                    **(
                        {
                            "semantic_eligible": sum(
                                case["semantic_status"]
                                == SemanticStatus.ELIGIBLE.value
                                for case in promoted_cases
                            ),
                            "semantic_ineligible": sum(
                                case["semantic_status"]
                                == SemanticStatus.INELIGIBLE.value
                                for case in promoted_cases
                            ),
                        }
                        if semantic_validator is not None
                        else {}
                    ),
                },
                "cases": promoted_cases,
            }
            write_json_atomic(staging / "manifest.json", manifest)
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, final_dir)
        with _timed(timing_callback, "srcdiff_attempt_compaction_seconds"):
            _compact_promoted_srcdiff_outputs(data_root, final_dir, manifest)
        return _verified_corpus(final_dir, manifest)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def _compact_promoted_srcdiff_outputs(
    data_root: Path, corpus_dir: Path, manifest: Mapping[str, Any]
) -> None:
    """Make the verified corpus copy the sole owner of successful srcDiff XML."""

    for case in manifest["cases"]:
        if case["generation_status"] != "accepted":
            continue
        attempt_dir = data_root / case["attempt_path"]
        canonical_path = (corpus_dir / case["input_path"]).relative_to(data_root)
        set_attempt_output_retention(
            attempt_dir,
            "promoted_to_corpus",
            canonical_path=canonical_path.as_posix(),
            discard=True,
        )


def run_corpus(
    *,
    data_root: Path,
    corpus: VerifiedCorpus | str | Path,
    srcmove: Path,
    timeout_seconds: float,
    mode: RunMode = RunMode.DEVELOPMENT,
    resume_run: str | Path | None = None,
    retry_failed: bool = False,
    selected_case_ids: Sequence[str] = (),
    require_semantic_eligible: bool = False,
    activity_callback: Callable[[str, str], None] | None = None,
    timing_callback: TimingCallback | None = None,
    srcmove_observation: Mapping[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    if isinstance(corpus, VerifiedCorpus):
        verified_corpus = corpus
        if timing_callback is not None:
            timing_callback("srcmove_corpus_verification_seconds", 0.0)
    else:
        with _timed(timing_callback, "srcmove_corpus_verification_seconds"):
            verified_corpus = load_corpus(data_root, corpus)
    corpus_dir = verified_corpus.directory
    corpus_manifest = verified_corpus.manifest
    if require_semantic_eligible:
        unclassified = [
            case["case_id"]
            for case in corpus_manifest["cases"]
            if case["generation_status"] == "accepted"
            and case.get("semantic_status")
            not in {
                SemanticStatus.ELIGIBLE.value,
                SemanticStatus.INELIGIBLE.value,
            }
        ]
        if unclassified:
            raise ValueError(
                "semantic eligibility was not recorded for accepted corpus case(s): "
                + ", ".join(unclassified)
            )
    if resume_run is None:
        run_id = f"run-{utc_now().replace(':', '').replace('+', '-')}-{uuid.uuid4()}"
        final_dir = data_root / "runs" / run_id
        final_dir.mkdir(parents=True, exist_ok=False)
        created_at = utc_now()
        case_records: list[dict[str, Any]] = []
    else:
        supplied = Path(resume_run)
        final_dir = (
            supplied if supplied.is_dir() else data_root / "runs" / str(resume_run)
        )
        run_path = final_dir / "run.json"
        if not run_path.is_file():
            raise FileNotFoundError(f"run manifest not found: {resume_run}")
        prior_run = json.loads(run_path.read_text(encoding="utf-8"))
        if prior_run.get("corpus_id") != corpus_manifest["corpus_id"]:
            raise ValueError("resumed run belongs to a different corpus")
        if prior_run.get("require_semantic_eligible", False) != require_semantic_eligible:
            raise ValueError("resumed run uses a different semantic eligibility policy")
        run_id = prior_run["run_id"]
        created_at = prior_run.get("created_at", utc_now())
        case_records = list(prior_run.get("cases", []))
        with _timed(timing_callback, "srcmove_attempt_recovery_seconds"):
            recover_interrupted_attempts(final_dir / "attempts")
    input_paths = {
        case["case_id"]: corpus_dir / case["input_path"]
        for case in corpus_manifest["cases"]
        if case["generation_status"] == "accepted"
        and (
            not require_semantic_eligible
            or case["semantic_status"] == SemanticStatus.ELIGIBLE.value
        )
    }
    input_checksums = {
        case["case_id"]: case["xml"]["sha256"]
        for case in corpus_manifest["cases"]
        if case["case_id"] in input_paths
    }
    input_observations = {
        case_id: {
            "path": str(path.resolve()),
            "status": "observed",
            "size_bytes": next(
                case["xml"]["size_bytes"]
                for case in corpus_manifest["cases"]
                if case["case_id"] == case_id
            ),
            "sha256": input_checksums[case_id],
        }
        for case_id, path in input_paths.items()
    }
    with _timed(timing_callback, "srcmove_observation_seconds"):
        observation = collect_run_observation(
            mode=mode,
            repositories={},
            executables={"srcMove": srcmove},
            inputs=input_paths,
            executable_observations=(
                {"srcMove": srcmove_observation}
                if srcmove_observation is not None
                else None
            ),
            input_observations=input_observations,
        )
    records_by_id = {record["case_id"]: record for record in case_records}
    selected = set(selected_case_ids) if selected_case_ids else set(input_paths)
    unknown = selected - set(input_paths)
    if unknown:
        raise ValueError(
            f"unknown accepted corpus case(s): {', '.join(sorted(unknown))}"
        )

    with _timed(timing_callback, "srcmove_attempt_reconciliation_seconds"):
        for terminal_path in (final_dir / "attempts").glob("attempt-*/attempt.json"):
            try:
                terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if terminal.get("context", {}).get("run_id") != run_id:
                continue
            case_id = terminal.get("case_id")
            if not isinstance(case_id, str) or case_id not in input_paths:
                continue
            previous = records_by_id.get(case_id)
            ordinal = terminal.get("retry_ordinal", 0)
            if previous is not None and previous.get("retry_ordinal", 0) >= ordinal:
                continue
            results_path = terminal_path.parent / "results.json"
            results = _observe_json(results_path)
            if results["status"] != "missing":
                results["path"] = str(results_path.relative_to(final_dir))
            completed = (
                terminal.get("admitted", False) and results["status"] == "valid"
            )
            records_by_id[case_id] = {
                "case_id": case_id,
                "attempt_id": terminal["attempt_id"],
                "parent_attempt_id": terminal.get("parent_attempt_id"),
                "retry_ordinal": ordinal,
                "status": "completed" if completed else "failed",
                "input_sha256": input_checksums[case_id],
                "xml": terminal.get("xml", {"status": "not_checked"}),
                "results": results,
            }
    try:
        for case_id, input_xml in input_paths.items():
            previous = records_by_id.get(case_id)
            should_retry = (
                previous is not None
                and previous["status"] == "failed"
                and retry_failed
                and case_id in selected
            )
            if previous is not None and not should_retry:
                if activity_callback is not None:
                    activity_callback("reused", case_id)
                continue

            def command(output: Path) -> Sequence[str]:
                return [
                    str(srcmove),
                    str(input_xml),
                    str(output),
                    "--results",
                    str(output.parent / "results.json"),
                ]

            if activity_callback is not None:
                activity_callback("running", case_id)
            with _timed(timing_callback, "srcmove_attempt_wall_seconds"):
                attempt_dir, attempt = execute_attempt(
                    attempts_root=final_dir / "attempts",
                    stage="srcmove",
                    case_id=case_id,
                    command_factory=command,
                    cwd=corpus_dir,
                    timeout_seconds=timeout_seconds,
                    xml_validator=lambda path: validate_srcdiff_xml(
                        path,
                        "archive"
                        if corpus_manifest["generation_configuration"]["archive"]
                        else "single_file",
                    ),
                    output_filename="srcmove.xml",
                    parent_attempt_id=previous["attempt_id"] if should_retry else None,
                    retry_ordinal=(
                        previous.get("retry_ordinal", 0) + 1 if should_retry else 0
                    ),
                    context={
                        "run_id": run_id,
                        "corpus_id": verified_corpus.corpus_id,
                        "input_sha256": input_checksums[case_id],
                    },
                )
            results_path = attempt_dir / "results.json"
            with _timed(timing_callback, "srcmove_results_observation_seconds"):
                results = _observe_json(results_path)
                if results["status"] != "missing":
                    results["path"] = str(results_path.relative_to(final_dir))
                completed = attempt["admitted"] and results["status"] == "valid"
                result_value = (
                    json.loads(results_path.read_text(encoding="utf-8"))
                    if completed
                    else None
                )
            if completed and result_value is not None:
                if result_value.get("move_count") == 0:
                    with _timed(
                        timing_callback, "srcmove_output_retention_seconds"
                    ):
                        attempt = set_attempt_output_retention(
                            attempt_dir,
                            "discarded_zero_move_after_validation",
                            discard=True,
                        )
            if activity_callback is not None:
                activity_callback("completed" if completed else "failed", case_id)
            records_by_id[case_id] = {
                "case_id": case_id,
                "attempt_id": attempt["attempt_id"],
                "parent_attempt_id": attempt["parent_attempt_id"],
                "retry_ordinal": attempt["retry_ordinal"],
                "status": "completed" if completed else "failed",
                "input_sha256": input_checksums[case_id],
                "xml": attempt["xml"],
                "results": results,
            }
            case_records = [
                records_by_id[selected_id]
                for selected_id in input_paths
                if selected_id in records_by_id
            ]
            with _timed(timing_callback, "srcmove_run_checkpoint_seconds"):
                write_json_atomic(
                    final_dir / "run.json",
                    {
                        "schema_version": RUN_SCHEMA_VERSION,
                        "run_id": run_id,
                        "created_at": created_at,
                        "status": "running",
                        "mode": mode.value,
                        "corpus_id": corpus_manifest["corpus_id"],
                        "require_semantic_eligible": require_semantic_eligible,
                        "cases": case_records,
                    },
                )
        case_records = [
            records_by_id[selected_id]
            for selected_id in input_paths
            if selected_id in records_by_id
        ]
        manifest = {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "created_at": created_at,
            "status": "completed",
            "mode": mode.value,
            "corpus_id": corpus_manifest["corpus_id"],
            "require_semantic_eligible": require_semantic_eligible,
            "corpus_manifest_sha256": verified_corpus.manifest_sha256,
            "timeout_seconds": timeout_seconds,
            "observation": observation,
            "counts": {
                "corpus_selected": len(corpus_manifest["cases"]),
                "corpus_accepted": sum(
                    case["generation_status"] == "accepted"
                    for case in corpus_manifest["cases"]
                ),
                "corpus_failed": sum(
                    case["generation_status"] == "failed"
                    for case in corpus_manifest["cases"]
                ),
                **(
                    {
                        "semantic_eligible": len(input_paths),
                        "semantic_ineligible": sum(
                            case["generation_status"] == "accepted"
                            and case["semantic_status"]
                            == SemanticStatus.INELIGIBLE.value
                            for case in corpus_manifest["cases"]
                        ),
                    }
                    if require_semantic_eligible
                    else {}
                ),
                "executed": len(case_records),
                "completed": sum(
                    case["status"] == "completed" for case in case_records
                ),
                "failed": sum(case["status"] == "failed" for case in case_records),
            },
            "cases": case_records,
        }
        with _timed(timing_callback, "srcmove_run_checkpoint_seconds"):
            write_json_atomic(final_dir / "run.json", manifest)
        return final_dir, manifest
    except BaseException:
        write_json_atomic(
            final_dir / "run.json",
            {
                "schema_version": RUN_SCHEMA_VERSION,
                "run_id": run_id,
                "mode": mode.value,
                "corpus_id": corpus_manifest["corpus_id"],
                "require_semantic_eligible": require_semantic_eligible,
                "status": "orchestration_interrupted",
                "completed_at": utc_now(),
                "cases": case_records,
            },
        )
        raise
