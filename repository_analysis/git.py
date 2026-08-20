"""Focused Git inventory and worker-owned blob materialization."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Iterable

from .contracts import ChangedPath, VerifiedArtifact


REGULAR_GIT_MODES = {"100644", "100755"}


class GitMaterializationError(RuntimeError):
    """Git could not produce a complete safe sparse input tree."""


def inventory_changed_paths(
    repository: Path,
    old_commit: str,
    new_commit: str,
    selected_directory: str | None,
    excluded_suffixes: tuple[str, ...],
) -> tuple[tuple[ChangedPath, ...], tuple[ChangedPath, ...]]:
    """Return all and analyzable raw changes without rename collapsing."""

    command = [
        "git",
        "diff",
        "--raw",
        "-z",
        "--no-abbrev",
        "--no-renames",
        old_commit,
        new_commit,
        "--",
    ]
    if selected_directory:
        command.append(selected_directory)
    result = subprocess.run(
        command,
        cwd=repository,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Git inventory failed for {old_commit}..{new_commit}: "
            f"{result.stderr.decode(errors='replace').strip()}"
        )
    fields = result.stdout.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    if len(fields) % 2:
        raise RuntimeError("Git returned malformed raw changed-path metadata")

    changed: list[ChangedPath] = []
    for index in range(0, len(fields), 2):
        header = fields[index].decode("ascii", errors="replace")
        path = fields[index + 1].decode("utf-8", errors="surrogateescape")
        parts = header.removeprefix(":").split()
        if len(parts) != 5:
            raise RuntimeError(f"Git returned malformed change header: {header!r}")
        old_mode, new_mode, old_blob, new_blob, status = parts
        changed.append(
            ChangedPath(
                status=status,
                path=path,
                old_mode=old_mode,
                new_mode=new_mode,
                old_blob=old_blob,
                new_blob=new_blob,
            )
        )

    excluded = {suffix.lower() for suffix in excluded_suffixes}
    analyzable = tuple(
        change
        for change in changed
        if change.content_changed and Path(change.path).suffix.lower() not in excluded
    )
    return tuple(changed), analyzable


def _validate_change(change: ChangedPath) -> None:
    path = Path(change.path)
    if not change.path or path.is_absolute() or ".." in path.parts:
        raise GitMaterializationError(f"unsafe changed path: {change.path!r}")
    for side, exists, mode, blob in (
        ("old", change.exists_in_old, change.old_mode, change.old_blob),
        ("new", change.exists_in_new, change.new_mode, change.new_blob),
    ):
        if not exists:
            continue
        if mode not in REGULAR_GIT_MODES:
            raise GitMaterializationError(
                f"unsupported {side} Git object mode {mode} for {change.path}"
            )
        if not blob or set(blob) == {"0"}:
            raise GitMaterializationError(
                f"missing {side} Git blob for {change.path}"
            )


class GitBatch:
    """One reusable ``git cat-file --batch`` process owned by a worker."""

    def __init__(self, repository: Path) -> None:
        self.repository = repository.resolve()
        self._process = subprocess.Popen(
            ["git", "cat-file", "--batch"],
            cwd=self.repository,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    @property
    def process_id(self) -> int:
        return self._process.pid

    def close(self) -> None:
        process = self._process
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    def __enter__(self) -> GitBatch:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def materialize(
        self,
        changes: Iterable[ChangedPath],
        *,
        side: str,
        destination: Path,
    ) -> tuple[VerifiedArtifact, ...]:
        """Write one sparse side and hash every blob during the single read."""

        if side not in {"old", "new"}:
            raise ValueError(f"unknown materialization side: {side}")
        if destination.exists() or destination.is_symlink():
            raise GitMaterializationError(
                f"materialization destination already exists: {destination}"
            )
        destination.mkdir(parents=True)

        artifacts: list[VerifiedArtifact] = []
        for change in changes:
            _validate_change(change)
            mode = change.old_mode if side == "old" else change.new_mode
            blob = change.old_blob if side == "old" else change.new_blob
            if mode == "000000":
                continue
            artifacts.append(
                self._write_blob(blob, mode, change.path, destination, side)
            )
        return tuple(artifacts)

    def _write_blob(
        self,
        blob: str,
        mode: str,
        relative_path: str,
        destination: Path,
        side: str,
    ) -> VerifiedArtifact:
        process = self._process
        if process.poll() is not None:
            raise GitMaterializationError(
                f"git cat-file exited unexpectedly with {process.returncode}"
            )
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(f"{blob}\n".encode("ascii"))
        process.stdin.flush()
        header = process.stdout.readline().decode("ascii", errors="replace").strip()
        fields = header.split()
        if len(fields) != 3 or fields[1] != "blob" or fields[0] != blob:
            raise GitMaterializationError(
                f"git cat-file returned malformed header for {relative_path}: "
                f"{header!r}"
            )
        try:
            size = int(fields[2])
        except ValueError as error:
            raise GitMaterializationError(
                f"git cat-file returned invalid size for {relative_path}: {header!r}"
            ) from error

        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        hasher = hashlib.sha256()
        remaining = size
        try:
            with target.open("xb") as stream:
                while remaining:
                    block = process.stdout.read(min(1024 * 1024, remaining))
                    if not block:
                        raise GitMaterializationError(
                            f"git cat-file truncated blob for {relative_path}"
                        )
                    stream.write(block)
                    hasher.update(block)
                    remaining -= len(block)
        except OSError as error:
            raise GitMaterializationError(str(error)) from error
        if process.stdout.read(1) != b"\n":
            raise GitMaterializationError(
                f"git cat-file omitted blob delimiter for {relative_path}"
            )
        target.chmod(0o755 if mode == "100755" else 0o644)
        return VerifiedArtifact(
            path=target,
            size_bytes=size,
            sha256=hasher.hexdigest(),
            kind="git_blob",
            validation_status="valid",
            producing_stage="git_materialization",
            producing_command=("git", "cat-file", "--batch"),
            details=(("side", side), ("git_blob", blob), ("git_mode", mode)),
            retention="ephemeral_input",
        )
