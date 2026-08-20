"""Focused Git inventory and worker-owned blob materialization."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .contracts import ChangedPath, VerifiedArtifact


REGULAR_GIT_MODES = {"100644", "100755"}
RETAINED_REF_PREFIX = "refs/srcmove/repository-analyses"


class GitMaterializationError(RuntimeError):
    """Git could not produce a complete safe sparse input tree."""


@dataclass(frozen=True, slots=True)
class FirstParentHistory:
    """One resolved bounded history in oldest-to-newest ancestry order."""

    resolved_start: str
    commits: tuple[str, ...]


def select_first_parent_history(
    repository: Path, start: str, pair_count: int
) -> FirstParentHistory:
    """Resolve a complete bounded first-parent history exactly once."""

    if (
        isinstance(pair_count, bool)
        or not isinstance(pair_count, int)
        or pair_count <= 0
    ):
        raise ValueError("pair count must be positive")
    if not isinstance(start, str) or not start or "\0" in start:
        raise ValueError("start revision must be a non-empty string")
    root = repository.expanduser().resolve(strict=True)
    shallow = _git(root, "rev-parse", "--is-shallow-repository")
    if shallow == "true":
        raise RuntimeError(
            "historical repository analysis requires a complete, non-shallow repository"
        )
    resolved = _git(root, "rev-parse", "--verify", f"{start}^{{commit}}")
    newest_first = tuple(
        line
        for line in _git(
            root,
            "rev-list",
            "--first-parent",
            f"--max-count={pair_count + 1}",
            resolved,
        ).splitlines()
        if line
    )
    if len(newest_first) < 2:
        raise RuntimeError(
            "the selected history has fewer than two commits; no adjacent pair exists"
        )
    return FirstParentHistory(resolved, tuple(reversed(newest_first)))


def retained_history_ref(manifest_bytes: bytes) -> str:
    """Return the deterministic namespaced ref for one exact frozen invocation."""

    identity = hashlib.sha256(manifest_bytes).hexdigest()
    return f"{RETAINED_REF_PREFIX}/{identity}/start"


def retain_history(repository: Path, ref: str, newest_commit: str) -> None:
    """Retain the frozen newest commit without permitting unsafe ref names."""

    if not ref.startswith(f"{RETAINED_REF_PREFIX}/") or not ref.endswith("/start"):
        raise ValueError(f"unsafe repository-analysis ref: {ref!r}")
    _git(repository, "update-ref", ref, newest_commit)


def verify_frozen_commits(
    repository: Path, commits: Iterable[str], *, retained_ref: str
) -> None:
    """Verify the retention ref and every native object ID in the manifest."""

    frozen = tuple(commits)
    if not frozen:
        raise ValueError("frozen commit sequence must not be empty")
    retained = _git(repository, "rev-parse", "--verify", f"{retained_ref}^{{commit}}")
    if retained != frozen[-1]:
        raise ValueError("retained history ref drift from frozen newest commit")
    for commit in frozen:
        _git(repository, "cat-file", "-e", f"{commit}^{{commit}}")


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip()
        raise RuntimeError(
            f"git {' '.join(arguments)} failed"
            + (f": {detail}" if detail else "")
        )
    return result.stdout.strip()


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
