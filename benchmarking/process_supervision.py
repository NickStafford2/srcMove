"""Low-level process-group supervision for benchmark attempts."""

from __future__ import annotations

import hashlib
import os
import platform
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_LOG_LIMIT = 16 * 1024 * 1024
DEFAULT_TIMEOUT_GRACE_SECONDS = 5.0


class _ProcessGroupResourceSampler:
    """Sample all active process groups with one shared /proc traversal."""

    def __init__(self, sample_seconds: float = 0.01) -> None:
        self.sample_seconds = sample_seconds
        self._condition = threading.Condition()
        self._monitors: set[ResourceMonitor] = set()
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

    def register(self, monitor: ResourceMonitor) -> None:
        with self._condition:
            self._monitors.add(monitor)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run,
                    name="benchmark-resource-sampler",
                    daemon=True,
                )
                self._thread.start()
            self._condition.notify_all()

    def unregister(self, monitor: ResourceMonitor) -> None:
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


class ResourceMonitor:
    """Best-effort Linux process-group RSS and cgroup OOM observation."""

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

    def finish(self) -> dict[str, Any]:
        if self._registered:
            _RESOURCE_SAMPLER.unregister(self)
            self._registered = False
        oom_after = self._read_oom_kill()
        oom_kill_observed = (
            self._oom_before is not None
            and oom_after is not None
            and oom_after > self._oom_before
        )
        return {
            "peak_rss_bytes": self.peak_rss_bytes if self._supported else None,
            "peak_rss_status": "observed" if self._supported else "unavailable",
            "measurement": "linux_proc_process_group" if self._supported else None,
            "cgroup_oom_kill_observed": oom_kill_observed,
        }


_RESOURCE_SAMPLER = _ProcessGroupResourceSampler()
@dataclass
class BoundedCapture:
    limit: int = DEFAULT_LOG_LIMIT
    _head: bytearray = field(default_factory=bytearray)
    _tail: bytearray = field(default_factory=bytearray)
    _total: int = 0
    _hasher: Any = field(default_factory=hashlib.sha256)

    @property
    def head_limit(self) -> int:
        return self.limit // 2

    @property
    def tail_limit(self) -> int:
        return self.limit - self.head_limit

    def add(self, block: bytes) -> None:
        self._total += len(block)
        self._hasher.update(block)
        head_remaining = max(0, self.head_limit - len(self._head))
        self._head.extend(block[:head_remaining])
        remainder = block[head_remaining:]
        if remainder:
            self._tail.extend(remainder)
            if len(self._tail) > self.tail_limit:
                del self._tail[: len(self._tail) - self.tail_limit]

    def retained(self) -> bytes:
        return bytes(self._head + self._tail)

    def metadata(self, filename: str | None) -> dict[str, Any]:
        retained = len(self._head) + len(self._tail)
        return {
            "path": filename,
            "total_bytes": self._total,
            "retained_bytes": retained,
            "omitted_bytes": self._total - retained,
            "truncated": retained < self._total,
            "sha256": self._hasher.hexdigest(),
        }


def _persist_capture(
    attempt_dir: Path, filename: str, capture: BoundedCapture
) -> dict[str, Any]:
    retained = capture.retained()
    if not retained:
        return capture.metadata(None)
    (attempt_dir / filename).write_bytes(retained)
    return capture.metadata(filename)


def _drain(stream: Any, capture: BoundedCapture) -> None:
    try:
        while block := stream.read(64 * 1024):
            capture.add(block)
    finally:
        stream.close()


def _process_group_exists(process_group: int) -> bool:
    if os.name != "posix":
        return False
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_exists(process_id: int) -> bool:
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
        group_done = os.name != "posix" or not _process_group_exists(process.pid)
        if leader_done and group_done:
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


def _signal_name(number: int) -> str:
    try:
        return signal.Signals(number).name
    except ValueError:
        return f"SIGNAL_{number}"
