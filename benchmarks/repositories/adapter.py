"""Repository inputs adapted to the shared benchmark pipeline."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from benchmarks.contracts import (
    InputPair,
    MaterializedInputPair,
    SemanticResult,
    SemanticStatus,
)


REGULAR_GIT_MODES = {"100644", "100755"}


class GitSnapshotMaterializationError(RuntimeError):
    """Git could not produce a complete direct input snapshot."""


@dataclass(frozen=True)
class GitSnapshotEntry:
    path: str
    old_mode: str
    new_mode: str
    old_blob: str
    new_blob: str


class GitRepositorySnapshotAdapter:
    """Materialize selected Git blobs directly into snapshot staging."""

    name = "repository"
    version = 1

    def __init__(
        self,
        *,
        case_id: str,
        repository: Path,
        entries: Sequence[GitSnapshotEntry],
        work_dir: Path,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.case_id = case_id
        self.repository = repository.resolve()
        self.entries = tuple(sorted(entries, key=lambda entry: entry.path))
        self.work_dir = work_dir
        self.metadata = dict(metadata or {})

    @staticmethod
    def _validate_entry(entry: GitSnapshotEntry) -> None:
        path = Path(entry.path)
        if path.is_absolute() or ".." in path.parts or not entry.path:
            raise ValueError(f"unsafe Git snapshot path: {entry.path!r}")
        for side, mode, blob in (
            ("old", entry.old_mode, entry.old_blob),
            ("new", entry.new_mode, entry.new_blob),
        ):
            if mode == "000000":
                continue
            if mode not in REGULAR_GIT_MODES:
                raise ValueError(
                    f"unsupported {side} Git object mode {mode} for {entry.path}"
                )
            if not blob or set(blob) == {"0"}:
                raise ValueError(f"missing {side} Git blob for {entry.path}")

    def _materialize_side(
        self, side: str, destination: Path
    ) -> dict[str, Any]:
        destination.mkdir(parents=True, exist_ok=False)
        selected = [
            (
                entry,
                entry.old_mode if side == "old" else entry.new_mode,
                entry.old_blob if side == "old" else entry.new_blob,
            )
            for entry in self.entries
            if (entry.old_mode if side == "old" else entry.new_mode) != "000000"
        ]
        if not selected:
            return {"kind": "directory", "files": [], "excluded": []}

        process = subprocess.Popen(
            ["git", "cat-file", "--batch"],
            cwd=self.repository,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        files = []
        try:
            for entry, mode, blob in selected:
                process.stdin.write(f"{blob}\n".encode("ascii"))
                process.stdin.flush()
                header = process.stdout.readline().decode(
                    "utf-8", errors="replace"
                ).strip()
                fields = header.split()
                if len(fields) != 3 or fields[1] != "blob":
                    raise RuntimeError(
                        f"git cat-file returned malformed header for {entry.path}: "
                        f"{header!r}"
                    )
                size = int(fields[2])
                target = destination / entry.path
                target.parent.mkdir(parents=True, exist_ok=True)
                hasher = hashlib.sha256()
                remaining = size
                with target.open("wb") as stream:
                    while remaining:
                        block = process.stdout.read(min(1024 * 1024, remaining))
                        if not block:
                            raise RuntimeError(
                                f"git cat-file truncated blob for {entry.path}"
                            )
                        stream.write(block)
                        hasher.update(block)
                        remaining -= len(block)
                if process.stdout.read(1) != b"\n":
                    raise RuntimeError(
                        f"git cat-file omitted blob delimiter for {entry.path}"
                    )
                target.chmod(0o755 if mode == "100755" else 0o644)
                files.append(
                    {
                        "path": entry.path,
                        "size_bytes": size,
                        "sha256": hasher.hexdigest(),
                    }
                )
            process.stdin.close()
            stderr = process.stderr.read() if process.stderr is not None else b""
            returncode = process.wait()
            if returncode != 0:
                raise RuntimeError(
                    "git cat-file failed while materializing snapshot\n"
                    f"stderr:\n{stderr.decode(errors='replace')}"
                )
        except BaseException:
            if process.poll() is None:
                process.kill()
            process.wait()
            raise
        finally:
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None and not pipe.closed:
                    pipe.close()
        return {"kind": "directory", "files": files, "excluded": []}

    def materialize_input_pairs(
        self, sources_root: Path, excluded_suffixes: Sequence[str]
    ) -> Sequence[MaterializedInputPair]:
        try:
            for entry in self.entries:
                self._validate_entry(entry)
                if Path(entry.path).suffix.lower() in excluded_suffixes:
                    raise ValueError(
                        "excluded path reached Git snapshot materializer: "
                        f"{entry.path}"
                    )
            self.work_dir.mkdir(parents=True, exist_ok=True)
            case_root = sources_root / self.case_id
            original = self._materialize_side("old", case_root / "original")
            modified = self._materialize_side("new", case_root / "modified")
            return [
                MaterializedInputPair(
                    case_id=self.case_id,
                    original=original,
                    modified=modified,
                    metadata=self.metadata,
                )
            ]
        except GitSnapshotMaterializationError:
            raise
        except Exception as error:
            raise GitSnapshotMaterializationError(str(error)) from error


class RepositoryAdapter:
    name = "repository"
    version = 1

    def __init__(
        self,
        *,
        case_id: str,
        original: Path,
        modified: Path,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.case = InputPair(
            case_id=case_id,
            original=original,
            modified=modified,
            metadata=metadata or {},
        )

    def input_pairs(self) -> Sequence[InputPair]:
        return [self.case]

    def validate_semantics(
        self, case: InputPair, srcdiff_xml: Path
    ) -> SemanticResult:
        return SemanticResult(SemanticStatus.NOT_APPLICABLE)
