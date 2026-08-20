"""Single-writer ownership for one repository-analysis root."""

from __future__ import annotations

import fcntl
import json
import os
import socket
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .inputs import canonical_pretty_json_bytes


LOCK_FILE_NAME = ".operation.lock"
ACTIVITY_FILE_NAME = "activity.json"
ACTIVITY_SCHEMA_VERSION = 1


class AnalysisBusyError(RuntimeError):
    """Another process currently owns the analysis writer lock."""


class AnalysisOperationLock:
    """Hold exclusive writer ownership and publish diagnostic activity state."""

    def __init__(self, analysis_root: Path, *, command: str) -> None:
        if not isinstance(command, str) or not command or "\0" in command:
            raise ValueError("analysis operation command must be a non-empty string")
        requested_root = analysis_root.expanduser().absolute()
        if requested_root.is_symlink():
            raise ValueError(
                f"analysis root must not be a symbolic link: {requested_root}"
            )
        requested_root.mkdir(parents=True, exist_ok=True)
        self.root = requested_root.resolve()
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError(f"analysis root is not an owned directory: {self.root}")
        self.command = command
        self.invocation_id = uuid.uuid4().hex
        self.started_at: str | None = None
        self._descriptor: int | None = None

    def __enter__(self) -> AnalysisOperationLock:
        lock_path = self.root / LOCK_FILE_NAME
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(lock_path, flags, 0o600)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError(
                    "analysis operation lock must be one owned regular file: "
                    f"{lock_path}"
                )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                detail = _running_operation_detail(self.root)
                raise AnalysisBusyError(
                    "another repository-analysis operation is already running"
                    + (f": {detail}" if detail else "")
                ) from error
        except BaseException:
            os.close(descriptor)
            raise
        self._descriptor = descriptor
        try:
            previous = _load_activity(self.root)
            self.started_at = _utc_now()
            _publish_activity(
                self.root,
                {
                    "schema_version": ACTIVITY_SCHEMA_VERSION,
                    "is_running": True,
                    "invocation_id": self.invocation_id,
                    "command": self.command,
                    "pid": os.getpid(),
                    "hostname": socket.gethostname(),
                    "started_at": self.started_at,
                    "ended_at": None,
                    "result": None,
                    "previous": _previous_activity(previous),
                },
            )
        except BaseException:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            self._descriptor = None
            raise
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        descriptor = self._descriptor
        if descriptor is None:
            return
        result = "completed" if exception_type is None else "failed"
        try:
            current = _load_activity(self.root)
            _publish_activity(
                self.root,
                {
                    "schema_version": ACTIVITY_SCHEMA_VERSION,
                    "is_running": False,
                    "invocation_id": self.invocation_id,
                    "command": self.command,
                    "pid": os.getpid(),
                    "hostname": socket.gethostname(),
                    "started_at": self.started_at,
                    "ended_at": _utc_now(),
                    "result": result,
                    "previous": (
                        current.get("previous")
                        if isinstance(current, dict)
                        else None
                    ),
                },
            )
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            self._descriptor = None


def load_analysis_activity(analysis_root: Path) -> dict[str, Any] | None:
    """Return diagnostic activity without treating it as writer ownership."""

    return _load_activity(analysis_root.expanduser().resolve())


def is_analysis_writer_locked(analysis_root: Path) -> bool:
    """Return whether a writer currently owns an existing analysis lock.

    This probe is intentionally non-creating: a missing analysis root or lock
    file means that no writer owns the lock.  Activity metadata is not an
    ownership authority and is neither read nor changed here.
    """

    requested_root = analysis_root.expanduser().absolute()
    if requested_root.is_symlink():
        raise ValueError(
            f"analysis root must not be a symbolic link: {requested_root}"
        )
    if not requested_root.exists():
        return False
    root = requested_root.resolve()
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"analysis root is not an owned directory: {root}")

    lock_path = root / LOCK_FILE_NAME
    flags = os.O_RDONLY | os.O_NONBLOCK
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags)
    except FileNotFoundError:
        return False
    except OSError as error:
        if lock_path.is_symlink():
            raise ValueError(
                f"analysis operation lock must not be a symbolic link: {lock_path}"
            ) from error
        raise

    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError(
                "analysis operation lock must be one owned regular file: "
                f"{lock_path}"
            )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    finally:
        os.close(descriptor)


def _previous_activity(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    result = value.get("result")
    if value.get("is_running") is True:
        result = "interrupted"
    return {
        "invocation_id": value.get("invocation_id"),
        "command": value.get("command"),
        "started_at": value.get("started_at"),
        "ended_at": value.get("ended_at"),
        "result": result,
    }


def _running_operation_detail(root: Path) -> str | None:
    activity = _load_activity(root)
    if not isinstance(activity, dict):
        return None
    fields = []
    for name in ("command", "pid", "hostname", "started_at", "invocation_id"):
        value = activity.get(name)
        if value is not None:
            fields.append(f"{name}={value}")
    return ", ".join(fields) or None


def _load_activity(root: Path) -> dict[str, Any] | None:
    path = root / ACTIVITY_FILE_NAME
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"analysis activity is not a regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"analysis activity is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"analysis activity must contain an object: {path}")
    return value


def _publish_activity(root: Path, value: dict[str, Any]) -> None:
    destination = root / ACTIVITY_FILE_NAME
    temporary = root / f".{ACTIVITY_FILE_NAME}.tmp-{uuid.uuid4().hex}"
    try:
        with temporary.open("xb") as stream:
            stream.write(canonical_pretty_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        _fsync_directory(root)
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
