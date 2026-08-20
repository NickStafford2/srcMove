"""Frozen invocation inputs and canonical repository-pair identity."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from .contracts import (
    COMPACT_PAIR_SCHEMA_VERSION,
    PAIR_OUTCOME_SCHEMA_VERSION,
    PairWorkItem,
)
from .process import (
    SRCDIFF_XML_VALIDATOR_SCHEMA_VERSION,
    SRCMOVE_RESULTS_VALIDATOR_SCHEMA_VERSION,
)
ANALYSIS_CONFIGURATION_SCHEMA_VERSION = 1
EXECUTABLE_OBSERVATION_SCHEMA_VERSION = 1
FROZEN_ANALYSIS_MANIFEST_SCHEMA_VERSION = 4
PAIR_FINGERPRINT_SCHEMA_VERSION = 1
FROZEN_ANALYSIS_MANIFEST_NAME = "manifest.json"


def canonical_json_bytes(value: Any) -> bytes:
    """Encode a JSON value with one deterministic, unambiguous representation."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_pretty_json_bytes(value: Any) -> bytes:
    """Encode readable JSON with deterministic formatting and one final newline."""

    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class RepositoryIdentity:
    """Caller-asserted durable identity, independent of mutable checkout state.

    Git has no intrinsic repository UUID.  The future public interface must
    therefore choose and persist a stable source identity rather than deriving
    one from a checkout path or mutable ``remote.origin.url`` configuration.
    """

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value or "\0" in self.value:
            raise ValueError("repository identity must be a non-empty string")

    def record(self) -> dict[str, str]:
        return {"value": self.value}


@dataclass(frozen=True, slots=True)
class AnalysisConfiguration:
    """Versioned configuration whose semantics affect every selected pair."""

    selected_directory: str | None = None
    excluded_suffixes: tuple[str, ...] = ()
    use_archive: bool = True
    use_position: bool = False
    source_encoding: str = "UTF-8"
    srcdiff_timeout_seconds: float = 1800.0
    srcmove_timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        directory = self.selected_directory
        if directory is not None:
            if not isinstance(directory, str) or "\0" in directory:
                raise ValueError("selected directory must be a relative Git path")
            parsed = PurePosixPath(directory)
            if parsed.is_absolute() or ".." in parsed.parts:
                raise ValueError("selected directory must be a relative Git path")
            directory = None if str(parsed) == "." else str(parsed)
        object.__setattr__(self, "selected_directory", directory)

        suffixes: set[str] = set()
        for suffix in self.excluded_suffixes:
            if (
                not isinstance(suffix, str)
                or not suffix.startswith(".")
                or "/" in suffix
                or "\0" in suffix
            ):
                raise ValueError("excluded suffixes must be dot-prefixed file suffixes")
            suffixes.add(suffix.lower())
        object.__setattr__(self, "excluded_suffixes", tuple(sorted(suffixes)))

        if not isinstance(self.use_archive, bool) or not isinstance(
            self.use_position, bool
        ):
            raise ValueError("archive and position options must be booleans")
        if not isinstance(self.source_encoding, str) or not self.source_encoding:
            raise ValueError("source encoding must be non-empty")
        for name in ("srcdiff_timeout_seconds", "srcmove_timeout_seconds"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError("tool timeouts must be finite and positive")
            object.__setattr__(self, name, float(value))

    def record(self) -> dict[str, Any]:
        return {
            "schema_version": ANALYSIS_CONFIGURATION_SCHEMA_VERSION,
            "selected_directory": self.selected_directory,
            "excluded_suffixes": list(self.excluded_suffixes),
            "use_archive": self.use_archive,
            "use_position": self.use_position,
            "source_encoding": self.source_encoding,
            "srcdiff_timeout_seconds": self.srcdiff_timeout_seconds,
            "srcmove_timeout_seconds": self.srcmove_timeout_seconds,
        }


@dataclass(frozen=True, slots=True)
class ExecutableObservation:
    """One immutable content observation of a resolved tool executable."""

    requested_path: Path
    resolved_path: Path
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise ValueError("executable size must be non-negative")
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise ValueError("executable SHA-256 must be 64 lowercase hex digits")
        if not self.resolved_path.is_absolute():
            raise ValueError("resolved executable path must be absolute")

    def record(self) -> dict[str, Any]:
        return {
            "schema_version": EXECUTABLE_OBSERVATION_SCHEMA_VERSION,
            "requested_path": str(self.requested_path),
            "resolved_path": str(self.resolved_path),
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


def observe_executable(path: Path) -> ExecutableObservation:
    """Resolve, validate, and hash an executable exactly once."""

    requested = path.expanduser().absolute()
    try:
        resolved = requested.resolve(strict=True)
        with resolved.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError(f"executable is not a regular file: {resolved}")
            if not os.access(resolved, os.X_OK):
                raise ValueError(f"file is not executable: {resolved}")
            hasher = hashlib.sha256()
            size = 0
            while block := stream.read(1024 * 1024):
                hasher.update(block)
                size += len(block)
            after = os.fstat(stream.fileno())
    except FileNotFoundError as error:
        raise ValueError(f"executable does not exist: {requested}") from error
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ) or size != after.st_size:
        raise RuntimeError(f"executable changed while being observed: {resolved}")
    return ExecutableObservation(
        requested_path=requested,
        resolved_path=resolved,
        size_bytes=size,
        sha256=hasher.hexdigest(),
    )


@dataclass(frozen=True, slots=True)
class FingerprintSchemaVersions:
    """Behavioral contract versions covered by pair identity."""

    pair_outcome: int = PAIR_OUTCOME_SCHEMA_VERSION
    srcdiff_xml_validator: int = SRCDIFF_XML_VALIDATOR_SCHEMA_VERSION
    srcmove_results_validator: int = SRCMOVE_RESULTS_VALIDATOR_SCHEMA_VERSION
    compact_pair: int = COMPACT_PAIR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in (
                self.pair_outcome,
                self.srcdiff_xml_validator,
                self.srcmove_results_validator,
                self.compact_pair,
            )
        ):
            raise ValueError("fingerprint schema versions must be positive integers")

    def record(self) -> dict[str, int]:
        return {
            "pair_outcome": self.pair_outcome,
            "srcdiff_xml_validator": self.srcdiff_xml_validator,
            "srcmove_results_validator": self.srcmove_results_validator,
            "compact_pair": self.compact_pair,
        }


@dataclass(frozen=True, slots=True)
class FrozenAnalysisManifest:
    """Durable history and invocation inputs, frozen before workers start."""

    repository: Path
    repository_identity: RepositoryIdentity
    commits: tuple[str, ...]
    configuration: AnalysisConfiguration
    srcdiff: ExecutableObservation
    srcmove: ExecutableObservation
    schema_versions: FingerprintSchemaVersions = FingerprintSchemaVersions()

    def __post_init__(self) -> None:
        if not isinstance(self.repository, Path) or not self.repository.is_absolute():
            raise ValueError("frozen repository path must be absolute")
        object.__setattr__(self, "commits", tuple(self.commits))
        if len(self.commits) < 2:
            raise ValueError("frozen history must contain at least two commits")
        if any(
            not isinstance(commit, str) or not commit or "\0" in commit
            for commit in self.commits
        ):
            raise ValueError("frozen commits must be non-empty native Git object IDs")
        if len(set(self.commits)) != len(self.commits):
            raise ValueError("frozen first-parent history contains duplicate commits")

    def record(self) -> dict[str, Any]:
        return {
            "schema_version": FROZEN_ANALYSIS_MANIFEST_SCHEMA_VERSION,
            "repository_identity": self.repository_identity.record(),
            "repository_path": str(self.repository),
            "commits": list(self.commits),
            "configuration": self.configuration.record(),
            "executables": {
                "srcdiff": self.srcdiff.record(),
                "srcmove": self.srcmove.record(),
            },
            "fingerprint_schema_versions": self.schema_versions.record(),
        }

    def canonical_bytes(self) -> bytes:
        """Return the deterministic human-readable manifest representation."""

        return canonical_pretty_json_bytes(self.record())


def persist_frozen_manifest(
    analysis_root: Path, manifest: FrozenAnalysisManifest
) -> Path:
    """Atomically create the canonical manifest without replacing prior state."""

    requested_root = analysis_root.expanduser().absolute()
    if requested_root.is_symlink():
        raise ValueError(f"analysis root must not be a symbolic link: {requested_root}")
    root = requested_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"analysis root is not an owned directory: {root}")
    destination = root / FROZEN_ANALYSIS_MANIFEST_NAME
    temporary = root / f".{destination.name}.tmp-{uuid.uuid4().hex}"
    try:
        with temporary.open("xb") as stream:
            stream.write(manifest.canonical_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
        _fsync_directory(root)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def load_frozen_manifest(analysis_root: Path) -> FrozenAnalysisManifest:
    """Strictly load one persisted manifest and reject schema ambiguity."""

    requested_root = analysis_root.expanduser().absolute()
    if requested_root.is_symlink():
        raise ValueError(f"analysis root must not be a symbolic link: {requested_root}")
    path = requested_root.resolve() / FROZEN_ANALYSIS_MANIFEST_NAME
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"frozen analysis manifest is not a regular file: {path}")
    try:
        content = path.read_bytes()
    except OSError as error:
        raise ValueError(f"frozen analysis manifest is unreadable: {path}") from error
    return load_frozen_manifest_bytes(content, context=str(path))


def load_frozen_manifest_bytes(
    content: bytes, *, context: str = "manifest"
) -> FrozenAnalysisManifest:
    """Strictly load canonical manifest bytes from an authoritative store."""

    try:
        raw = content.decode("utf-8")
        value = json.loads(raw, object_pairs_hook=_strict_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"frozen analysis manifest is unreadable: {context}") from error
    record = _object(value, "manifest")
    _fields(
        record,
        {
            "schema_version",
            "repository_identity",
            "repository_path",
            "commits",
            "configuration",
            "executables",
            "fingerprint_schema_versions",
        },
        "manifest",
    )
    _schema(record, "schema_version", FROZEN_ANALYSIS_MANIFEST_SCHEMA_VERSION)
    identity_record = _object(record["repository_identity"], "repository_identity")
    _fields(identity_record, {"value"}, "repository_identity")
    identity = RepositoryIdentity(_string(identity_record, "value"))

    repository_value = _string(record, "repository_path")
    repository = Path(repository_value)
    if not repository.is_absolute():
        raise ValueError("manifest repository_path must be absolute")

    commits_value = record["commits"]
    if not isinstance(commits_value, list):
        raise ValueError("manifest commits must be an array")
    commits = tuple(
        _plain_string(commit, f"commits[{index}]")
        for index, commit in enumerate(commits_value)
    )
    configuration = _load_configuration(record["configuration"])
    executables = _object(record["executables"], "executables")
    _fields(executables, {"srcdiff", "srcmove"}, "executables")
    schema_versions = _load_fingerprint_schema_versions(
        record["fingerprint_schema_versions"]
    )
    manifest = FrozenAnalysisManifest(
        repository=repository,
        repository_identity=identity,
        commits=commits,
        configuration=configuration,
        srcdiff=_load_executable(executables["srcdiff"], "executables.srcdiff"),
        srcmove=_load_executable(executables["srcmove"], "executables.srcmove"),
        schema_versions=schema_versions,
    )
    if content != manifest.canonical_bytes():
        raise ValueError("frozen analysis manifest is not canonically encoded")
    return manifest


def verify_resume_inputs(
    manifest: FrozenAnalysisManifest,
    *,
    repository_identity: RepositoryIdentity,
    configuration: AnalysisConfiguration,
    srcdiff: ExecutableObservation,
    srcmove: ExecutableObservation,
) -> FrozenAnalysisManifest:
    """Verify caller inputs and bind work items to freshly observed tools."""

    if repository_identity != manifest.repository_identity:
        raise ValueError("repository identity drift from frozen manifest")
    if configuration != manifest.configuration:
        raise ValueError("analysis configuration drift from frozen manifest")
    for name, current, frozen in (
        ("srcDiff", srcdiff, manifest.srcdiff),
        ("srcMove", srcmove, manifest.srcmove),
    ):
        if (current.size_bytes, current.sha256) != (
            frozen.size_bytes,
            frozen.sha256,
        ):
            raise ValueError(f"{name} executable drift from frozen manifest")
    return FrozenAnalysisManifest(
        repository=manifest.repository,
        repository_identity=manifest.repository_identity,
        commits=manifest.commits,
        configuration=manifest.configuration,
        srcdiff=srcdiff,
        srcmove=srcmove,
        schema_versions=manifest.schema_versions,
    )


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    return value


def _fields(record: Mapping[str, Any], expected: set[str], context: str) -> None:
    actual = set(record)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(
            f"{context} fields do not match schema; missing={missing}, unknown={unknown}"
        )


def _schema(record: Mapping[str, Any], name: str, expected: int) -> None:
    value = record[name]
    if isinstance(value, bool) or not isinstance(value, int) or value != expected:
        raise ValueError(f"unsupported {name}: {value!r}")


def _plain_string(value: Any, context: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a string")
    return value


def _string(record: Mapping[str, Any], name: str) -> str:
    return _plain_string(record[name], name)


def _boolean(record: Mapping[str, Any], name: str) -> bool:
    value = record[name]
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _number(record: Mapping[str, Any], name: str) -> float:
    value = record[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    return float(value)


def _integer(record: Mapping[str, Any], name: str) -> int:
    value = record[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _load_configuration(value: Any) -> AnalysisConfiguration:
    record = _object(value, "configuration")
    names = {
        "schema_version",
        "selected_directory",
        "excluded_suffixes",
        "use_archive",
        "use_position",
        "source_encoding",
        "srcdiff_timeout_seconds",
        "srcmove_timeout_seconds",
    }
    _fields(record, names, "configuration")
    _schema(record, "schema_version", ANALYSIS_CONFIGURATION_SCHEMA_VERSION)
    directory = record["selected_directory"]
    if directory is not None and not isinstance(directory, str):
        raise ValueError("selected_directory must be a string or null")
    suffixes = record["excluded_suffixes"]
    if not isinstance(suffixes, list):
        raise ValueError("excluded_suffixes must be an array")
    parsed_suffixes = tuple(
        _plain_string(suffix, f"excluded_suffixes[{index}]")
        for index, suffix in enumerate(suffixes)
    )
    configuration = AnalysisConfiguration(
        selected_directory=directory,
        excluded_suffixes=parsed_suffixes,
        use_archive=_boolean(record, "use_archive"),
        use_position=_boolean(record, "use_position"),
        source_encoding=_string(record, "source_encoding"),
        srcdiff_timeout_seconds=_number(record, "srcdiff_timeout_seconds"),
        srcmove_timeout_seconds=_number(record, "srcmove_timeout_seconds"),
    )
    if configuration.record() != record:
        raise ValueError("configuration is not in canonical frozen form")
    return configuration


def _load_executable(value: Any, context: str) -> ExecutableObservation:
    record = _object(value, context)
    _fields(
        record,
        {
            "schema_version",
            "requested_path",
            "resolved_path",
            "size_bytes",
            "sha256",
        },
        context,
    )
    _schema(record, "schema_version", EXECUTABLE_OBSERVATION_SCHEMA_VERSION)
    requested = Path(_string(record, "requested_path"))
    resolved = Path(_string(record, "resolved_path"))
    if not requested.is_absolute():
        raise ValueError(f"{context}.requested_path must be absolute")
    observation = ExecutableObservation(
        requested_path=requested,
        resolved_path=resolved,
        size_bytes=_integer(record, "size_bytes"),
        sha256=_string(record, "sha256"),
    )
    if observation.record() != record:
        raise ValueError(f"{context} is not in canonical frozen form")
    return observation


def _load_fingerprint_schema_versions(value: Any) -> FingerprintSchemaVersions:
    record = _object(value, "fingerprint_schema_versions")
    expected = FingerprintSchemaVersions().record()
    _fields(record, set(expected), "fingerprint_schema_versions")
    for name, version in expected.items():
        _schema(record, name, version)
    return FingerprintSchemaVersions(**record)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def freeze_analysis_inputs(
    *,
    repository: Path,
    repository_identity: RepositoryIdentity,
    commits: Iterable[str],
    configuration: AnalysisConfiguration,
    srcdiff: ExecutableObservation,
    srcmove: ExecutableObservation,
) -> FrozenAnalysisManifest:
    """Freeze an already-resolved first-parent sequence without querying Git."""

    resolved_repository = repository.expanduser().resolve(strict=True)
    if not resolved_repository.is_dir():
        raise ValueError(f"repository is not a directory: {resolved_repository}")
    return FrozenAnalysisManifest(
        repository=resolved_repository,
        repository_identity=repository_identity,
        commits=tuple(commits),
        configuration=configuration,
        srcdiff=srcdiff,
        srcmove=srcmove,
    )


def _pair_fingerprint_record(
    manifest: FrozenAnalysisManifest, old_commit: str, new_commit: str
) -> dict[str, Any]:
    return {
        "schema_version": PAIR_FINGERPRINT_SCHEMA_VERSION,
        "repository_identity": manifest.repository_identity.record(),
        "old_commit": old_commit,
        "new_commit": new_commit,
        "configuration": manifest.configuration.record(),
        "executable_sha256": {
            "srcdiff": manifest.srcdiff.sha256,
            "srcmove": manifest.srcmove.sha256,
        },
        "contract_schema_versions": manifest.schema_versions.record(),
    }


def pair_fingerprint_bytes(
    manifest: FrozenAnalysisManifest, old_commit: str, new_commit: str
) -> bytes:
    """Return the exact versioned canonical bytes hashed for one pair."""

    return canonical_json_bytes(
        _pair_fingerprint_record(manifest, old_commit, new_commit)
    )


def pair_fingerprint(
    manifest: FrozenAnalysisManifest, old_commit: str, new_commit: str
) -> str:
    """Hash one canonical pair identity once with analysis-owned SHA-256."""

    return hashlib.sha256(
        pair_fingerprint_bytes(manifest, old_commit, new_commit)
    ).hexdigest()


def build_pair_work_items(
    manifest: FrozenAnalysisManifest,
) -> tuple[PairWorkItem, ...]:
    """Construct contiguous work from the manifest's frozen commit sequence."""

    configuration = manifest.configuration
    return tuple(
        PairWorkItem(
            sequence=sequence,
            old_commit=old_commit,
            new_commit=new_commit,
            fingerprint=pair_fingerprint(manifest, old_commit, new_commit),
            repository=manifest.repository,
            selected_directory=configuration.selected_directory,
            excluded_suffixes=configuration.excluded_suffixes,
            srcdiff=manifest.srcdiff.resolved_path,
            srcmove=manifest.srcmove.resolved_path,
            srcdiff_timeout_seconds=configuration.srcdiff_timeout_seconds,
            srcmove_timeout_seconds=configuration.srcmove_timeout_seconds,
            use_position=configuration.use_position,
            use_archive=configuration.use_archive,
            source_encoding=configuration.source_encoding,
        )
        for sequence, (old_commit, new_commit) in enumerate(
            zip(manifest.commits, manifest.commits[1:])
        )
    )
