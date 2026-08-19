"""Failure-preserving process execution for benchmark attempts."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import signal
import subprocess
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from benchmarks.contracts import TerminationStatus, XmlStatus
from benchmarks.provenance import observe_file, utc_now


ATTEMPT_SCHEMA_VERSION = 2
DEFAULT_LOG_LIMIT = 16 * 1024 * 1024
DEFAULT_TIMEOUT_GRACE_SECONDS = 5.0
SRCML_NAMESPACE = "http://www.srcML.org/srcML/src"
SRCDIFF_NAMESPACES = {
    "http://www.srcML.org/srcDiff",
    "http://www.srcML.org/srcDiff/diff",
}
CommandFactory = Callable[[Path], Sequence[str | os.PathLike[str]]]
XmlValidator = Callable[[Path], dict[str, Any]]


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


def write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


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

    def metadata(self, filename: str) -> dict[str, Any]:
        retained = len(self._head) + len(self._tail)
        return {
            "path": filename,
            "total_bytes": self._total,
            "retained_bytes": retained,
            "omitted_bytes": self._total - retained,
            "truncated": retained < self._total,
            "sha256": self._hasher.hexdigest(),
        }


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


def validate_srcdiff_xml(path: Path, expected_shape: str) -> dict[str, Any]:
    """Perform generic structural admission without dataset semantics."""

    artifact = observe_file(path)
    if artifact["status"] != "observed":
        return {"status": XmlStatus.MISSING.value}
    base = {
        "size_bytes": artifact["size_bytes"],
        "sha256": artifact["sha256"],
    }
    if artifact["size_bytes"] == 0:
        return {"status": XmlStatus.EMPTY.value, **base}

    namespaces = set()
    try:
        parsed = ET.iterparse(path, events=("start-ns",))
        for _, namespace in parsed:
            namespaces.add(namespace[1])
        root = parsed.root
    except (ET.ParseError, OSError) as error:
        return {
            "status": XmlStatus.MALFORMED.value,
            "error": str(error),
            **base,
        }

    if root.tag != f"{{{SRCML_NAMESPACE}}}unit":
        return {
            "status": XmlStatus.INVALID_STRUCTURE.value,
            "error": "root must be a srcML unit element",
            **base,
        }
    if not namespaces.intersection(SRCDIFF_NAMESPACES):
        return {
            "status": XmlStatus.INVALID_STRUCTURE.value,
            "error": "srcDiff namespace declaration is missing",
            **base,
        }

    child_units = [
        child for child in root if child.tag == f"{{{SRCML_NAMESPACE}}}unit"
    ]
    if expected_shape == "archive" and not child_units:
        return {
            "status": XmlStatus.INVALID_STRUCTURE.value,
            "error": "archive output must contain child unit elements",
            **base,
        }
    if expected_shape == "single_file" and child_units:
        return {
            "status": XmlStatus.INVALID_STRUCTURE.value,
            "error": "single-file output must not contain child unit elements",
            **base,
        }
    if expected_shape not in {"archive", "single_file"}:
        raise ValueError(f"unknown srcDiff XML shape: {expected_shape}")
    return {"status": XmlStatus.VALID.value, **base}


def execute_attempt(
    *,
    attempts_root: Path,
    stage: str,
    case_id: str,
    command_factory: CommandFactory,
    cwd: Path,
    timeout_seconds: float,
    xml_validator: XmlValidator,
    output_filename: str,
    log_limit: int = DEFAULT_LOG_LIMIT,
    timeout_grace_seconds: float = DEFAULT_TIMEOUT_GRACE_SECONDS,
    parent_attempt_id: str | None = None,
    retry_ordinal: int = 0,
    environment: Mapping[str, str] | None = None,
    context: Mapping[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Run one isolated attempt and atomically write exactly one terminal record."""

    if log_limit < 2:
        raise ValueError("log limit must be at least two bytes")
    attempt_id = f"attempt-{uuid.uuid4()}"
    attempt_dir = attempts_root / attempt_id
    attempt_dir.mkdir(parents=True, exist_ok=False)
    output_path = attempt_dir / output_filename
    command = [os.fspath(part) for part in command_factory(output_path)]
    started_at = utc_now()
    effective_environment = os.environ if environment is None else environment
    started = {
        "schema_version": ATTEMPT_SCHEMA_VERSION,
        "attempt_id": attempt_id,
        "stage": stage,
        "case_id": case_id,
        "started_at": started_at,
        "command": command,
        "working_directory": str(cwd.expanduser().resolve()),
        "timeout_seconds": timeout_seconds,
        "timeout_grace_seconds": timeout_grace_seconds,
        "parent_attempt_id": parent_attempt_id,
        "retry_ordinal": retry_ordinal,
        "context": dict(context or {}),
        "output_path": output_filename,
        "environment": {
            key: effective_environment.get(key)
            for key in ("PATH", "LANG", "LC_ALL", "TZ")
            if effective_environment.get(key) is not None
        },
    }
    write_json_atomic(attempt_dir / "started.json", started)

    stdout_capture = BoundedCapture(log_limit)
    stderr_capture = BoundedCapture(log_limit)
    cleanup_signals: list[dict[str, Any]] = []
    termination: dict[str, Any]
    process: subprocess.Popen[bytes] | None = None
    threads: list[threading.Thread] = []
    resource_monitor: ResourceMonitor | None = None
    start = time.monotonic()
    process_elapsed_seconds: float | None = None

    try:
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=dict(environment) if environment is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=os.name == "posix",
            )
        except OSError as error:
            termination = {
                "status": TerminationStatus.SPAWN_FAILED.value,
                "error": f"{type(error).__name__}: {error}",
            }
        else:
            start = time.monotonic()
            started["pid"] = process.pid
            started["process_group"] = process.pid if os.name == "posix" else None
            write_json_atomic(attempt_dir / "started.json", started)
            assert process.stdout is not None
            assert process.stderr is not None
            threads = [
                threading.Thread(
                    target=_drain, args=(process.stdout, stdout_capture), daemon=True
                ),
                threading.Thread(
                    target=_drain, args=(process.stderr, stderr_capture), daemon=True
                ),
            ]
            for thread in threads:
                thread.start()
            resource_monitor = ResourceMonitor(process.pid)
            resource_monitor.start()

            completed = _wait_for_process_group(
                process, start + max(0.0, timeout_seconds)
            )
            timed_out = not completed
            if timed_out:
                if _send_group_signal(process, signal.SIGTERM):
                    cleanup_signals.append(
                        {"number": signal.SIGTERM, "name": "SIGTERM"}
                    )
                completed = _wait_for_process_group(
                    process, time.monotonic() + timeout_grace_seconds
                )
                if not completed and _send_group_signal(process, signal.SIGKILL):
                    cleanup_signals.append(
                        {"number": signal.SIGKILL, "name": "SIGKILL"}
                    )
                    _wait_for_process_group(process, time.monotonic() + 0.5)

            returncode = process.wait()
            process_elapsed_seconds = time.monotonic() - start
            if timed_out:
                termination = {"status": TerminationStatus.TIMED_OUT.value}
            elif returncode < 0:
                number = -returncode
                termination = {
                    "status": TerminationStatus.SIGNALED.value,
                    "signal_number": number,
                    "signal_name": _signal_name(number),
                }
            else:
                termination = {
                    "status": TerminationStatus.EXITED.value,
                    "exit_code": returncode,
                }
    except BaseException:
        if process is not None and (
            process.poll() is None or _process_group_exists(process.pid)
        ):
            if _send_group_signal(process, signal.SIGTERM):
                cleanup_signals.append(
                    {"number": signal.SIGTERM, "name": "SIGTERM"}
                )
            if not _wait_for_process_group(process, time.monotonic() + 1.0):
                if _send_group_signal(process, signal.SIGKILL):
                    cleanup_signals.append(
                        {"number": signal.SIGKILL, "name": "SIGKILL"}
                    )
                    _wait_for_process_group(process, time.monotonic() + 0.5)
            if process.poll() is None:
                process.wait()
        for thread in threads:
            thread.join(timeout=5.0)
        resource_usage = (
            resource_monitor.finish()
            if resource_monitor is not None
            else {
                "peak_rss_bytes": None,
                "peak_rss_status": "unavailable",
                "measurement": None,
                "cgroup_oom_kill_observed": False,
            }
        )
        stdout_path = attempt_dir / "stdout.bin"
        stderr_path = attempt_dir / "stderr.bin"
        stdout_path.write_bytes(stdout_capture.retained())
        stderr_path.write_bytes(stderr_capture.retained())
        record = {
            **started,
            "completed_at": utc_now(),
            "elapsed_seconds": time.monotonic() - start,
            "process_elapsed_seconds": process_elapsed_seconds,
            "termination": {
                "status": TerminationStatus.ORCHESTRATION_INTERRUPTED.value
            },
            "cleanup_signals": cleanup_signals,
            "resource_usage": resource_usage,
            "stdout": stdout_capture.metadata(stdout_path.name),
            "stderr": stderr_capture.metadata(stderr_path.name),
            "xml": {"status": XmlStatus.NOT_CHECKED.value},
            "admitted": False,
        }
        write_json_atomic(attempt_dir / "attempt.json", record)
        (attempt_dir / "started.json").unlink(missing_ok=True)
        raise

    for thread in threads:
        thread.join(timeout=5.0)
    resource_usage = (
        resource_monitor.finish()
        if resource_monitor is not None
        else {
            "peak_rss_bytes": None,
            "peak_rss_status": "unavailable",
            "measurement": None,
            "cgroup_oom_kill_observed": False,
        }
    )
    log_capture_complete = not any(thread.is_alive() for thread in threads)
    stdout_path = attempt_dir / "stdout.bin"
    stderr_path = attempt_dir / "stderr.bin"
    stdout_path.write_bytes(stdout_capture.retained())
    stderr_path.write_bytes(stderr_capture.retained())
    xml = xml_validator(output_path)
    admitted = (
        termination["status"] == TerminationStatus.EXITED.value
        and termination.get("exit_code") == 0
        and xml["status"] == XmlStatus.VALID.value
        and log_capture_complete
    )
    record = {
        **started,
        "completed_at": utc_now(),
        "elapsed_seconds": time.monotonic() - start,
        "process_elapsed_seconds": process_elapsed_seconds,
        "termination": termination,
        "cleanup_signals": cleanup_signals,
        "resource_failure": (
            "out_of_memory"
            if resource_usage["cgroup_oom_kill_observed"]
            else "unknown_resource_failure"
            if termination["status"] == TerminationStatus.SIGNALED.value
            and termination.get("signal_number") == signal.SIGKILL
            else None
        ),
        "resource_usage": resource_usage,
        "process_tree_guarantee": (
            "posix_process_group" if os.name == "posix" else "none"
        ),
        "log_capture_complete": log_capture_complete,
        "stdout": stdout_capture.metadata(stdout_path.name),
        "stderr": stderr_capture.metadata(stderr_path.name),
        "xml": xml,
        "output_path": output_filename,
        "output_retention": "retained",
        "admitted": admitted,
    }
    write_json_atomic(attempt_dir / "attempt.json", record)
    (attempt_dir / "started.json").unlink(missing_ok=True)
    return attempt_dir, record


def set_attempt_output_retention(
    attempt_dir: Path,
    retention: str,
    *,
    canonical_path: str | None = None,
    discard: bool = False,
) -> dict[str, Any]:
    """Update a sealed attempt after its output receives a durable owner."""

    terminal_path = attempt_dir / "attempt.json"
    record = json.loads(terminal_path.read_text(encoding="utf-8"))
    output_name = record.get("output_path")
    output_exists = isinstance(output_name, str) and (attempt_dir / output_name).exists()
    if (
        record.get("output_retention") == retention
        and record.get("canonical_output_path") == canonical_path
        and (not discard or not output_exists)
    ):
        return record
    if discard and isinstance(output_name, str):
        (attempt_dir / output_name).unlink(missing_ok=True)
    record["output_retention"] = retention
    if canonical_path is None:
        record.pop("canonical_output_path", None)
    else:
        record["canonical_output_path"] = canonical_path
    write_json_atomic(terminal_path, record)
    return record


def recover_interrupted_attempts(attempts_root: Path) -> list[str]:
    """Seal abandoned staging directories that have no terminal record."""

    recovered = []
    if not attempts_root.is_dir():
        return recovered
    for attempt_dir in sorted(attempts_root.glob("attempt-*")):
        terminal_path = attempt_dir / "attempt.json"
        started_path = attempt_dir / "started.json"
        if terminal_path.exists() or not started_path.is_file():
            continue
        try:
            started = json.loads(started_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            started = {
                "schema_version": ATTEMPT_SCHEMA_VERSION,
                "attempt_id": attempt_dir.name,
            }
        process_id = started.get("pid")
        if isinstance(process_id, int) and _process_exists(process_id):
            continue
        record = {
            **started,
            "completed_at": utc_now(),
            "termination": {
                "status": TerminationStatus.ORCHESTRATION_INTERRUPTED.value
            },
            "cleanup_signals": [],
            "stdout": {"status": "unavailable"},
            "stderr": {"status": "unavailable"},
            "elapsed_seconds": None,
            "xml": {
                "status": XmlStatus.NOT_CHECKED.value,
                "partial_artifact": observe_file(
                    attempt_dir / started.get("output_path", "partial.srcdiff.xml")
                ),
            },
            "admitted": False,
            "recovered": True,
        }
        write_json_atomic(terminal_path, record)
        started_path.unlink(missing_ok=True)
        recovered.append(attempt_dir.name)
    return recovered
