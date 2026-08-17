"""Immutable preparation, srcDiff corpus, and srcMove run stages."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from benchmarks.contracts import (
    canonical_json,
    DatasetAdapter,
    PreparedCase,
    RunMode,
    SemanticResult,
    SemanticStatus,
    content_identifier,
)
from benchmarks.process import (
    execute_attempt,
    recover_interrupted_attempts,
    validate_srcdiff_xml,
    write_json_atomic,
)
from benchmarks.provenance import (
    collect_run_observation,
    observe_executable,
    sha256_file,
    utc_now,
)


PREPARATION_SCHEMA_VERSION = 2
CORPUS_SCHEMA_VERSION = 3
RUN_SCHEMA_VERSION = 3


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
    normalized = {
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
        raise ValueError(f"prepared input must not be a symbolic link: {resolved}")
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
        raise ValueError(f"prepared input not found: {resolved}")

    files = []
    excluded = []
    for candidate in sorted(resolved.rglob("*")):
        if candidate.is_symlink():
            raise ValueError(
                f"prepared input tree must not contain symbolic links: {candidate}"
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


def _manifest_checksum(path: Path) -> str:
    return sha256_file(path)


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
        raise FileNotFoundError(f"{kind} manifest not found: {identifier_or_path}")
    return candidate.resolve()


def _load_manifest(path: Path, schema_version: int, id_field: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != schema_version:
        raise ValueError(f"unsupported or malformed manifest: {path}")
    if not isinstance(value.get(id_field), str):
        raise ValueError(f"manifest is missing {id_field}: {path}")
    return value


def _verify_preparation(directory: Path, manifest: Mapping[str, Any]) -> None:
    identity_payload = {
        "schema_version": PREPARATION_SCHEMA_VERSION,
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
    expected_id = content_identifier("preparation", identity_payload)
    expected_identity_checksum = hashlib.sha256(
        canonical_json(identity_payload)
    ).hexdigest()
    if manifest["preparation_id"] != expected_id:
        raise ValueError("preparation identity does not match its manifest")
    if manifest["identity_sha256"] != expected_identity_checksum:
        raise ValueError("preparation identity checksum does not match its manifest")
    for case in manifest["cases"]:
        original = directory / case["original_path"]
        modified = directory / case["modified_path"]
        if _input_identity(original) != {**case["original"], "excluded": []}:
            raise ValueError(
                f"prepared original input checksum mismatch: {case['case_id']}"
            )
        if _input_identity(modified) != {**case["modified"], "excluded": []}:
            raise ValueError(
                f"prepared modified input checksum mismatch: {case['case_id']}"
            )


def _verify_corpus(directory: Path, manifest: Mapping[str, Any]) -> None:
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
            "preparation_identity_sha256": manifest[
                "preparation_identity_sha256"
            ],
            "srcdiff_sha256": artifact.get("sha256"),
            "generation_configuration": manifest["generation_configuration"],
            "accepted_xml": accepted_checksums,
        },
    )
    if manifest["corpus_id"] != expected_id:
        raise ValueError("corpus identity does not match its manifest")
    for case in manifest["cases"]:
        if case["generation_status"] != "accepted":
            continue
        input_path = directory / case["input_path"]
        if not input_path.is_file() or sha256_file(input_path) != case["xml"]["sha256"]:
            raise ValueError(f"corpus input checksum mismatch: {case['case_id']}")


def create_preparation(
    *,
    data_root: Path,
    adapter: DatasetAdapter,
    source: Mapping[str, Any],
    filter_configuration: Mapping[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    cases = list(adapter.prepare())
    if not cases:
        raise ValueError("dataset adapter produced no cases")

    excluded_suffixes = _normalized_excluded_suffixes(filter_configuration)
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
    identity_payload = {
        "schema_version": PREPARATION_SCHEMA_VERSION,
        "adapter": {"name": adapter.name, "version": adapter.version},
        "source": dict(source),
        "filter_configuration": {
            **dict(filter_configuration or {}),
            "excluded_suffixes": list(excluded_suffixes),
        },
        "cases": identities,
    }
    preparation_id = content_identifier("preparation", identity_payload)
    final_dir = data_root / "preparations" / preparation_id
    if final_dir.is_dir():
        manifest = _load_manifest(
            final_dir / "manifest.json", PREPARATION_SCHEMA_VERSION, "preparation_id"
        )
        _verify_preparation(final_dir, manifest)
        return final_dir, manifest

    staging = data_root / "preparations" / f".staging-{uuid.uuid4()}"
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
        manifest = {
            "schema_version": PREPARATION_SCHEMA_VERSION,
            "preparation_id": preparation_id,
            "identity_sha256": hashlib.sha256(
                canonical_json(identity_payload)
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
            "cases": manifest_cases,
        }
        write_json_atomic(staging / "manifest.json", manifest)
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, final_dir)
        return final_dir, manifest
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def generate_corpus(
    *,
    data_root: Path,
    preparation: str | Path,
    srcdiff: Path,
    timeout_seconds: float,
    use_position: bool = False,
    use_archive: bool = True,
    source_encoding: str = "UTF-8",
    retry_failed: bool = False,
    selected_case_ids: Sequence[str] = (),
    semantic_validator: Callable[[PreparedCase, Path], SemanticResult] | None = None,
    semantic_oracle: Mapping[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    preparation_manifest_path = _resolve_manifest(
        data_root, "preparations", preparation
    )
    preparation_manifest = _load_manifest(
        preparation_manifest_path, PREPARATION_SCHEMA_VERSION, "preparation_id"
    )
    preparation_dir = preparation_manifest_path.parent
    _verify_preparation(preparation_dir, preparation_manifest)
    attempts_root = data_root / "attempts"
    attempts_root.mkdir(parents=True, exist_ok=True)
    recover_interrupted_attempts(attempts_root)
    srcdiff_observation = observe_executable(srcdiff)
    generation_configuration = {
        "position": use_position,
        "archive": use_archive,
        "source_encoding": source_encoding,
        "timeout_seconds": timeout_seconds,
        "semantic_oracle": dict(semantic_oracle or {}),
    }
    artifact = srcdiff_observation.get("artifact", {})
    batch_identity = {
        "preparation_identity_sha256": preparation_manifest["identity_sha256"],
        "srcdiff_sha256": artifact.get("sha256"),
        "generation_configuration": generation_configuration,
    }
    batch_id = content_identifier("generation", batch_identity)
    batch_path = data_root / "generation-batches" / batch_id / "batch.json"
    if batch_path.is_file():
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
        if batch.get("identity") != batch_identity:
            raise ValueError(f"generation batch identity mismatch: {batch_path}")
    else:
        batch = {
            "schema_version": 1,
            "generation_id": batch_id,
            "identity": batch_identity,
            "created_at": utc_now(),
            "cases": [],
        }
    records_by_id = {record["case_id"]: record for record in batch["cases"]}
    preparation_cases = {
        case["case_id"]: case for case in preparation_manifest["cases"]
    }

    def validate_semantics(case_id: str, xml_path: Path) -> dict[str, Any]:
        if semantic_validator is None:
            return {
                "semantic_status": SemanticStatus.NOT_APPLICABLE.value,
                "semantic_details": {},
            }
        prepared = preparation_cases[case_id]
        result = semantic_validator(
            PreparedCase(
                case_id=case_id,
                original=preparation_dir / prepared["original_path"],
                modified=preparation_dir / prepared["modified_path"],
                metadata=prepared["metadata"],
            ),
            xml_path,
        )
        return {
            "semantic_status": result.status.value,
            "semantic_details": dict(result.details),
        }
    # An interruption can occur after execute_attempt seals its evidence but before
    # the batch checkpoint is updated. Reconcile those terminal records first.
    for terminal_path in attempts_root.glob("attempt-*/attempt.json"):
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
            validate_semantics(case_id, terminal_path.parent / "partial.srcdiff.xml")
            if terminal.get("admitted")
            else {
                "semantic_status": SemanticStatus.NOT_CHECKED.value,
                "semantic_details": {},
            }
        )
        records_by_id[case_id] = {
            "case_id": case_id,
            "metadata": preparation_cases[case_id]["metadata"],
            "attempt_id": terminal["attempt_id"],
            "parent_attempt_id": terminal.get("parent_attempt_id"),
            "retry_ordinal": ordinal,
            "generation_status": "accepted" if terminal.get("admitted") else "failed",
            "xml": terminal.get("xml", {"status": "not_checked"}),
            **semantic,
            "attempt_path": str(terminal_path.parent.relative_to(data_root)),
        }
    known_ids = {case["case_id"] for case in preparation_manifest["cases"]}
    selected = set(selected_case_ids) if selected_case_ids else known_ids
    unknown = selected - known_ids
    if unknown:
        raise ValueError(f"unknown preparation case(s): {', '.join(sorted(unknown))}")

    for case in preparation_manifest["cases"]:
        case_id = case["case_id"]
        previous = records_by_id.get(case_id)
        should_retry = (
            previous is not None
            and previous["generation_status"] == "failed"
            and retry_failed
            and case_id in selected
        )
        if previous is not None and not should_retry:
            continue
        original = preparation_dir / case["original_path"]
        modified = preparation_dir / case["modified_path"]

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

        attempt_dir, attempt = execute_attempt(
            attempts_root=attempts_root,
            stage="srcdiff",
            case_id=case_id,
            command_factory=command,
            cwd=preparation_dir,
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
                "preparation_id": preparation_manifest["preparation_id"],
                "preparation_manifest_sha256": _manifest_checksum(
                    preparation_manifest_path
                ),
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
        batch["cases"] = [
            records_by_id[item["case_id"]]
            for item in preparation_manifest["cases"]
            if item["case_id"] in records_by_id
        ]
        batch["updated_at"] = utc_now()
        write_json_atomic(batch_path, batch)

    case_records = [
        records_by_id[case["case_id"]] for case in preparation_manifest["cases"]
    ]
    accepted_checksums = [
        {"case_id": record["case_id"], "sha256": record["xml"]["sha256"]}
        for record in case_records
        if record["generation_status"] == "accepted"
    ]
    identity_payload = {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "preparation_identity_sha256": preparation_manifest["identity_sha256"],
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
        _verify_corpus(final_dir, manifest)
        return final_dir, manifest

    staging = data_root / "corpora" / f".staging-{uuid.uuid4()}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        promoted_cases = []
        records_by_id = {record["case_id"]: record for record in case_records}
        for case in preparation_manifest["cases"]:
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
                shutil.copy2(source_xml, case_dir / "input.srcdiff.xml")
                promoted["input_path"] = (
                    Path("cases") / case["case_id"] / "input.srcdiff.xml"
                ).as_posix()
                write_json_atomic(case_dir / "case.json", promoted)
            promoted_cases.append(promoted)
        manifest = {
            "schema_version": CORPUS_SCHEMA_VERSION,
            "corpus_id": corpus_id,
            "created_at": utc_now(),
            "preparation_id": preparation_manifest["preparation_id"],
            "adapter": preparation_manifest["adapter"],
            "source": preparation_manifest["source"],
            "filter_configuration": preparation_manifest["filter_configuration"],
            "preparation_identity_sha256": identity_payload[
                "preparation_identity_sha256"
            ],
            "observed_preparation_manifest_sha256": _manifest_checksum(
                preparation_manifest_path
            ),
            "srcdiff": srcdiff_observation,
            "generation_configuration": generation_configuration,
            "generation_id": batch_id,
            "counts": {
                "selected": len(promoted_cases),
                "accepted": sum(
                    case["generation_status"] == "accepted"
                    for case in promoted_cases
                ),
                "failed": sum(
                    case["generation_status"] == "failed" for case in promoted_cases
                ),
                **(
                    {
                        "semantic_eligible": sum(
                            case["semantic_status"] == SemanticStatus.ELIGIBLE.value
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
        return final_dir, manifest
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def run_corpus(
    *,
    data_root: Path,
    corpus: str | Path,
    srcmove: Path,
    timeout_seconds: float,
    mode: RunMode = RunMode.DEVELOPMENT,
    resume_run: str | Path | None = None,
    retry_failed: bool = False,
    selected_case_ids: Sequence[str] = (),
    require_semantic_eligible: bool = False,
) -> tuple[Path, dict[str, Any]]:
    corpus_manifest_path = _resolve_manifest(data_root, "corpora", corpus)
    corpus_manifest = _load_manifest(
        corpus_manifest_path, CORPUS_SCHEMA_VERSION, "corpus_id"
    )
    corpus_dir = corpus_manifest_path.parent
    _verify_corpus(corpus_dir, corpus_manifest)
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
    recover_interrupted_attempts(data_root / "attempts")
    for prior_run_attempts in (data_root / "runs").glob("*/attempts"):
        recover_interrupted_attempts(prior_run_attempts)
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
    input_paths = {
        case["case_id"]: corpus_dir / case["input_path"]
        for case in corpus_manifest["cases"]
        if case["generation_status"] == "accepted"
        and (
            not require_semantic_eligible
            or case["semantic_status"] == SemanticStatus.ELIGIBLE.value
        )
    }
    observation = collect_run_observation(
        mode=mode,
        repositories={},
        executables={"srcMove": srcmove},
        inputs=input_paths,
    )
    records_by_id = {record["case_id"]: record for record in case_records}
    selected = set(selected_case_ids) if selected_case_ids else set(input_paths)
    unknown = selected - set(input_paths)
    if unknown:
        raise ValueError(
            f"unknown accepted corpus case(s): {', '.join(sorted(unknown))}"
        )

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
        completed = terminal.get("admitted", False) and results["status"] == "valid"
        records_by_id[case_id] = {
            "case_id": case_id,
            "attempt_id": terminal["attempt_id"],
            "parent_attempt_id": terminal.get("parent_attempt_id"),
            "retry_ordinal": ordinal,
            "status": "completed" if completed else "failed",
            "input_sha256": sha256_file(input_paths[case_id]),
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
                continue

            def command(output: Path) -> Sequence[str]:
                return [
                    str(srcmove),
                    str(input_xml),
                    str(output),
                    "--results",
                    str(output.parent / "results.json"),
                ]

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
                    "corpus_id": corpus_manifest["corpus_id"],
                    "input_sha256": sha256_file(input_xml),
                },
            )
            results_path = attempt_dir / "results.json"
            results = _observe_json(results_path)
            if results["status"] != "missing":
                results["path"] = str(results_path.relative_to(final_dir))
            completed = attempt["admitted"] and results["status"] == "valid"
            records_by_id[case_id] = {
                "case_id": case_id,
                "attempt_id": attempt["attempt_id"],
                "parent_attempt_id": attempt["parent_attempt_id"],
                "retry_ordinal": attempt["retry_ordinal"],
                "status": "completed" if completed else "failed",
                "input_sha256": sha256_file(input_xml),
                "xml": attempt["xml"],
                "results": results,
            }
            case_records = [
                records_by_id[selected_id]
                for selected_id in input_paths
                if selected_id in records_by_id
            ]
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
            "corpus_manifest_sha256": _manifest_checksum(corpus_manifest_path),
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
