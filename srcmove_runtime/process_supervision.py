"""Bounded, failure-preserving supervision for one tool process group."""

from __future__ import annotations

import hashlib
import os
import platform
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    """Identity needed to persist or recover a running process group."""

    pid: int
    process_group: int | None


@dataclass(frozen=True, slots=True)
class CaptureResult:
    """Bounded captured stream plus integrity metadata for the full stream."""

    retained: bytes
    total_bytes: int
    omitted_bytes: int
    truncated: bool
    sha256: str
    complete: bool
    error: str | None


@dataclass(frozen=True, slots=True)
class ResourceObservation:
    """Best-effort resource evidence collected while the process group ran."""

    peak_rss_bytes: int | None
    status: str
    measurement: str | None
    cgroup_oom_kill_observed: bool


@dataclass(frozen=True, slots=True)
class SupervisedProcessResult:
    """Domain-neutral outcome of supervising one process group."""

    command: tuple[str, ...]
    identity: ProcessIdentity | None
    termination_status: str
    exit_code: int | None
    signal_number: int | None
    timed_out: bool
    spawn_error: str | None
    signals_sent: tuple[int, ...]
    process_group_cleaned: bool
    process_tree_guarantee: str
    process_elapsed_seconds: float | None
    stdout: CaptureResult
    stderr: CaptureResult
    resources: ResourceObservation

    @property
    def capture_complete(self) -> bool:
        return self.stdout.complete and self.stderr.complete


StartedCallback = Callable[[ProcessIdentity], None]
InterruptedCallback = Callable[[SupervisedProcessResult], None]


class _ProcessGroupResourceSampler:
    """Sample all active process groups with one shared /proc traversal."""

    def __init__(self, sample_seconds: float = 0.01) -> None:
        self.sample_seconds = sample_seconds
        self._condition = threading.Condition()
        self._monitors: set[_ResourceMonitor] = set()
        self._generation = 0
        self._thread: threading.Thread | None = None

    @staticmethod
    def _read_group_rss(process_groups: set[int]) -> dict[int, int]:
        totals = {process_group: 0 for process_group in process_groups}
        try:
            process_dirs = list(Path("/proc").glob("[0-9]*"))
        except OSError:
            return totals
        for directory in process_dirs:
            try:
                stat_text = (directory / "stat").read_text()
                stat_fields = stat_text[stat_text.rfind(")") + 2 :].split()
                process_group = int(stat_fields[2])
                if process_group not in totals:
                    continue
                status = (directory / "status").read_text().splitlines()
                rss_line = next(line for line in status if line.startswith("VmRSS:"))
                totals[process_group] += int(rss_line.split()[1]) * 1024
            except (OSError, StopIteration, ValueError, IndexError):
                continue
        return totals

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
                for process_group, monitor in monitors.items():
                    if monitor in self._monitors:
                        monitor.peak_rss_bytes = max(
                            monitor.peak_rss_bytes,
                            totals.get(process_group, 0),
                        )
                self._generation += 1
                self._condition.notify_all()
                if self._monitors:
                    self._condition.wait(self.sample_seconds)

    def register(self, monitor: _ResourceMonitor) -> None:
        with self._condition:
            self._monitors.add(monitor)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run,
                    name="process-group-resource-sampler",
                    daemon=True,
                )
                self._thread.start()
            self._condition.notify_all()

    def unregister(self, monitor: _ResourceMonitor) -> None:
        with self._condition:
            if monitor not in self._monitors:
                return
            final_generation = self._generation + 1
            deadline = time.monotonic() + 1.0
            self._condition.notify_all()
            while self._generation < final_generation:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            self._monitors.discard(monitor)
            self._condition.notify_all()


class _ResourceMonitor:
    """Best-effort process-group RSS and cgroup OOM observation."""

    def __init__(self, process_group: int) -> None:
        self.process_group = process_group
        self.peak_rss_bytes = 0
        self._supported = platform.system() == "Linux" and Path("/proc").is_dir()
        self._registered = False
        self._memory_events = self._find_memory_events(process_group)
        self._oom_before = self._read_oom_kill()

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

    def _read_oom_kill(self) -> int | None:
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
        if self._supported and not self._registered:
            _RESOURCE_SAMPLER.register(self)
            self._registered = True

    def finish(self) -> ResourceObservation:
        if self._registered:
            _RESOURCE_SAMPLER.unregister(self)
            self._registered = False
        oom_after = self._read_oom_kill()
        oom_kill_observed = (
            self._oom_before is not None
            and oom_after is not None
            and oom_after > self._oom_before
        )
        return ResourceObservation(
            peak_rss_bytes=self.peak_rss_bytes if self._supported else None,
            status="observed" if self._supported else "unavailable",
            measurement="linux_proc_process_group" if self._supported else None,
            cgroup_oom_kill_observed=oom_kill_observed,
        )


_RESOURCE_SAMPLER = _ProcessGroupResourceSampler()


@dataclass
class _BoundedCapture:
    limit: int
    _head: bytearray = field(default_factory=bytearray)
    _tail: bytearray = field(default_factory=bytearray)
    _total: int = 0
    _hasher: Any = field(default_factory=hashlib.sha256)
    _error: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, block: bytes) -> None:
        with self._lock:
            self._total += len(block)
            self._hasher.update(block)
            head_limit = self.limit // 2
            head_remaining = max(0, head_limit - len(self._head))
            self._head.extend(block[:head_remaining])
            remainder = block[head_remaining:]
            if remainder:
                self._tail.extend(remainder)
                tail_limit = self.limit - head_limit
                if len(self._tail) > tail_limit:
                    del self._tail[: len(self._tail) - tail_limit]

    def fail(self, error: BaseException) -> None:
        with self._lock:
            self._error = f"{type(error).__name__}: {error}"

    def snapshot(self, *, thread_finished: bool) -> CaptureResult:
        with self._lock:
            retained = bytes(self._head + self._tail)
            return CaptureResult(
                retained=retained,
                total_bytes=self._total,
                omitted_bytes=self._total - len(retained),
                truncated=len(retained) < self._total,
                sha256=self._hasher.hexdigest(),
                complete=thread_finished and self._error is None,
                error=self._error,
            )


def _drain(stream: Any, capture: _BoundedCapture) -> None:
    try:
        while block := stream.read(64 * 1024):
            capture.add(block)
    except BaseException as error:
        capture.fail(error)
    finally:
        stream.close()


def _process_group_exists(process_group: int) -> bool:
    if os.name != "posix":
        return False
    if platform.system() == "Linux" and Path("/proc").is_dir():
        observed_member = False
        try:
            process_dirs = list(Path("/proc").glob("[0-9]*"))
        except OSError:
            process_dirs = []
        for directory in process_dirs:
            try:
                stat_text = (directory / "stat").read_text()
                stat_fields = stat_text[stat_text.rfind(")") + 2 :].split()
                if int(stat_fields[2]) != process_group:
                    continue
                observed_member = True
                if stat_fields[0] != "Z":
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


def process_exists(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_process_group(
    process: subprocess.Popen[bytes], deadline: float
) -> bool:
    while time.monotonic() < deadline:
        process.poll()
        leader_done = process.returncode is not None
        if leader_done:
            group_done = os.name != "posix" or not _process_group_exists(process.pid)
            if group_done:
                return True
        time.sleep(0.01)
    return False


def _send_group_signal(process: subprocess.Popen[bytes], number: int) -> bool:
    try:
        if os.name == "posix":
            os.killpg(process.pid, number)
        else:
            process.send_signal(number)
    except ProcessLookupError:
        return False
    return True


def _empty_resource_observation() -> ResourceObservation:
    return ResourceObservation(
        peak_rss_bytes=None,
        status="unavailable",
        measurement=None,
        cgroup_oom_kill_observed=False,
    )


def _result(
    *,
    command: tuple[str, ...],
    process: subprocess.Popen[bytes] | None,
    process_elapsed_seconds: float | None,
    termination_status: str,
    exit_code: int | None,
    signal_number: int | None,
    timed_out: bool,
    spawn_error: str | None,
    signals_sent: Sequence[int],
    stdout_capture: _BoundedCapture,
    stderr_capture: _BoundedCapture,
    threads: Sequence[threading.Thread],
    resources: ResourceObservation,
) -> SupervisedProcessResult:
    stdout_finished = len(threads) < 1 or not threads[0].is_alive()
    stderr_finished = len(threads) < 2 or not threads[1].is_alive()
    identity = (
        ProcessIdentity(
            pid=process.pid,
            process_group=process.pid if os.name == "posix" else None,
        )
        if process is not None
        else None
    )
    return SupervisedProcessResult(
        command=command,
        identity=identity,
        termination_status=termination_status,
        exit_code=exit_code,
        signal_number=signal_number,
        timed_out=timed_out,
        spawn_error=spawn_error,
        signals_sent=tuple(signals_sent),
        process_group_cleaned=(
            process is None
            or (os.name != "posix" and process.poll() is not None)
            or not _process_group_exists(process.pid)
        ),
        process_tree_guarantee=(
            "posix_process_group" if process is not None and os.name == "posix" else "none"
        ),
        process_elapsed_seconds=process_elapsed_seconds,
        stdout=stdout_capture.snapshot(thread_finished=stdout_finished),
        stderr=stderr_capture.snapshot(thread_finished=stderr_finished),
        resources=resources,
    )


def run_supervised_process(
    command: Sequence[str | os.PathLike[str]],
    *,
    cwd: Path,
    timeout_seconds: float,
    timeout_grace_seconds: float = 5.0,
    capture_limit: int,
    environment: Mapping[str, str] | None = None,
    on_started: StartedCallback | None = None,
    on_interrupted: InterruptedCallback | None = None,
) -> SupervisedProcessResult:
    """Run one isolated process group and return persistence-neutral evidence."""

    if capture_limit < 2:
        raise ValueError("capture limit must be at least two bytes")
    normalized_command = tuple(os.fspath(part) for part in command)
    stdout_capture = _BoundedCapture(capture_limit)
    stderr_capture = _BoundedCapture(capture_limit)
    process: subprocess.Popen[bytes] | None = None
    process_started: float | None = None
    process_elapsed_seconds: float | None = None
    resource_monitor: _ResourceMonitor | None = None
    threads: list[threading.Thread] = []
    signals_sent: list[int] = []
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
                env=dict(environment) if environment is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=os.name == "posix",
            )
        except OSError as error:
            spawn_error = f"{type(error).__name__}: {error}"
        else:
            process_started = time.monotonic()
            identity = ProcessIdentity(
                pid=process.pid,
                process_group=process.pid if os.name == "posix" else None,
            )
            if on_started is not None:
                on_started(identity)
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
            resource_monitor = _ResourceMonitor(process.pid)
            resource_monitor.start()

            completed = _wait_for_process_group(
                process,
                process_started + max(0.0, timeout_seconds),
            )
            timed_out = not completed
            if timed_out:
                if _send_group_signal(process, signal.SIGTERM):
                    signals_sent.append(signal.SIGTERM)
                completed = _wait_for_process_group(
                    process,
                    time.monotonic() + timeout_grace_seconds,
                )
                if not completed and _send_group_signal(process, signal.SIGKILL):
                    signals_sent.append(signal.SIGKILL)
                    _wait_for_process_group(process, time.monotonic() + 0.5)

            returncode = process.wait()
            process_elapsed_seconds = time.monotonic() - process_started
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
            if _send_group_signal(process, signal.SIGTERM):
                signals_sent.append(signal.SIGTERM)
            if not _wait_for_process_group(process, time.monotonic() + 1.0):
                if _send_group_signal(process, signal.SIGKILL):
                    signals_sent.append(signal.SIGKILL)
                    _wait_for_process_group(process, time.monotonic() + 0.5)
            if process.poll() is None:
                process.wait()
        for thread in threads:
            thread.join(timeout=5.0)
        resources = (
            resource_monitor.finish()
            if resource_monitor is not None
            else _empty_resource_observation()
        )
        interrupted = _result(
            command=normalized_command,
            process=process,
            process_elapsed_seconds=process_elapsed_seconds,
            termination_status="orchestration_interrupted",
            exit_code=None,
            signal_number=None,
            timed_out=False,
            spawn_error=spawn_error,
            signals_sent=signals_sent,
            stdout_capture=stdout_capture,
            stderr_capture=stderr_capture,
            threads=threads,
            resources=resources,
        )
        if on_interrupted is not None:
            on_interrupted(interrupted)
        raise

    for thread in threads:
        thread.join(timeout=5.0)
    resources = (
        resource_monitor.finish()
        if resource_monitor is not None
        else _empty_resource_observation()
    )
    return _result(
        command=normalized_command,
        process=process,
        process_elapsed_seconds=process_elapsed_seconds,
        termination_status=termination_status,
        exit_code=exit_code,
        signal_number=signal_number,
        timed_out=timed_out,
        spawn_error=spawn_error,
        signals_sent=signals_sent,
        stdout_capture=stdout_capture,
        stderr_capture=stderr_capture,
        threads=threads,
        resources=resources,
    )
