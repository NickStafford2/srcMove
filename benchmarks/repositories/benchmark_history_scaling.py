#!/usr/bin/env python3
"""Measure repository-history throughput across bounded worker counts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import random
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, MutableMapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
TESTS_ROOT = REPO_ROOT / "tests"
for import_root in (REPO_ROOT, TESTS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from benchmarks.contracts import canonical_json
from benchmarks.performance import describe
from benchmarks.process import write_json_atomic
from benchmarks.provenance import (
    observe_environment,
    observe_executable,
    observe_file,
    observe_repository,
    sha256_file,
    utc_now,
)
from benchmarks.repositories.run_case import (
    DEFAULT_DATA_ROOT,
    ensure_repo,
    load_case_config,
    normalize_repo_subdir,
)
from benchmarks.repositories.run_history import (
    load_history_results,
    select_first_parent_history,
)
from support.tooling import find_srcdiff, find_srcmove


SCALING_STUDY_SCHEMA_VERSION = 1
SCALING_TRIAL_SCHEMA_VERSION = 1
SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
TRIAL_COLUMNS = (
    "sequence",
    "phase",
    "repetition",
    "position",
    "jobs",
    "status",
    "exit_code",
    "wall_seconds",
    "cpu_user_seconds",
    "cpu_system_seconds",
    "cpu_total_seconds",
    "cpu_utilization",
    "peak_rss_bytes",
    "disk_bytes",
    "scratch_enabled",
    "scratch_root",
    "scratch_promotion_seconds",
    "selected_pairs",
    "analyzed_pairs",
    "skipped_pairs",
    "failed_pairs",
    "throughput_pairs_per_second",
    "analyzed_pairs_per_second",
    "normalized_results_sha256",
    "history_id",
    "history_manifest",
    "log_path",
)


@contextmanager
def _trial_data_storage(
    durable_data_root: Path,
    scratch_root: Path | None,
    observation: MutableMapping[str, Any],
) -> Iterator[Path]:
    """Yield isolated trial storage and promote it after the timed command."""

    if scratch_root is None:
        observation.update(
            {
                "scratch_enabled": False,
                "scratch_root": None,
                "scratch_promotion_seconds": 0.0,
            }
        )
        yield durable_data_root
        return

    supplied_root = scratch_root.expanduser()
    if supplied_root.is_symlink():
        raise ValueError(f"scratch root must not be a symbolic link: {supplied_root}")
    resolved_root = supplied_root.resolve()
    if not resolved_root.is_dir():
        raise ValueError(f"scratch root is not an existing directory: {resolved_root}")
    scratch_trial_root = Path(
        tempfile.mkdtemp(prefix="srcmove-history-scaling-", dir=resolved_root)
    )
    execution_data_root = scratch_trial_root / "data"
    observation.update(
        {
            "scratch_enabled": True,
            "scratch_root": str(resolved_root),
            "scratch_promotion_seconds": None,
        }
    )
    try:
        yield execution_data_root
    finally:
        promotion_started = time.monotonic()
        promoted = False
        try:
            if execution_data_root.exists():
                if durable_data_root.exists():
                    raise FileExistsError(
                        f"durable trial data already exists: {durable_data_root}"
                    )
                shutil.copytree(
                    execution_data_root,
                    durable_data_root,
                    symlinks=True,
                )
            promoted = True
        finally:
            observation["scratch_promotion_seconds"] = (
                time.monotonic() - promotion_started
            )
            if promoted:
                shutil.rmtree(scratch_trial_root)
SUMMARY_COLUMNS = (
    "jobs",
    "successful_trials",
    "failed_trials",
    "wall_seconds_median",
    "wall_seconds_mad",
    "wall_seconds_min",
    "wall_seconds_max",
    "throughput_pairs_per_second_median",
    "analyzed_pairs_per_second_median",
    "speedup",
    "parallel_efficiency",
    "marginal_time_improvement",
    "cpu_utilization_median",
    "peak_rss_bytes_median",
    "peak_rss_bytes_max",
    "disk_bytes_median",
    "normalized_results_equivalent",
)


def parse_jobs(value: str) -> list[int]:
    """Parse a comma-separated, unique, positive worker-count list."""

    try:
        jobs = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as error:
        raise argparse.ArgumentTypeError("--jobs must contain integers") from error
    if not jobs:
        raise argparse.ArgumentTypeError("--jobs must not be empty")
    if any(item <= 0 for item in jobs):
        raise argparse.ArgumentTypeError("--jobs values must be positive")
    if len(set(jobs)) != len(jobs):
        raise argparse.ArgumentTypeError("--jobs values must be unique")
    return jobs


def build_schedule(
    jobs: Sequence[int], *, repetitions: int, warmups: int, seed: int
) -> list[dict[str, Any]]:
    """Build a deterministic interleaved schedule with rotating positions."""

    if not jobs or any(item <= 0 for item in jobs):
        raise ValueError("schedule requires positive worker counts")
    if len(set(jobs)) != len(jobs):
        raise ValueError("schedule worker counts must be unique")
    if repetitions <= 0 or warmups < 0:
        raise ValueError("repetitions must be positive and warmups nonnegative")
    randomizer = random.Random(seed)
    base = list(jobs)
    randomizer.shuffle(base)
    schedule: list[dict[str, Any]] = []
    sequence = 0
    for phase, count in (("warmup", warmups), ("measured", repetitions)):
        for repetition in range(1, count + 1):
            offset = (repetition - 1) % len(base)
            order = base[offset:] + base[:offset]
            if repetition % 2 == 0:
                order = list(reversed(order))
            for position, worker_count in enumerate(order, start=1):
                sequence += 1
                schedule.append(
                    {
                        "sequence": sequence,
                        "phase": phase,
                        "repetition": repetition,
                        "position": position,
                        "jobs": worker_count,
                    }
                )
    return schedule


class ProcessTreeMonitor:
    """Best-effort peak RSS monitor for one Linux process and descendants."""

    def __init__(self, root_pid: int, sample_seconds: float = 0.02) -> None:
        self.root_pid = root_pid
        self.sample_seconds = sample_seconds
        self.peak_rss_bytes = 0
        self._supported = platform.system() == "Linux" and Path("/proc").is_dir()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def _process_observation(directory: Path) -> tuple[int, int] | None:
        try:
            status = (directory / "status").read_text().splitlines()
            parent = int(next(line for line in status if line.startswith("PPid:")).split()[1])
            rss = int(next(line for line in status if line.startswith("VmRSS:")).split()[1])
            return parent, rss * 1024
        except (OSError, StopIteration, ValueError, IndexError):
            return None

    def _sample(self) -> None:
        observations: dict[int, tuple[int, int]] = {}
        try:
            directories = list(Path("/proc").glob("[0-9]*"))
        except OSError:
            return
        for directory in directories:
            observation = self._process_observation(directory)
            if observation is not None:
                observations[int(directory.name)] = observation
        descendants = {self.root_pid}
        changed = True
        while changed:
            changed = False
            for process_id, (parent_id, _) in observations.items():
                if parent_id in descendants and process_id not in descendants:
                    descendants.add(process_id)
                    changed = True
        total = sum(
            observations[process_id][1]
            for process_id in descendants
            if process_id in observations
        )
        self.peak_rss_bytes = max(self.peak_rss_bytes, total)

    def _run(self) -> None:
        while not self._stop.wait(self.sample_seconds):
            self._sample()
        self._sample()

    def start(self) -> None:
        if self._supported:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def finish(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        return {
            "peak_rss_bytes": self.peak_rss_bytes if self._supported else None,
            "peak_rss_status": "observed" if self._supported else "unavailable",
            "measurement": "linux_proc_descendant_tree" if self._supported else None,
        }


def _directory_size(path: Path) -> int:
    total = 0
    for candidate in path.rglob("*"):
        try:
            if candidate.is_file() and not candidate.is_symlink():
                total += candidate.stat().st_size
        except OSError:
            continue
    return total


def _read_text(command: Sequence[str]) -> str | None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def observe_system(label: str | None) -> dict[str, Any]:
    """Capture stable container and resource-allocation context."""

    observation = observe_environment()
    observation["label"] = label
    observation["processor"] = platform.processor() or None
    observation["git_version"] = _read_text(["git", "--version"])
    for key, path in (
        ("cgroup_cpu_max", Path("/sys/fs/cgroup/cpu.max")),
        ("cgroup_memory_max", Path("/sys/fs/cgroup/memory.max")),
    ):
        try:
            observation[key] = path.read_text().strip()
        except OSError:
            observation[key] = None
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text().splitlines()
        observation["cpu_model"] = next(
            line.split(":", 1)[1].strip()
            for line in cpuinfo
            if line.startswith("model name")
        )
    except (OSError, StopIteration, IndexError):
        observation["cpu_model"] = None
    try:
        meminfo = Path("/proc/meminfo").read_text().splitlines()
        observation["memory_total_bytes"] = (
            int(
                next(
                    line for line in meminfo if line.startswith("MemTotal:")
                ).split()[1]
            )
            * 1024
        )
    except (OSError, StopIteration, ValueError, IndexError):
        observation["memory_total_bytes"] = None
    return observation


def _history_directory(trial_data_root: Path) -> Path | None:
    histories = trial_data_root / "repository-histories"
    if not histories.is_dir():
        return None
    candidates = [
        path
        for path in histories.iterdir()
        if path.is_dir() and path.name.startswith("history-")
    ]
    return candidates[0] if len(candidates) == 1 else None


def normalize_history_results(
    history_dir: Path, trial_data_root: Path
) -> tuple[str, list[dict[str, Any]]]:
    """Hash result-bearing fields while excluding IDs, paths, and timings."""

    _, pairs = load_history_results(history_dir)
    normalized: list[dict[str, Any]] = []
    for pair in pairs:
        results = None
        artifacts = pair.get("artifacts", {})
        relative = artifacts.get("results_path") if isinstance(artifacts, Mapping) else None
        if isinstance(relative, str):
            results_path = (trial_data_root / relative).resolve()
            if not results_path.is_relative_to(trial_data_root.resolve()):
                raise ValueError(f"result path escaped trial data root: {relative}")
            if results_path.is_file():
                results = json.loads(results_path.read_text(encoding="utf-8"))
        normalized.append(
            {
                key: pair.get(key)
                for key in (
                    "sequence",
                    "old_commit",
                    "new_commit",
                    "status",
                    "path_counts",
                    "changed_paths",
                    "counts",
                    "metrics",
                )
            }
            | {"results": results}
        )
    return hashlib.sha256(canonical_json(normalized)).hexdigest(), normalized


def _child_cpu_usage() -> tuple[float, float]:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime, usage.ru_stime


def run_trial(
    *,
    study_dir: Path,
    schedule_entry: Mapping[str, Any],
    case_name: str,
    start_commit: str,
    pair_count: int,
    selected_dir: str | None,
    retention: str,
    srcdiff: Path,
    srcmove: Path,
    srcdiff_timeout: float,
    srcmove_timeout: float,
    source_encoding: str,
    position: bool,
    expected_files: Mapping[str, tuple[Path, str]],
    scratch_root: Path | None = None,
) -> dict[str, Any]:
    """Run and observe one isolated history invocation."""

    for name, (path, expected_sha256) in expected_files.items():
        actual_sha256 = sha256_file(path)
        if actual_sha256 != expected_sha256:
            raise RuntimeError(
                f"{name} changed during scaling study: expected "
                f"{expected_sha256}, observed {actual_sha256}"
            )

    sequence = int(schedule_entry["sequence"])
    trial_name = (
        f"{sequence:04d}-{schedule_entry['phase']}-r"
        f"{schedule_entry['repetition']:02d}-j{schedule_entry['jobs']:02d}"
    )
    trial_dir = study_dir / "trials" / trial_name
    trial_dir.mkdir(parents=True, exist_ok=False)
    durable_data_root = trial_dir / "data"
    log_path = trial_dir / "history.log"
    storage_observation: dict[str, Any] = {}
    with _trial_data_storage(
        durable_data_root, scratch_root, storage_observation
    ) as trial_data_root:
        command = [
            sys.executable,
            str(SCRIPT_DIR / "run_history.py"),
            "start",
            case_name,
            "--start",
            start_commit,
            "--count",
            str(pair_count),
            "--jobs",
            str(schedule_entry["jobs"]),
            "--offline",
            "--retention",
            retention,
            "--data-root",
            str(trial_data_root),
            "--srcdiff",
            str(srcdiff),
            "--srcmove",
            str(srcmove),
            "--srcdiff-timeout",
            str(srcdiff_timeout),
            "--srcmove-timeout",
            str(srcmove_timeout),
            "--src-encoding",
            source_encoding,
            "--label",
            trial_name,
        ]
        if selected_dir is not None:
            command.extend(["--directory", selected_dir])
        if position:
            command.append("--position")

        before_user, before_system = _child_cpu_usage()
        started = time.monotonic()
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                command,
                cwd=REPO_ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            monitor = ProcessTreeMonitor(process.pid)
            monitor.start()
            try:
                exit_code = process.wait()
            except BaseException:
                if process.poll() is None:
                    try:
                        if os.name == "posix":
                            os.killpg(process.pid, signal.SIGTERM)
                        else:
                            process.terminate()
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=5.0)
                    except subprocess.TimeoutExpired:
                        try:
                            if os.name == "posix":
                                os.killpg(process.pid, signal.SIGKILL)
                            else:
                                process.kill()
                        except ProcessLookupError:
                            pass
                        process.wait()
                raise
            finally:
                resource_usage = monitor.finish()
        wall_seconds = time.monotonic() - started
        after_user, after_system = _child_cpu_usage()
    cpu_user = max(0.0, after_user - before_user)
    cpu_system = max(0.0, after_system - before_system)
    cpu_total = cpu_user + cpu_system

    history_dir = _history_directory(durable_data_root)
    history: dict[str, Any] | None = None
    normalized_sha256 = None
    normalization_error = None
    if history_dir is not None:
        try:
            history, _ = load_history_results(history_dir)
            normalized_sha256, _ = normalize_history_results(
                history_dir, durable_data_root
            )
        except Exception as error:
            normalization_error = f"{type(error).__name__}: {error}"
    aggregates = history.get("aggregates", {}) if history else {}
    selected_pairs = aggregates.get("selected_pairs")
    analyzed_pairs = aggregates.get("completed")
    status = (
        "success"
        if exit_code == 0
        and history is not None
        and history.get("status") == "completed"
        and normalized_sha256 is not None
        else "failed"
    )
    record: dict[str, Any] = {
        "schema_version": SCALING_TRIAL_SCHEMA_VERSION,
        **dict(schedule_entry),
        "trial_id": trial_name,
        "status": status,
        "exit_code": exit_code,
        "command": command,
        "completed_at": utc_now(),
        "wall_seconds": wall_seconds,
        "cpu_user_seconds": cpu_user,
        "cpu_system_seconds": cpu_system,
        "cpu_total_seconds": cpu_total,
        "cpu_utilization": cpu_total / wall_seconds if wall_seconds else None,
        **resource_usage,
        "disk_bytes": _directory_size(trial_dir),
        **storage_observation,
        "selected_pairs": selected_pairs,
        "analyzed_pairs": analyzed_pairs,
        "skipped_pairs": aggregates.get("no_analyzable_change"),
        "failed_pairs": aggregates.get("failed"),
        "throughput_pairs_per_second": (
            selected_pairs / wall_seconds
            if isinstance(selected_pairs, int) and wall_seconds
            else None
        ),
        "analyzed_pairs_per_second": (
            analyzed_pairs / wall_seconds
            if isinstance(analyzed_pairs, int) and wall_seconds
            else None
        ),
        "normalized_results_sha256": normalized_sha256,
        "normalization_error": normalization_error,
        "configuration_fingerprint_sha256": (
            history.get("configuration_fingerprint_sha256") if history else None
        ),
        "history_id": history.get("history_id") if history else None,
        "history_manifest": (
            str((history_dir / "history.json").relative_to(study_dir))
            if history_dir is not None
            else None
        ),
        "log_path": str(log_path.relative_to(study_dir)),
    }
    write_json_atomic(trial_dir / "trial.json", record)
    return record


def _median(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    value = describe(values)["median"]
    return float(value) if value is not None else None


def build_summary(
    rows: Sequence[Mapping[str, Any]],
    jobs: Sequence[int],
    *,
    marginal_threshold: float,
) -> dict[str, Any]:
    """Aggregate measured trials and locate a conservative scaling knee."""

    measured = [row for row in rows if row["phase"] == "measured"]
    successful = [row for row in measured if row["status"] == "success"]
    all_successful = [row for row in rows if row["status"] == "success"]
    by_jobs: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in successful:
        by_jobs[int(row["jobs"])].append(row)
    ordered_jobs = sorted(jobs)
    baseline_jobs = ordered_jobs[0]
    baseline_wall = _median(by_jobs[baseline_jobs], "wall_seconds")
    normalized_hashes = {
        str(row["normalized_results_sha256"])
        for row in all_successful
        if row.get("normalized_results_sha256")
    }
    configuration_hashes = {
        str(row["configuration_fingerprint_sha256"])
        for row in all_successful
        if row.get("configuration_fingerprint_sha256")
    }
    variants: dict[str, Any] = {}
    previous_wall = None
    for worker_count in ordered_jobs:
        selected = by_jobs[worker_count]
        wall = describe([float(row["wall_seconds"]) for row in selected])
        median_wall = wall["median"]
        speedup = (
            baseline_wall / float(median_wall)
            if baseline_wall is not None and median_wall not in (None, 0)
            else None
        )
        marginal = (
            (previous_wall - float(median_wall)) / previous_wall
            if previous_wall is not None and median_wall is not None and previous_wall
            else None
        )
        variants[str(worker_count)] = {
            "jobs": worker_count,
            "successful_trials": len(selected),
            "failed_trials": sum(
                row["status"] != "success"
                for row in measured
                if int(row["jobs"]) == worker_count
            ),
            "wall_seconds": wall,
            "throughput_pairs_per_second": describe(
                [float(row["throughput_pairs_per_second"]) for row in selected]
            ),
            "analyzed_pairs_per_second": describe(
                [float(row["analyzed_pairs_per_second"]) for row in selected]
            ),
            "cpu_utilization": describe(
                [float(row["cpu_utilization"]) for row in selected]
            ),
            "peak_rss_bytes": describe(
                [
                    float(row["peak_rss_bytes"])
                    for row in selected
                    if row.get("peak_rss_bytes") is not None
                ]
            ),
            "disk_bytes": describe(
                [float(row["disk_bytes"]) for row in selected]
            ),
            "speedup": speedup,
            "parallel_efficiency": (
                speedup / worker_count if speedup is not None else None
            ),
            "marginal_time_improvement": marginal,
        }
        if median_wall is not None:
            previous_wall = float(median_wall)

    diminishing_after = None
    for index in range(1, len(ordered_jobs) - 1):
        current = variants[str(ordered_jobs[index])]["marginal_time_improvement"]
        following = variants[str(ordered_jobs[index + 1])][
            "marginal_time_improvement"
        ]
        if (
            current is not None
            and following is not None
            and current < marginal_threshold
            and following < marginal_threshold
        ):
            diminishing_after = ordered_jobs[index - 1]
            break
    return {
        "schema_version": SCALING_STUDY_SCHEMA_VERSION,
        "total_trials": len(rows),
        "total_successful_trials": len(all_successful),
        "total_failed_trials": len(rows) - len(all_successful),
        "measured_trials": len(measured),
        "successful_trials": len(successful),
        "failed_trials": len(measured) - len(successful),
        "baseline_jobs": baseline_jobs,
        "marginal_threshold": marginal_threshold,
        "diminishing_returns_after_jobs": diminishing_after,
        "normalized_results_equivalent": len(normalized_hashes) == 1,
        "normalized_results_sha256": (
            next(iter(normalized_hashes)) if len(normalized_hashes) == 1 else None
        ),
        "normalized_result_hashes": sorted(normalized_hashes),
        "configuration_equivalent": len(configuration_hashes) == 1,
        "configuration_fingerprints": sorted(configuration_hashes),
        "jobs": variants,
    }


def _write_csv(path: Path, columns: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def write_summary_csv(path: Path, summary: Mapping[str, Any]) -> None:
    rows = []
    equivalent = summary["normalized_results_equivalent"]
    for value in summary["jobs"].values():
        rows.append(
            {
                "jobs": value["jobs"],
                "successful_trials": value["successful_trials"],
                "failed_trials": value["failed_trials"],
                "wall_seconds_median": value["wall_seconds"]["median"],
                "wall_seconds_mad": value["wall_seconds"]["mad"],
                "wall_seconds_min": value["wall_seconds"]["min"],
                "wall_seconds_max": value["wall_seconds"]["max"],
                "throughput_pairs_per_second_median": value[
                    "throughput_pairs_per_second"
                ]["median"],
                "analyzed_pairs_per_second_median": value[
                    "analyzed_pairs_per_second"
                ]["median"],
                "speedup": value["speedup"],
                "parallel_efficiency": value["parallel_efficiency"],
                "marginal_time_improvement": value["marginal_time_improvement"],
                "cpu_utilization_median": value["cpu_utilization"]["median"],
                "peak_rss_bytes_median": value["peak_rss_bytes"]["median"],
                "peak_rss_bytes_max": value["peak_rss_bytes"]["max"],
                "disk_bytes_median": value["disk_bytes"]["median"],
                "normalized_results_equivalent": equivalent,
            }
        )
    _write_csv(path, SUMMARY_COLUMNS, rows)


def _study_identifier(label: str | None) -> str:
    suffix = label or "history-scaling"
    if not SAFE_LABEL_RE.fullmatch(suffix):
        raise ValueError(
            "label must start with an alphanumeric character and contain only "
            "letters, digits, '.', '_', or '-'"
        )
    timestamp = utc_now().replace(":", "").replace("+", "-")
    return f"scaling-{timestamp}-{suffix}-{uuid.uuid4()}"


def run_study(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    case_dir = SCRIPT_DIR / args.case
    config_path = case_dir / "info.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"repository case not found: {config_path}")
    config = load_case_config(config_path)
    selected_dir = (
        normalize_repo_subdir(args.directory, "--directory")
        if args.directory is not None
        else config["directory"]
    )
    clone_dir = case_dir / "work" / "repo"
    ensure_repo(
        config["github"], clone_dir, offline=args.offline, update=args.fetch
    )
    resolved_start, commits = select_first_parent_history(
        clone_dir, args.start, args.count
    )
    pair_count = len(commits) - 1
    srcdiff = find_srcdiff(REPO_ROOT, args.srcdiff)
    srcmove = find_srcmove(REPO_ROOT, args.srcmove)
    if srcdiff is None or srcmove is None:
        raise FileNotFoundError("srcdiff and srcMove executables are required")

    study_id = _study_identifier(args.label)
    study_dir = (
        args.data_root.expanduser().resolve() / "history-scaling" / study_id
    )
    study_dir.mkdir(parents=True, exist_ok=False)
    (study_dir / "trials").mkdir()
    schedule = build_schedule(
        args.jobs,
        repetitions=args.repetitions,
        warmups=args.warmups,
        seed=args.seed,
    )
    commit_list = [commit.commit for commit in commits]
    study: dict[str, Any] = {
        "schema_version": SCALING_STUDY_SCHEMA_VERSION,
        "study_id": study_id,
        "status": "running",
        "created_at": utc_now(),
        "label": args.label,
        "workload": {
            "case": args.case,
            "repository": config["github"],
            "directory": selected_dir,
            "requested_start": args.start,
            "resolved_start": resolved_start,
            "requested_pair_count": args.count,
            "available_pair_count": pair_count,
            "commits": commit_list,
            "commit_list_sha256": hashlib.sha256(
                canonical_json(commit_list)
            ).hexdigest(),
        },
        "policy": {
            "jobs": args.jobs,
            "repetitions": args.repetitions,
            "warmups": args.warmups,
            "seed": args.seed,
            "ordering": "deterministic_interleaved_rotating",
            "retention": args.retention,
            "scratch_root": (
                str(args.scratch_root.expanduser().resolve())
                if args.scratch_root is not None
                else None
            ),
            "marginal_threshold": args.marginal_threshold,
            "result_equivalence": "normalized_pair_receipts_and_available_results",
        },
        "configuration": {
            "position": args.position,
            "source_encoding": args.src_encoding,
            "srcdiff_timeout_seconds": args.srcdiff_timeout,
            "srcmove_timeout_seconds": args.srcmove_timeout,
        },
        "schedule": schedule,
        "observation": {
            "system": observe_system(args.environment_label),
            "repositories": {
                "srcMove": observe_repository(REPO_ROOT),
                "srcDiff": observe_repository(REPO_ROOT.parent / "srcDiff"),
            },
            "executables": {
                "srcdiff": observe_executable(srcdiff),
                "srcmove": observe_executable(srcmove),
            },
            "implementation": {
                "scaling_runner": observe_file(Path(__file__)),
                "history_runner": observe_file(SCRIPT_DIR / "run_history.py"),
            },
        },
        "trials": [],
    }
    write_json_atomic(study_dir / "study.json", study)
    rows: list[dict[str, Any]] = []
    expected_files = {
        "srcdiff executable": (srcdiff, sha256_file(srcdiff)),
        "srcMove executable": (srcmove, sha256_file(srcmove)),
        "history runner": (
            SCRIPT_DIR / "run_history.py",
            sha256_file(SCRIPT_DIR / "run_history.py"),
        ),
    }
    try:
        for entry in schedule:
            print(
                f"[{entry['sequence']}/{len(schedule)}] "
                f"{entry['phase']} repeat {entry['repetition']}, "
                f"jobs={entry['jobs']}"
            )
            row = run_trial(
                study_dir=study_dir,
                schedule_entry=entry,
                case_name=args.case,
                start_commit=resolved_start,
                pair_count=pair_count,
                selected_dir=selected_dir,
                retention=args.retention,
                srcdiff=srcdiff,
                srcmove=srcmove,
                srcdiff_timeout=args.srcdiff_timeout,
                srcmove_timeout=args.srcmove_timeout,
                source_encoding=args.src_encoding,
                position=args.position,
                expected_files=expected_files,
                scratch_root=args.scratch_root,
            )
            rows.append(row)
            study["trials"].append(
                {
                    "sequence": row["sequence"],
                    "trial_id": row["trial_id"],
                    "status": row["status"],
                    "path": f"trials/{row['trial_id']}/trial.json",
                }
            )
            write_json_atomic(study_dir / "study.json", study)
            print(
                f"  {row['status']}: {row['wall_seconds']:.2f}s, "
                f"{row.get('throughput_pairs_per_second') or 0:.3f} pairs/s, "
                f"peak RSS {((row.get('peak_rss_bytes') or 0) / 1024 / 1024):.1f} MiB"
            )
        _write_csv(study_dir / "trials.csv", TRIAL_COLUMNS, rows)
        summary = build_summary(
            rows, args.jobs, marginal_threshold=args.marginal_threshold
        )
        write_json_atomic(study_dir / "summary.json", summary)
        write_summary_csv(study_dir / "summary.csv", summary)
        status = (
            "completed"
            if summary["total_failed_trials"] == 0
            and summary["normalized_results_equivalent"]
            and summary["configuration_equivalent"]
            else "completed_with_failures"
        )
        study.update(
            {
                "status": status,
                "completed_at": utc_now(),
                "summary": {
                    "path": "summary.json",
                    "sha256": sha256_file(study_dir / "summary.json"),
                },
                "trials_csv": {
                    "path": "trials.csv",
                    "sha256": sha256_file(study_dir / "trials.csv"),
                },
                "summary_csv": {
                    "path": "summary.csv",
                    "sha256": sha256_file(study_dir / "summary.csv"),
                },
            }
        )
        write_json_atomic(study_dir / "study.json", study)
        return study_dir, study
    except BaseException:
        study.update({"status": "interrupted", "completed_at": utc_now()})
        write_json_atomic(study_dir / "study.json", study)
        raise


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark repository-history throughput across worker counts."
    )
    parser.add_argument("case")
    parser.add_argument("--start", required=True)
    parser.add_argument("--count", required=True, type=int)
    parser.add_argument("--jobs", required=True, type=parse_jobs)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--label")
    parser.add_argument("--environment-label")
    parser.add_argument("--directory")
    network = parser.add_mutually_exclusive_group()
    network.add_argument("--fetch", action="store_true")
    network.add_argument("--offline", action="store_true")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument(
        "--scratch-root",
        type=Path,
        help=(
            "existing local directory for timed trial data; finalized trial "
            "reports are promoted to --data-root afterward"
        ),
    )
    parser.add_argument("--srcdiff", type=Path)
    parser.add_argument("--srcmove", type=Path)
    parser.add_argument("--srcdiff-timeout", type=float, default=1800.0)
    parser.add_argument("--srcmove-timeout", type=float, default=300.0)
    parser.add_argument("--src-encoding", default="UTF-8")
    parser.add_argument("--position", action="store_true")
    parser.add_argument(
        "--retention",
        choices=("results", "compact", "ephemeral"),
        default="results",
        help="history artifact retention per trial; default: results",
    )
    parser.add_argument(
        "--marginal-threshold",
        type=float,
        default=0.10,
        help="fractional improvement below which returns diminish; default: 0.10",
    )
    args = parser.parse_args(argv)
    if args.count <= 0:
        parser.error("--count must be positive")
    if args.repetitions <= 0 or args.warmups < 0:
        parser.error("--repetitions must be positive and --warmups nonnegative")
    if args.srcdiff_timeout <= 0 or args.srcmove_timeout <= 0:
        parser.error("timeouts must be positive")
    if not 0 < args.marginal_threshold < 1:
        parser.error("--marginal-threshold must be between 0 and 1")
    if args.label is not None and not SAFE_LABEL_RE.fullmatch(args.label):
        parser.error("--label contains unsafe characters")
    return args


def print_summary(study_dir: Path, study: Mapping[str, Any]) -> None:
    summary = json.loads((study_dir / "summary.json").read_text(encoding="utf-8"))
    print(f"\nHistory scaling study: {study['study_id']}")
    print(f"  Status: {study['status'].replace('_', ' ')}")
    print("  Jobs   Median    Speedup   Efficiency   Throughput   Peak RSS")
    for value in summary["jobs"].values():
        wall = value["wall_seconds"]["median"]
        speedup = value["speedup"]
        efficiency = value["parallel_efficiency"]
        throughput = value["throughput_pairs_per_second"]["median"]
        peak_rss = value["peak_rss_bytes"]["median"]
        if None in (wall, speedup, efficiency, throughput, peak_rss):
            print(f"  {value['jobs']:>4}   insufficient successful trials")
        else:
            print(
                f"  {value['jobs']:>4}   {wall:>6.2f}s   {speedup:>6.2f}x   "
                f"{efficiency:>9.1%}   {throughput:>8.3f}/s   "
                f"{(peak_rss / 1024 / 1024):>7.1f} MiB"
            )
    knee = summary["diminishing_returns_after_jobs"]
    print(
        "  Diminishing returns: "
        + (f"after {knee} jobs" if knee is not None else "not established")
    )
    print(
        "  Results equivalent: "
        f"{'yes' if summary['normalized_results_equivalent'] else 'NO'}"
    )
    print(f"  Study:   {(study_dir / 'study.json').resolve()}")
    print(f"  Summary: {(study_dir / 'summary.csv').resolve()}")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    study_dir, study = run_study(args)
    print_summary(study_dir, study)
    return 0 if study["status"] == "completed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
