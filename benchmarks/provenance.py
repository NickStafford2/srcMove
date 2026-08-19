"""Read-only provenance collection and build-receipt validation."""

from __future__ import annotations

import hashlib
import json
import locale
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from benchmarks.contracts import (
    CONTRACT_VERSION,
    ProvenanceStatus,
    RunMode,
    content_identifier,
)


RECEIPT_SCHEMA_VERSION = 1
OBSERVATION_SCHEMA_VERSION = 1
RELEVANT_SOURCE_SUFFIXES = {
    ".c",
    ".cc",
    ".cmake",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".xml",
}
RELEVANT_SOURCE_NAMES = {"CMakeLists.txt", "Makefile"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            hasher.update(block)
    return hasher.hexdigest()


def observe_file(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    observation: dict[str, Any] = {"path": str(resolved)}
    try:
        observation.update(
            {
                "status": "observed",
                "size_bytes": resolved.stat().st_size,
                "sha256": sha256_file(resolved),
            }
        )
    except OSError as error:
        observation.update(
            {"status": "unavailable", "error": f"{type(error).__name__}: {error}"}
        )
    return observation


def _git(repo: Path, arguments: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repo,
        capture_output=True,
        check=False,
    )


def _git_text(repo: Path, arguments: Sequence[str]) -> str | None:
    result = _git(repo, arguments)
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="replace").strip()


def _is_relevant_source(path: Path) -> bool:
    return path.name in RELEVANT_SOURCE_NAMES or path.suffix.lower() in RELEVANT_SOURCE_SUFFIXES


def observe_repository(path: Path) -> dict[str, Any]:
    """Observe a Git checkout without fetching, cleaning, or modifying it."""

    resolved = path.expanduser().resolve()
    observation: dict[str, Any] = {"path": str(resolved)}
    if not resolved.is_dir():
        observation.update({"status": "unavailable", "error": "directory not found"})
        return observation

    repository_root = _git_text(resolved, ["rev-parse", "--show-toplevel"])
    commit = _git_text(resolved, ["rev-parse", "HEAD"])
    if repository_root is None or commit is None:
        observation.update({"status": "unavailable", "error": "not a Git repository"})
        return observation

    tracked_diff = _git(resolved, ["diff", "--binary", "HEAD", "--"])
    if tracked_diff.returncode != 0:
        observation.update(
            {"status": "unavailable", "error": "could not read tracked working-tree diff"}
        )
        return observation

    untracked_result = _git(
        resolved, ["ls-files", "--others", "--exclude-standard", "-z"]
    )
    if untracked_result.returncode != 0:
        observation.update(
            {"status": "unavailable", "error": "could not enumerate untracked files"}
        )
        return observation

    root = Path(repository_root)
    untracked_sources = []
    for raw_path in untracked_result.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative = Path(raw_path.decode("utf-8", errors="surrogateescape"))
        source_path = root / relative
        if _is_relevant_source(relative) and source_path.is_file():
            untracked_sources.append(
                {
                    "path": relative.as_posix(),
                    "size_bytes": source_path.stat().st_size,
                    "sha256": sha256_file(source_path),
                }
            )

    tracked_dirty = bool(tracked_diff.stdout)
    observation.update(
        {
            "status": "observed",
            "repository_root": str(root),
            "origin": _git_text(resolved, ["remote", "get-url", "origin"]),
            "commit": commit,
            "branch": _git_text(resolved, ["branch", "--show-current"]) or None,
            "tracked_dirty": tracked_dirty,
            "tracked_diff_sha256": (
                sha256_bytes(tracked_diff.stdout) if tracked_dirty else None
            ),
            "untracked_sources": sorted(
                untracked_sources, key=lambda entry: entry["path"]
            ),
        }
    )
    return observation


def source_state_core(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Return the path-independent repository fields used for comparisons."""

    return {
        key: observation.get(key)
        for key in (
            "status",
            "origin",
            "commit",
            "tracked_dirty",
            "tracked_diff_sha256",
            "untracked_sources",
        )
    }


def observe_environment() -> dict[str, Any]:
    language, encoding = locale.getlocale()
    environment = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "locale": {"language": language, "encoding": encoding},
        "timezone": os.environ.get("TZ"),
        "container": Path("/.dockerenv").exists(),
    }
    return {
        "environment_id": content_identifier("environment", environment),
        **environment,
    }


def build_receipt_identifier(
    *,
    sources: Mapping[str, Mapping[str, Any]],
    source_lock: Mapping[str, Any] | None,
    build: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
) -> str:
    identity_payload = {
        "contract_version": CONTRACT_VERSION,
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "sources": {
            name: source_state_core(observation)
            for name, observation in sources.items()
        },
        "source_lock": source_lock,
        "build": {
            "configuration": build.get("configuration"),
            "cmake_options": build.get("cmake_options"),
            "compiler": build.get("compiler"),
        },
        "artifacts": list(artifacts),
    }
    return content_identifier("build-receipt", identity_payload)


def _load_receipt(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "missing"
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "malformed"

    if not isinstance(value, dict):
        return None, "malformed"
    if value.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        return None, "malformed"
    if not isinstance(value.get("receipt_id"), str):
        return None, "malformed"
    sources = value.get("sources")
    source_lock = value.get("source_lock")
    build = value.get("build")
    tests = value.get("tests")
    if not isinstance(sources, dict):
        return None, "malformed"
    if source_lock is not None and not isinstance(source_lock, dict):
        return None, "malformed"
    if not isinstance(build, dict):
        return None, "malformed"
    if not isinstance(build.get("configuration"), str):
        return None, "malformed"
    if not isinstance(build.get("cmake_options"), dict):
        return None, "malformed"
    compiler = build.get("compiler")
    if not isinstance(compiler, dict):
        return None, "malformed"
    if not isinstance(compiler.get("id"), str) or not isinstance(
        compiler.get("version"), str
    ):
        return None, "malformed"
    if not isinstance(tests, dict) or tests.get("status") not in {
        "passed",
        "failed",
        "not_run",
    }:
        return None, "malformed"
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return None, "malformed"
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            return None, "malformed"
        if not isinstance(artifact.get("name"), str):
            return None, "malformed"
        checksum = artifact.get("sha256")
        if not isinstance(checksum, str) or len(checksum) != 64:
            return None, "malformed"
    expected_identifier = build_receipt_identifier(
        sources=sources,
        source_lock=source_lock,
        build=build,
        artifacts=artifacts,
    )
    if value["receipt_id"] != expected_identifier:
        return None, "malformed"
    return value, "valid"


def observe_executable(
    executable: Path, receipt_path: Path | None = None
) -> dict[str, Any]:
    artifact = observe_file(executable)
    observation: dict[str, Any] = {"artifact": artifact}
    if artifact["status"] != "observed":
        observation.update(
            {
                "provenance_status": ProvenanceStatus.UNAVAILABLE.value,
                "receipt_validation": "not_checked",
            }
        )
        return observation

    candidate = receipt_path or Path(f"{artifact['path']}.build-receipt.json")
    receipt, validation = _load_receipt(candidate)
    observation["receipt_path"] = str(candidate.expanduser().resolve())
    observation["receipt_validation"] = validation
    if receipt is None:
        observation["provenance_status"] = ProvenanceStatus.UNVERIFIED.value
        return observation

    matching_artifact = next(
        (
            entry
            for entry in receipt["artifacts"]
            if entry["name"] == Path(artifact["path"]).name
        ),
        None,
    )
    if matching_artifact is None:
        observation["provenance_status"] = ProvenanceStatus.STALE.value
    elif matching_artifact["sha256"] == artifact["sha256"]:
        observation["provenance_status"] = ProvenanceStatus.VERIFIED.value
    else:
        observation["provenance_status"] = ProvenanceStatus.STALE.value
    observation["receipt"] = receipt
    return observation


def compare_receipt_sources(
    executable_observation: Mapping[str, Any],
    repositories: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    """Compare current repositories with receipt sources independently of the binary."""

    receipt = executable_observation.get("receipt")
    if not isinstance(receipt, dict) or not isinstance(receipt.get("sources"), dict):
        return {name: "unavailable" for name in repositories}

    receipt_sources = receipt["sources"]
    relationships = {}
    for name, current in repositories.items():
        recorded = receipt_sources.get(name)
        if not isinstance(recorded, dict):
            relationships[name] = "unavailable"
        elif source_state_core(current) == source_state_core(recorded):
            relationships[name] = "matches"
        else:
            relationships[name] = "differs"
    return relationships


def collect_run_observation(
    *,
    mode: RunMode,
    repositories: Mapping[str, Path],
    executables: Mapping[str, Path],
    inputs: Mapping[str, Path],
    executable_observations: Mapping[str, Mapping[str, Any]] | None = None,
    input_observations: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Collect the immutable observation snapshot for one future run."""

    repository_observations = {
        name: observe_repository(path) for name, path in repositories.items()
    }
    supplied_executables = executable_observations or {}
    executable_observations = {
        name: dict(supplied_executables[name])
        if name in supplied_executables
        else observe_executable(path)
        for name, path in executables.items()
    }
    for observation in executable_observations.values():
        observation["current_source_relationships"] = compare_receipt_sources(
            observation, repository_observations
        )

    return {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "observed_at": utc_now(),
        "mode": mode.value,
        "environment": observe_environment(),
        "repositories": repository_observations,
        "executables": executable_observations,
        "inputs": {
            name: dict(input_observations[name])
            if input_observations is not None and name in input_observations
            else observe_file(path)
            for name, path in inputs.items()
        },
    }
