"""Run srcMove on XML without defining a detector's semantic expectations.

Every invocation keeps its input, outputs, command logs, and tool identity under
build/test-results. A later assertion failure therefore retains its evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from benchmarking.results import validate_results_schema
from benchmarking.tooling import find_srcmove

class ExecutionError(RuntimeError):
    """A required executable/input/output failed before semantic assertions."""


def require_success(completed):
    if completed.returncode != 0:
        raise ExecutionError(f"command failed (exit {completed.returncode}): {completed.args}\n{completed.stderr}")


def require_tool(tool):
    if tool is None:
        raise ExecutionError("required detector/upstream executable not found")


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_MODES = ("ordinary", "diagnostic", "results_only")
_ACTIVE_ARTIFACTS = ContextVar("srcmove_test_artifacts", default=None)


def _new_artifact_directory(case_id: str) -> Path:
    results_root = Path(os.environ.get("SRCMOVE_TEST_ARTIFACTS", REPO_ROOT / "build" / "test-results")) / "behavior"
    results_root.mkdir(parents=True, exist_ok=True)
    label = re.sub(r"[^A-Za-z0-9_.-]", "_", case_id)[-120:]
    return Path(tempfile.mkdtemp(prefix=label + "-", dir=results_root))


@contextmanager
def artifact_directory(*, case_id: str):
    """Keep source inputs and intermediate files even after later assertions fail."""
    directory = _new_artifact_directory(case_id)
    token = _ACTIVE_ARTIFACTS.set(directory)
    try:
        yield directory
    finally:
        _ACTIVE_ARTIFACTS.reset(token)


@dataclass(frozen=True)
class ModeObservation:
    name: str
    command: tuple[str, ...]
    completed: subprocess.CompletedProcess[str]
    results_json: Path
    output_xml: Path | None

    def payload(self) -> dict:
        payload = json.loads(self.results_json.read_text())
        failures = validate_results_schema(payload, require_xpaths=True)
        if failures:
            raise ExecutionError("invalid results: " + "; ".join(failures))
        return payload


@dataclass(frozen=True)
class ExecutionObservation:
    directory: Path
    binary: Path
    modes: tuple[ModeObservation, ...]


@lru_cache(maxsize=32)
def _binary_sha256(path: str, size: int, mtime_ns: int) -> str:
    # Cache by file identity, rather than hashing a large build for every case.
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_logged(command, *, artifacts: Path | None = None, **options):
    """Keep process evidence while preserving subprocess.run options and types."""
    root = artifacts if artifacts is not None else _ACTIVE_ARTIFACTS.get()
    if root is None:
        raise ExecutionError("run_logged requires an active artifact_directory")
    commands = Path(root) / "commands"
    commands.mkdir(exist_ok=True)
    directory = commands / f"{len(list(commands.iterdir())) + 1:04d}"
    directory.mkdir()
    argv = [os.fsdecode(arg) for arg in command]
    cwd = Path(options.get("cwd") or Path.cwd()).resolve()
    executable = Path(argv[0])
    if executable.is_absolute() or executable.parent != Path("."):
        executable = (cwd / executable).resolve()
    else:
        env = options.get("env") or os.environ
        executable = Path(shutil.which(argv[0], path=env.get("PATH")) or argv[0]).resolve()
    identity = {"path": str(executable)}
    if executable.is_file():
        stat = executable.stat()
        identity.update(size=stat.st_size, mtime_ns=stat.st_mtime_ns,
                        sha256=_binary_sha256(str(executable), stat.st_size, stat.st_mtime_ns))
    metadata = {"argv": argv, "cwd": str(cwd), "executable": identity, "status": "starting"}
    record = directory / "command.json"
    record.write_text(json.dumps(metadata, indent=2) + "\n")

    def snapshot(phase):
        # Subtests reuse inputs and output filenames. Snapshot both sides of the
        # process, including the small source directories supplied to srcdiff.
        snapshot_root = directory / phase
        snapshot_root.mkdir()
        for index, argument in enumerate(argv[1:], 1):
            path = (cwd / argument).resolve()
            destination = snapshot_root / f"argument-{index}-{path.name}"
            if path.is_file():
                shutil.copyfile(path, destination)
            elif path.is_dir() and not directory.is_relative_to(path):
                shutil.copytree(path, destination)

    snapshot("before")

    def finish(returncode, stdout, stderr, error=None):
        for name, value in (("stdout", stdout), ("stderr", stderr)):
            if isinstance(value, str):
                (directory / f"{name}.log").write_text(value)
            else:
                (directory / f"{name}.log").write_bytes(value or b"")
        metadata.update(status="error" if error else "completed", returncode=returncode)
        if error:
            metadata["error"] = str(error)
        record.write_text(json.dumps(metadata, indent=2) + "\n")
        snapshot("after")

    try:
        completed = subprocess.run(command, **options)
    except subprocess.CalledProcessError as error:
        finish(error.returncode, error.stdout, error.stderr, error)
        raise
    except subprocess.TimeoutExpired as error:
        finish(None, error.stdout, error.stderr, error)
        raise
    except OSError as error:
        finish(None, None, None, error)
        raise
    finish(completed.returncode, completed.stdout, completed.stderr)
    return completed


def execute_xml(
    xml: str | bytes,
    *,
    case_id: str,
    binary: Path | None = None,
    min_granularity: str | None = None,
    modes: tuple[str, ...] = OUTPUT_MODES,
) -> ExecutionObservation:
    """Observe explicitly requested modes; nonzero statuses remain inspectable.

None means srcMove's default granularity and emits no extra flag, preserving
the existing behavior fixtures' command and input semantics.
"""
    if not modes or len(set(modes)) != len(modes) or any(mode not in OUTPUT_MODES for mode in modes):
        raise ValueError(f"invalid output modes: {modes!r}")
    binary = find_srcmove(REPO_ROOT, binary)
    if binary is None:
        raise FileNotFoundError("required srcMove executable was not found")
    directory = _new_artifact_directory(case_id)
    fixture = directory / "input.xml"
    fixture.write_bytes(xml.encode() if isinstance(xml, str) else xml)
    stat = binary.stat()
    metadata = {
        "case_id": case_id,
        "input_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "min_granularity": min_granularity or "default",
        "binary": {"path": str(binary), "size": stat.st_size,
                   "mtime_ns": stat.st_mtime_ns,
                   "sha256": _binary_sha256(str(binary), stat.st_size, stat.st_mtime_ns)},
        "modes": [],
    }
    (directory / "execution.json").write_text(json.dumps(metadata, indent=2) + "\n")
    observations = []
    for mode in modes:
        results = directory / f"{mode}.json"
        output = None if mode == "results_only" else directory / f"{mode}.xml"
        command = [str(binary), str(fixture)]
        if output is not None:
            command.append(str(output))
        command += ["--results", str(results)]
        if mode != "ordinary":
            command.append("--diagnostics")
        if mode == "results_only":
            command.append("--results-only")
        if min_granularity is not None:
            command += ["--min-granularity", min_granularity]
        completed = run_logged(command, artifacts=directory, capture_output=True, text=True, check=False)
        (directory / f"{mode}.stdout.log").write_text(completed.stdout)
        (directory / f"{mode}.stderr.log").write_text(completed.stderr)
        metadata["modes"].append({"name": mode, "command": command,
                                  "returncode": completed.returncode})
        (directory / "execution.json").write_text(json.dumps(metadata, indent=2) + "\n")
        require_success(completed)
        observations.append(ModeObservation(mode, tuple(command), completed, results, output))
    return ExecutionObservation(directory, binary, tuple(observations))
