"""Admission of exact executable bytes into an analysis-owned tool store."""

from __future__ import annotations

import hashlib
import os
import stat
import uuid
from pathlib import Path

from .inputs import ExecutableObservation, observe_executable


def admit_executable(
    source: Path, analysis_root: Path, *, role: str
) -> ExecutableObservation:
    """Copy, hash, and bind future execution to one analysis-owned file."""

    if role not in {"srcdiff", "srcmove"}:
        raise ValueError(f"unknown analysis executable role: {role!r}")
    requested = source.expanduser().absolute()
    resolved = requested.resolve(strict=True)
    tools_root = analysis_root.resolve() / "tools"
    tools_root.mkdir(exist_ok=True)
    if tools_root.is_symlink() or not tools_root.is_dir():
        raise ValueError(f"analysis tool store is not an owned directory: {tools_root}")
    temporary = tools_root / f".{role}.tmp-{uuid.uuid4().hex}"
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(resolved, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError(f"executable is not a regular file: {resolved}")
            if not os.access(resolved, os.X_OK):
                raise ValueError(f"executable is not executable: {resolved}")
            hasher = hashlib.sha256()
            size = 0
            with temporary.open("xb") as output:
                while block := os.read(descriptor, 1024 * 1024):
                    output.write(block)
                    hasher.update(block)
                    size += len(block)
                output.flush()
                os.fsync(output.fileno())
            temporary.chmod(0o500)
            _fsync_file(temporary)
        finally:
            os.close(descriptor)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    checksum = hasher.hexdigest()
    identity_root = tools_root / checksum
    identity_root.mkdir(exist_ok=True)
    if identity_root.is_symlink() or not identity_root.is_dir():
        temporary.unlink(missing_ok=True)
        raise ValueError(
            f"analysis executable identity is not an owned directory: {identity_root}"
        )
    destination = identity_root / role
    try:
        if destination.exists() or destination.is_symlink():
            observed = observe_executable(destination)
            if (observed.size_bytes, observed.sha256) != (size, checksum):
                raise ValueError(f"analysis-owned {role} executable drift")
        else:
            os.link(temporary, destination)
            _fsync_directory(identity_root)
        return ExecutableObservation(
            requested_path=destination,
            resolved_path=destination,
            size_bytes=size,
            sha256=checksum,
        )
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
