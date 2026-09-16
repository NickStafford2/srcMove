"""Content-addressed stable Java wrapper objects for normalized census plans."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from benchmarking.identity import content_identifier
from bigMoveBench.synthetic import (
    STABLE_ROLES,
    STABLE_WRAPPER_VERSION,
    build_stable_archive_unit,
    indent_fragment,
)


GENERATED_OBJECT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class GeneratedObject:
    object_id: str
    wrapper_version: int
    role: str
    fragment_sha256: str | None
    path: Path
    size_bytes: int
    sha256: str
    payload_range: tuple[int, int] | None


class GeneratedObjectStore:
    """Publish and verify reusable wrappers without creating case directories."""

    def __init__(self, data_root: Path) -> None:
        self.directory = data_root.expanduser().resolve() / "generated-objects"

    @staticmethod
    def _render(
        role: str, fragment: str | None
    ) -> tuple[bytes, str | None, tuple[int, int] | None]:
        if role not in STABLE_ROLES:
            raise ValueError(f"unsupported generated-object role: {role}")
        if fragment == "":
            raise ValueError("generated-object fragment must be nonempty or None")
        fragment_sha256 = (
            hashlib.sha256(fragment.encode("utf-8")).hexdigest()
            if fragment is not None
            else None
        )
        generated_fragment = indent_fragment(fragment) if fragment is not None else None
        source, payload_range = build_stable_archive_unit(role, generated_fragment)
        return source.encode("utf-8"), fragment_sha256, payload_range

    @staticmethod
    def _verify_existing(path: Path, expected: bytes) -> None:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"generated object is unavailable: {path}")
        observed = path.read_bytes()
        if observed != expected:
            raise ValueError(f"generated object content mismatch: {path}")

    def publish(self, role: str, fragment: str | None) -> GeneratedObject:
        """Publish one stable wrapper and return its complete identity."""

        contents, fragment_sha256, payload_range = self._render(role, fragment)
        identity = {
            "schema_version": GENERATED_OBJECT_SCHEMA_VERSION,
            "wrapper_version": STABLE_WRAPPER_VERSION,
            "role": role,
            "fragment_sha256": fragment_sha256,
        }
        object_id = content_identifier("bmb-generated-object", identity)
        sha256 = hashlib.sha256(contents).hexdigest()
        path = self.directory / f"{object_id}.java"
        self.directory.mkdir(parents=True, exist_ok=True)

        if path.exists() or path.is_symlink():
            self._verify_existing(path, contents)
        else:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{object_id}.", suffix=".tmp", dir=self.directory
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(contents)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    self._verify_existing(path, contents)
            finally:
                temporary.unlink(missing_ok=True)

        return GeneratedObject(
            object_id=object_id,
            wrapper_version=STABLE_WRAPPER_VERSION,
            role=role,
            fragment_sha256=fragment_sha256,
            path=path,
            size_bytes=len(contents),
            sha256=sha256,
            payload_range=payload_range,
        )
