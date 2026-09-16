"""Failure-preserving execution and recovery for benchmark attempts."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from benchmarking.contracts import TerminationStatus, XmlStatus
from benchmarking.process_supervision import (
    DEFAULT_LOG_LIMIT,
    DEFAULT_TIMEOUT_GRACE_SECONDS,
    BoundedCapture,
    ResourceMonitor,
    _drain,
    _persist_capture,
    _process_exists,
    _process_group_exists,
    _send_group_signal,
    _signal_name,
    _wait_for_process_group,
)
from benchmarking.provenance import observe_file, utc_now
from benchmarking.storage import write_json_atomic


ATTEMPT_SCHEMA_VERSION = 2
CommandFactory = Callable[[Path], Sequence[str | os.PathLike[str]]]
XmlValidator = Callable[[Path], dict[str, Any]]


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
        stdout = _persist_capture(attempt_dir, "stdout.bin", stdout_capture)
        stderr = _persist_capture(attempt_dir, "stderr.bin", stderr_capture)
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
            "stdout": stdout,
            "stderr": stderr,
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
    stdout = _persist_capture(attempt_dir, "stdout.bin", stdout_capture)
    stderr = _persist_capture(attempt_dir, "stderr.bin", stderr_capture)
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
        "stdout": stdout,
        "stderr": stderr,
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
