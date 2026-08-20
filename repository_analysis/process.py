"""Bounded process supervision and focused artifact admission."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import signal
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .contracts import CaptureObservation, ProcessOutcome, VerifiedArtifact


DEFAULT_LOG_LIMIT = 1024 * 1024
DEFAULT_TIMEOUT_GRACE_SECONDS = 5.0
SRCML_NAMESPACE = "http://www.srcML.org/srcML/src"
SRCDIFF_NAMESPACES = {
    "http://www.srcML.org/srcDiff",
    "http://www.srcML.org/srcDiff/diff",
}
ArtifactValidator = Callable[[Path], VerifiedArtifact]


class ArtifactValidationError(RuntimeError):
    """A produced artifact could not be admitted."""

    def __init__(
        self, message: str, artifact: VerifiedArtifact | None = None
    ) -> None:
        super().__init__(message)
        self.artifact = artifact


class _ProcessGroupSampler:
    """Observe all active groups with one shared Linux /proc traversal."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._monitors: set[_ResourceMonitor] = set()
        self._generation = 0
        self._thread: threading.Thread | None = None

    @staticmethod
    def _read_group_rss(groups: set[int]) -> dict[int, int]:
        totals = {group: 0 for group in groups}
        try:
            process_directories = list(Path("/proc").glob("[0-9]*"))
        except OSError:
            return totals
        for directory in process_directories:
            try:
                stat = (directory / "stat").read_text()
                fields = stat[stat.rfind(")") + 2 :].split()
                process_group = int(fields[2])
                if process_group not in totals:
                    continue
                status = (directory / "status").read_text().splitlines()
                rss = next(line for line in status if line.startswith("VmRSS:"))
                totals[process_group] += int(rss.split()[1]) * 1024
            except (OSError, StopIteration, ValueError, IndexError):
                continue
        return totals

    def register(self, monitor: _ResourceMonitor) -> None:
        with self._condition:
            self._monitors.add(monitor)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run,
                    name="repository-analysis-resource-sampler",
                    daemon=True,
                )
                self._thread.start()
            self._condition.notify_all()

    def unregister(self, monitor: _ResourceMonitor) -> None:
        with self._condition:
            if monitor not in self._monitors:
                return
            target_generation = self._generation + 1
            self._condition.notify_all()
            deadline = time.monotonic() + 1.0
            while self._generation < target_generation:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            self._monitors.discard(monitor)
            self._condition.notify_all()

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._monitors:
                    self._condition.wait()
                monitors = {
                    monitor.process_group: monitor for monitor in self._monitors
                }
            totals = self._read_group_rss(set(monitors))
            with self._condition:
                for group, monitor in monitors.items():
                    if monitor in self._monitors:
                        monitor.peak_rss_bytes = max(
                            monitor.peak_rss_bytes, totals.get(group, 0)
                        )
                self._generation += 1
                self._condition.notify_all()
                if self._monitors:
                    self._condition.wait(0.01)


class _ResourceMonitor:
    """Best-effort process-group RSS and cgroup OOM observation."""

    def __init__(self, process_group: int) -> None:
        self.process_group = process_group
        self.peak_rss_bytes = 0
        self.supported = platform.system() == "Linux" and Path("/proc").is_dir()
        self._memory_events = self._find_memory_events(process_group)
        self._oom_before = self._read_oom_count()
        self._registered = False

    @staticmethod
    def _find_memory_events(process_id: int) -> Path | None:
        try:
            lines = Path(f"/proc/{process_id}/cgroup").read_text().splitlines()
        except OSError:
            return None
        for line in lines:
            parts = line.split(":", 2)
            if len(parts) == 3 and parts[0] == "0":
                candidate = (
                    Path("/sys/fs/cgroup")
                    / parts[2].lstrip("/")
                    / "memory.events"
                )
                return candidate if candidate.is_file() else None
        return None

    def _read_oom_count(self) -> int | None:
        if self._memory_events is None:
            return None
        try:
            fields = dict(
                line.split(maxsplit=1)
                for line in self._memory_events.read_text().splitlines()
            )
            return int(fields["oom_kill"])
        except (OSError, KeyError, ValueError):
            return None

    def start(self) -> None:
        if self.supported:
            _RESOURCE_SAMPLER.register(self)
            self._registered = True

    def finish(self) -> tuple[int | None, bool]:
        if self._registered:
            _RESOURCE_SAMPLER.unregister(self)
            self._registered = False
        oom_after = self._read_oom_count()
        oom_observed = (
            self._oom_before is not None
            and oom_after is not None
            and oom_after > self._oom_before
        )
        return (self.peak_rss_bytes if self.supported else None, oom_observed)


_RESOURCE_SAMPLER = _ProcessGroupSampler()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> tuple[int, str]:
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            hasher.update(block)
            size += len(block)
    return size, hasher.hexdigest()


def validate_xml_artifact(
    path: Path, *, shape: str, producing_stage: str
) -> VerifiedArtifact:
    """Admit a srcDiff-shaped XML file and record its checksum."""

    if shape not in {"archive", "single_file"}:
        raise ValueError(f"unknown srcDiff XML shape: {shape}")
    try:
        size, checksum = _sha256_file(path)
    except FileNotFoundError as error:
        raise ArtifactValidationError("output XML is missing") from error
    if size == 0:
        raise ArtifactValidationError(
            "output XML is empty",
            _invalid_artifact(
                path, size, checksum, producing_stage, shape, "empty"
            ),
        )

    namespaces: set[str] = set()
    try:
        parsed = ET.iterparse(path, events=("start-ns",))
        for _, namespace in parsed:
            namespaces.add(namespace[1])
        root = parsed.root
    except (ET.ParseError, OSError) as error:
        message = f"output XML is malformed: {error}"
        raise ArtifactValidationError(
            message,
            _invalid_artifact(
                path, size, checksum, producing_stage, shape, "malformed", message
            ),
        ) from error
    if root.tag != f"{{{SRCML_NAMESPACE}}}unit":
        message = "root must be a srcML unit element"
        raise ArtifactValidationError(
            message,
            _invalid_artifact(
                path,
                size,
                checksum,
                producing_stage,
                shape,
                "invalid_structure",
                message,
            ),
        )
    if not namespaces.intersection(SRCDIFF_NAMESPACES):
        message = "srcDiff namespace declaration is missing"
        raise ArtifactValidationError(
            message,
            _invalid_artifact(
                path,
                size,
                checksum,
                producing_stage,
                shape,
                "invalid_structure",
                message,
            ),
        )
    child_units = tuple(
        child for child in root if child.tag == f"{{{SRCML_NAMESPACE}}}unit"
    )
    if shape == "archive" and not child_units:
        message = "archive output must contain child unit elements"
        raise ArtifactValidationError(
            message,
            _invalid_artifact(
                path,
                size,
                checksum,
                producing_stage,
                shape,
                "invalid_structure",
                message,
            ),
        )
    if shape == "single_file" and child_units:
        message = "single-file output must not contain child unit elements"
        raise ArtifactValidationError(
            message,
            _invalid_artifact(
                path,
                size,
                checksum,
                producing_stage,
                shape,
                "invalid_structure",
                message,
            ),
        )
    return VerifiedArtifact(
        path=path,
        size_bytes=size,
        sha256=checksum,
        kind="xml",
        validation_status="valid",
        producing_stage=producing_stage,
        shape=shape,
    )


def _invalid_artifact(
    path: Path,
    size: int,
    checksum: str,
    producing_stage: str,
    shape: str,
    status: str,
    error: str | None = None,
) -> VerifiedArtifact:
    return VerifiedArtifact(
        path=path,
        size_bytes=size,
        sha256=checksum,
        kind="xml",
        validation_status=status,
        producing_stage=producing_stage,
        shape=shape,
        details=(("error", error),) if error is not None else (),
    )


def validate_results_artifact(
    path: Path,
    *,
    producing_stage: str = "srcmove",
    producing_command: tuple[str, ...] = (),
) -> tuple[VerifiedArtifact, tuple[tuple[str, Any], ...]]:
    """Admit srcMove JSON results and return normalized scalar metrics."""

    try:
        content = path.read_bytes()
    except FileNotFoundError as error:
        raise ArtifactValidationError("srcMove results JSON is missing") from error
    checksum = hashlib.sha256(content).hexdigest()
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        message = f"srcMove results JSON is malformed: {error}"
        raise ArtifactValidationError(
            message,
            _invalid_results_artifact(
                path,
                content,
                checksum,
                producing_stage,
                producing_command,
                "malformed",
                message,
            ),
        ) from error
    if not isinstance(value, dict):
        message = "srcMove results must be a JSON object"
        raise ArtifactValidationError(
            message,
            _invalid_results_artifact(
                path,
                content,
                checksum,
                producing_stage,
                producing_command,
                "invalid_structure",
                message,
            ),
        )
    move_count = value.get("move_count")
    if (
        isinstance(move_count, bool)
        or not isinstance(move_count, int)
        or move_count < 0
    ):
        message = "srcMove results require a non-negative integer move_count"
        raise ArtifactValidationError(
            message,
            _invalid_results_artifact(
                path,
                content,
                checksum,
                producing_stage,
                producing_command,
                "invalid_structure",
                message,
            ),
        )
    moves = value.get("moves")
    if moves is not None and (not isinstance(moves, list) or len(moves) != move_count):
        message = "srcMove results moves must be a list matching move_count"
        raise ArtifactValidationError(
            message,
            _invalid_results_artifact(
                path,
                content,
                checksum,
                producing_stage,
                producing_command,
                "invalid_structure",
                message,
            ),
        )
    metrics = tuple(
        sorted(
            (key, metric)
            for key, metric in value.items()
            if isinstance(metric, (int, float, str, bool)) or metric is None
        )
    )
    return (
        VerifiedArtifact(
            path=path,
            size_bytes=len(content),
            sha256=checksum,
            kind="json_results",
            validation_status="valid",
            producing_stage=producing_stage,
            producing_command=producing_command,
        ),
        metrics,
    )


def _invalid_results_artifact(
    path: Path,
    content: bytes,
    checksum: str,
    producing_stage: str,
    producing_command: tuple[str, ...],
    status: str,
    error: str,
) -> VerifiedArtifact:
    return VerifiedArtifact(
        path=path,
        size_bytes=len(content),
        sha256=checksum,
        kind="json_results",
        validation_status=status,
        producing_stage=producing_stage,
        producing_command=producing_command,
        details=(("error", error),),
    )


@dataclass
class _BoundedCapture:
    limit: int
    head: bytearray = field(default_factory=bytearray)
    tail: bytearray = field(default_factory=bytearray)
    total: int = 0
    hasher: Any = field(default_factory=hashlib.sha256)

    def add(self, block: bytes) -> None:
        self.total += len(block)
        self.hasher.update(block)
        head_limit = self.limit // 2
        head_remaining = max(0, head_limit - len(self.head))
        self.head.extend(block[:head_remaining])
        remainder = block[head_remaining:]
        if remainder:
            self.tail.extend(remainder)
            tail_limit = self.limit - head_limit
            if len(self.tail) > tail_limit:
                del self.tail[: len(self.tail) - tail_limit]

    def persist(self, path: Path) -> CaptureObservation:
        retained = bytes(self.head + self.tail)
        retained_path: Path | None = None
        if retained:
            path.write_bytes(retained)
            retained_path = path
        return CaptureObservation(
            path=retained_path,
            total_bytes=self.total,
            retained_bytes=len(retained),
            omitted_bytes=self.total - len(retained),
            truncated=len(retained) < self.total,
            sha256=self.hasher.hexdigest(),
        )


def _drain(stream: Any, capture: _BoundedCapture) -> None:
    try:
        while block := stream.read(64 * 1024):
            capture.add(block)
    finally:
        stream.close()


def _process_group_exists(process_group: int) -> bool:
    if os.name != "posix":
        return False
    if platform.system() == "Linux" and Path("/proc").is_dir():
        observed_member = False
        try:
            process_directories = list(Path("/proc").glob("[0-9]*"))
        except OSError:
            process_directories = []
        for directory in process_directories:
            try:
                stat = (directory / "stat").read_text()
                fields = stat[stat.rfind(")") + 2 :].split()
                if int(fields[2]) != process_group:
                    continue
                observed_member = True
                if fields[0] != "Z":
                    return True
            except (OSError, ValueError, IndexError):
                continue
        if observed_member:
            return False
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_group(process: subprocess.Popen[bytes], deadline: float) -> bool:
    while time.monotonic() < deadline:
        process.poll()
        if process.returncode is not None and not _process_group_exists(process.pid):
            return True
        time.sleep(0.01)
    return False


def _signal_group(process: subprocess.Popen[bytes], number: int) -> bool:
    try:
        if os.name == "posix":
            os.killpg(process.pid, number)
        else:
            process.send_signal(number)
    except ProcessLookupError:
        return False
    return True


def run_process(
    command: Sequence[str | os.PathLike[str]],
    *,
    cwd: Path,
    timeout_seconds: float,
    output_path: Path,
    validator: ArtifactValidator,
    capture_prefix: str,
    log_limit: int = DEFAULT_LOG_LIMIT,
    timeout_grace_seconds: float = DEFAULT_TIMEOUT_GRACE_SECONDS,
) -> ProcessOutcome:
    """Run one process group, bound logs, and validate its output once."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if log_limit < 2:
        raise ValueError("log_limit must be at least two bytes")
    normalized_command = tuple(os.fspath(part) for part in command)
    stdout_capture = _BoundedCapture(log_limit)
    stderr_capture = _BoundedCapture(log_limit)
    started_at = _utc_now()
    started = time.monotonic()
    process: subprocess.Popen[bytes] | None = None
    resource_monitor: _ResourceMonitor | None = None
    threads: list[threading.Thread] = []
    cleanup_signals: list[int] = []
    termination_status = "spawn_failed"
    exit_code: int | None = None
    signal_number: int | None = None
    timed_out = False
    spawn_error: str | None = None

    try:
        try:
            process = subprocess.Popen(
                normalized_command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=os.name == "posix",
            )
        except OSError as error:
            spawn_error = f"{type(error).__name__}: {error}"
        else:
            resource_monitor = _ResourceMonitor(process.pid)
            resource_monitor.start()
            assert process.stdout is not None
            assert process.stderr is not None
            threads = [
                threading.Thread(
                    target=_drain,
                    args=(process.stdout, stdout_capture),
                    daemon=True,
                ),
                threading.Thread(
                    target=_drain,
                    args=(process.stderr, stderr_capture),
                    daemon=True,
                ),
            ]
            for thread in threads:
                thread.start()
            completed = _wait_for_group(process, started + timeout_seconds)
            timed_out = not completed
            if timed_out:
                if _signal_group(process, signal.SIGTERM):
                    cleanup_signals.append(signal.SIGTERM)
                completed = _wait_for_group(
                    process, time.monotonic() + timeout_grace_seconds
                )
                if not completed and _signal_group(process, signal.SIGKILL):
                    cleanup_signals.append(signal.SIGKILL)
                    _wait_for_group(process, time.monotonic() + 0.5)
            returncode = process.wait()
            if timed_out:
                termination_status = "timed_out"
            elif returncode < 0:
                termination_status = "signaled"
                signal_number = -returncode
            else:
                termination_status = "exited"
                exit_code = returncode
    except BaseException:
        if process is not None and (
            process.poll() is None or _process_group_exists(process.pid)
        ):
            if _signal_group(process, signal.SIGTERM):
                cleanup_signals.append(signal.SIGTERM)
            if not _wait_for_group(process, time.monotonic() + 1.0):
                if _signal_group(process, signal.SIGKILL):
                    cleanup_signals.append(signal.SIGKILL)
                    _wait_for_group(process, time.monotonic() + 0.5)
            process.wait()
        if resource_monitor is not None:
            resource_monitor.finish()
            resource_monitor = None
        raise
    finally:
        for thread in threads:
            thread.join(timeout=5.0)

    peak_rss_bytes, oom_kill_observed = (
        resource_monitor.finish() if resource_monitor is not None else (None, False)
    )

    stdout = stdout_capture.persist(cwd / f"{capture_prefix}.stdout.bin")
    stderr = stderr_capture.persist(cwd / f"{capture_prefix}.stderr.bin")
    artifact: VerifiedArtifact | None = None
    validation_error: str | None = None
    try:
        artifact = validator(output_path)
        if not artifact.producing_command:
            artifact = replace(artifact, producing_command=normalized_command)
    except ArtifactValidationError as error:
        artifact = error.artifact
        if artifact is not None and not artifact.producing_command:
            artifact = replace(artifact, producing_command=normalized_command)
        validation_error = str(error)
    except OSError as error:
        validation_error = str(error)
    process_group_cleaned = process is None or not _process_group_exists(process.pid)
    return ProcessOutcome(
        command=normalized_command,
        working_directory=cwd.resolve(),
        started_at=started_at,
        completed_at=_utc_now(),
        elapsed_seconds=time.monotonic() - started,
        termination_status=termination_status,
        exit_code=exit_code,
        signal_number=signal_number,
        timed_out=timed_out,
        spawn_error=spawn_error,
        cleanup_signals=tuple(cleanup_signals),
        process_group_cleaned=process_group_cleaned,
        stdout=stdout,
        stderr=stderr,
        peak_rss_bytes=peak_rss_bytes,
        oom_kill_observed=oom_kill_observed,
        output_artifact=artifact,
        validation_error=validation_error,
    )
