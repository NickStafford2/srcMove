"""Failure-preserving execution and recovery for benchmark attempts."""

from __future__ import annotations

import json
import os
import signal
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from benchmarking.contracts import TerminationStatus, XmlStatus
from benchmarking.provenance import observe_file, utc_now
from benchmarking.storage import write_json_atomic
from srcmove_runtime.process_supervision import (
    CaptureResult,
    ProcessIdentity,
    SupervisedProcessResult,
    process_exists,
    run_supervised_process,
)


ATTEMPT_SCHEMA_VERSION = 2
DEFAULT_LOG_LIMIT = 16 * 1024 * 1024
DEFAULT_TIMEOUT_GRACE_SECONDS = 5.0
CommandFactory = Callable[[Path], Sequence[str | os.PathLike[str]]]
XmlValidator = Callable[[Path], dict[str, Any]]
ProfileCallback = Callable[[str, float, Mapping[str, int]], None]


def _persist_capture(
    attempt_dir: Path, filename: str, capture: CaptureResult
) -> dict[str, Any]:
    retained_path = None
    if capture.retained:
        (attempt_dir / filename).write_bytes(capture.retained)
        retained_path = filename
    return {
        "path": retained_path,
        "total_bytes": capture.total_bytes,
        "retained_bytes": len(capture.retained),
        "omitted_bytes": capture.omitted_bytes,
        "truncated": capture.truncated,
        "sha256": capture.sha256,
        **({"error": capture.error} if capture.error is not None else {}),
    }


def _resource_usage(result: SupervisedProcessResult) -> dict[str, Any]:
    return {
        "peak_rss_bytes": result.resources.peak_rss_bytes,
        "peak_rss_status": result.resources.status,
        "measurement": result.resources.measurement,
        "cgroup_oom_kill_observed": (
            result.resources.cgroup_oom_kill_observed
        ),
    }


def _cleanup_signals(result: SupervisedProcessResult) -> list[dict[str, Any]]:
    return [
        {"number": number, "name": signal.Signals(number).name}
        for number in result.signals_sent
    ]


def _termination(result: SupervisedProcessResult) -> dict[str, Any]:
    if result.termination_status == "spawn_failed":
        return {
            "status": TerminationStatus.SPAWN_FAILED.value,
            "error": result.spawn_error,
        }
    if result.termination_status == "timed_out":
        return {"status": TerminationStatus.TIMED_OUT.value}
    if result.termination_status == "signaled":
        assert result.signal_number is not None
        try:
            signal_name = signal.Signals(result.signal_number).name
        except ValueError:
            signal_name = f"SIGNAL_{result.signal_number}"
        return {
            "status": TerminationStatus.SIGNALED.value,
            "signal_number": result.signal_number,
            "signal_name": signal_name,
        }
    return {
        "status": TerminationStatus.EXITED.value,
        "exit_code": result.exit_code,
    }


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
    profile_callback: ProfileCallback | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Run one isolated attempt and atomically write exactly one terminal record."""

    if log_limit < 2:
        raise ValueError("log limit must be at least two bytes")
    setup_started = time.perf_counter() if profile_callback is not None else None
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
    attempt_started = time.monotonic()

    def profile(
        name: str, started: float | None, counters: Mapping[str, int]
    ) -> None:
        if profile_callback is not None and started is not None:
            profile_callback(name, time.perf_counter() - started, counters)

    profile("attempt_setup", setup_started, {"attempt_directories": 1})

    def record_started(identity: ProcessIdentity) -> None:
        write_started = (
            time.perf_counter() if profile_callback is not None else None
        )
        started["pid"] = identity.pid
        started["process_group"] = identity.process_group
        write_json_atomic(attempt_dir / "started.json", started)
        if profile_callback is not None and write_started is not None:
            elapsed = time.perf_counter() - write_started
            profile_callback(
                "attempt_started_write",
                elapsed,
                {
                    "json_writes": 1,
                    "json_bytes": (attempt_dir / "started.json").stat().st_size,
                },
            )

    def record_interrupted(result: SupervisedProcessResult) -> None:
        stdout = _persist_capture(attempt_dir, "stdout.bin", result.stdout)
        stderr = _persist_capture(attempt_dir, "stderr.bin", result.stderr)
        record = {
            **started,
            "completed_at": utc_now(),
            "elapsed_seconds": time.monotonic() - attempt_started,
            "process_elapsed_seconds": result.process_elapsed_seconds,
            "termination": {
                "status": TerminationStatus.ORCHESTRATION_INTERRUPTED.value
            },
            "cleanup_signals": _cleanup_signals(result),
            "resource_usage": _resource_usage(result),
            "stdout": stdout,
            "stderr": stderr,
            "xml": {"status": XmlStatus.NOT_CHECKED.value},
            "admitted": False,
        }
        write_json_atomic(attempt_dir / "attempt.json", record)
        (attempt_dir / "started.json").unlink(missing_ok=True)

    supervision_started = (
        time.perf_counter() if profile_callback is not None else None
    )
    result = run_supervised_process(
        command,
        cwd=cwd,
        environment=environment,
        timeout_seconds=timeout_seconds,
        timeout_grace_seconds=timeout_grace_seconds,
        capture_limit=log_limit,
        on_started=record_started,
        on_interrupted=record_interrupted,
    )
    if profile_callback is not None and supervision_started is not None:
        profile_callback(
            "process_supervision",
            max(
                0.0,
                time.perf_counter() - supervision_started
                - (result.process_elapsed_seconds or 0.0),
            ),
            {},
        )
    termination = _termination(result)
    resource_usage = _resource_usage(result)
    capture_started = time.perf_counter() if profile_callback is not None else None
    stdout = _persist_capture(attempt_dir, "stdout.bin", result.stdout)
    stderr = _persist_capture(attempt_dir, "stderr.bin", result.stderr)
    profile(
        "attempt_capture_write",
        capture_started,
        {
            "log_writes": int(stdout["path"] is not None)
            + int(stderr["path"] is not None),
            "log_bytes": int(stdout["retained_bytes"])
            + int(stderr["retained_bytes"]),
        },
    )
    validation_started = (
        time.perf_counter() if profile_callback is not None else None
    )
    xml = xml_validator(output_path)
    profile(
        "xml_validation",
        validation_started,
        {"validation_bytes": int(xml.get("size_bytes") or 0)},
    )
    admitted = (
        termination["status"] == TerminationStatus.EXITED.value
        and termination.get("exit_code") == 0
        and xml["status"] == XmlStatus.VALID.value
        and result.capture_complete
    )
    record = {
        **started,
        "completed_at": utc_now(),
        "elapsed_seconds": time.monotonic() - attempt_started,
        "process_elapsed_seconds": result.process_elapsed_seconds,
        "termination": termination,
        "cleanup_signals": _cleanup_signals(result),
        "resource_failure": (
            "out_of_memory"
            if resource_usage["cgroup_oom_kill_observed"]
            else "unknown_resource_failure"
            if termination["status"] == TerminationStatus.SIGNALED.value
            and termination.get("signal_number") == signal.SIGKILL
            else None
        ),
        "resource_usage": resource_usage,
        "process_tree_guarantee": result.process_tree_guarantee,
        "log_capture_complete": result.capture_complete,
        "stdout": stdout,
        "stderr": stderr,
        "xml": xml,
        "output_path": output_filename,
        "output_retention": "retained",
        "admitted": admitted,
    }
    terminal_write_started = (
        time.perf_counter() if profile_callback is not None else None
    )
    write_json_atomic(attempt_dir / "attempt.json", record)
    profile(
        "attempt_terminal_write",
        terminal_write_started,
        {
            "json_writes": 1,
            "json_bytes": (attempt_dir / "attempt.json").stat().st_size,
        },
    )
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
        if isinstance(process_id, int) and process_exists(process_id):
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
