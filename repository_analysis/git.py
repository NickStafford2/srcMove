"""Focused Git inventory and worker-owned blob materialization."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .contracts import ChangedPath, VerifiedArtifact


REGULAR_GIT_MODES = {"100644", "100755"}
GIT_MODE_NAMES = {"120000": "symlink", "160000": "submodule"}
RETAINED_REF_PREFIX = "refs/srcmove/repository-analyses"


class GitMaterializationError(RuntimeError):
    """Git could not produce a complete safe sparse input tree."""


def find_repository_root(path: Path) -> Path:
    """Return the containing non-bare Git worktree root."""

    requested = path.expanduser().resolve(strict=True)
    if not requested.is_dir():
        raise ValueError(
            f"repository working directory is not a directory: {requested}"
        )
    process = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=requested,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip()
        raise ValueError(
            f"not inside a Git worktree: {requested}"
            + (f" ({detail})" if detail else "")
        )
    root = Path(process.stdout.strip()).resolve(strict=True)
    if not root.is_dir():
        raise RuntimeError(f"Git returned an invalid worktree root: {root}")
    return root


@dataclass(frozen=True, slots=True)
class FirstParentHistory:
    """One resolved bounded history in oldest-to-newest ancestry order."""

    resolved_start: str
    commits: tuple[str, ...]
    history_exhausted: bool


def resolve_commit(repository: Path, revision: str) -> str:
    """Resolve one revision to its complete native commit object ID."""

    if not isinstance(revision, str) or not revision or "\0" in revision:
        raise ValueError("revision must be a non-empty string")
    root = repository.expanduser().resolve(strict=True)
    return _git(root, "rev-parse", "--verify", f"{revision}^{{commit}}")


def first_parent_distance(repository: Path, start: str, through: str) -> int:
    """Count pairs to a first-parent commit without loading every object ID."""

    root = repository.expanduser().resolve(strict=True)
    if _git(root, "rev-parse", "--is-shallow-repository") == "true":
        raise RuntimeError(
            "historical repository analysis requires a complete, non-shallow repository"
        )
    resolved_start = resolve_commit(root, start)
    resolved_through = resolve_commit(root, through)
    count_text = _git(
        root,
        "rev-list",
        "--first-parent",
        "--count",
        f"{resolved_through}..{resolved_start}",
    )
    try:
        distance = int(count_text)
    except ValueError as error:
        raise RuntimeError("Git returned a malformed first-parent count") from error
    candidate = _git(
        root,
        "rev-list",
        "--first-parent",
        "--max-count=1",
        f"--skip={distance}",
        resolved_start,
    )
    if candidate != resolved_through:
        raise ValueError("through commit is not on the frozen first-parent history")
    return distance


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
    history = select_older_first_parent_history(
        repository, start, pair_count=pair_count
    )
    if len(history.commits) < 2:
        raise RuntimeError(
            "the selected history has fewer than two commits; no adjacent pair exists"
        )
    return history


def select_older_first_parent_history(
    repository: Path,
    start: str,
    *,
    pair_count: int | None = None,
    through: str | None = None,
) -> FirstParentHistory:
    """Select an idempotent older-history target, allowing an exhausted frontier."""

    if pair_count is not None and (
        isinstance(pair_count, bool)
        or not isinstance(pair_count, int)
        or pair_count <= 0
    ):
        raise ValueError("pair count must be positive")
    if pair_count is not None and through is not None:
        raise ValueError("history selection accepts either pair_count or through")
    if not isinstance(start, str) or not start or "\0" in start:
        raise ValueError("start revision must be a non-empty string")
    if through is not None and (
        not isinstance(through, str) or not through or "\0" in through
    ):
        raise ValueError("through revision must be a non-empty string")
    root = repository.expanduser().resolve(strict=True)
    shallow = _git(root, "rev-parse", "--is-shallow-repository")
    if shallow == "true":
        raise RuntimeError(
            "historical repository analysis requires a complete, non-shallow repository"
        )
    resolved = _git(root, "rev-parse", "--verify", f"{start}^{{commit}}")
    if through is not None:
        resolved_through = _git(
            root, "rev-parse", "--verify", f"{through}^{{commit}}"
        )
        newest_first = tuple(
            line
            for line in _git(root, "rev-list", "--first-parent", resolved).splitlines()
            if line
        )
        try:
            through_index = newest_first.index(resolved_through)
        except ValueError as error:
            raise ValueError(
                "through commit is not on the frozen first-parent history"
            ) from error
        selected = newest_first[: through_index + 1]
        return FirstParentHistory(
            resolved,
            tuple(reversed(selected)),
            history_exhausted=through_index == len(newest_first) - 1,
        )
    maximum = [] if pair_count is None else [f"--max-count={pair_count + 2}"]
    newest_first = tuple(
        line
        for line in _git(
            root,
            "rev-list",
            "--first-parent",
            *maximum,
            resolved,
        ).splitlines()
        if line
    )
    if not newest_first:
        raise RuntimeError("Git returned no commits for the selected history")
    if pair_count is None:
        selected = newest_first
        exhausted = True
    else:
        selected = newest_first[: pair_count + 1]
        exhausted = len(newest_first) <= pair_count + 1
    return FirstParentHistory(resolved, tuple(reversed(selected)), exhausted)


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
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", frozen[-1], retained],
        cwd=repository,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if ancestry.returncode == 1:
        raise ValueError("retained history ref does not cover frozen newest commit")
    if ancestry.returncode != 0:
        detail = ancestry.stderr.strip()
        raise RuntimeError(
            "git merge-base --is-ancestor failed"
            + (f": {detail}" if detail else "")
        )
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
                exclusion_reasons=_unsupported_git_mode_reasons(
                    old_mode, new_mode
                ),
            )
        )

    excluded = {suffix.lower() for suffix in excluded_suffixes}
    analyzable = tuple(
        change
        for change in changed
        if not change.exclusion_reasons
        and change.content_changed
        and Path(change.path).suffix.lower() not in excluded
    )
    return tuple(changed), analyzable


def _unsupported_git_mode_reasons(
    old_mode: str, new_mode: str
) -> tuple[str, ...]:
    reasons = {
        f"unsupported_git_mode: {GIT_MODE_NAMES.get(mode, mode)}"
        for mode in (old_mode, new_mode)
        if mode != "000000" and mode not in REGULAR_GIT_MODES
    }
    return tuple(sorted(reasons))


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
