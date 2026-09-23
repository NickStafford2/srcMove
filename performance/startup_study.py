#!/usr/bin/env python3
"""Measure startup cost introduced by srcMove's shared-library layers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import resource
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any


PROBE_SOURCE = r"""
#include <cstdio>
#include <cstdlib>
#include <ctime>

static timespec preinit_time;
static timespec main_time;
static bool report_timing = false;

static void report_exit_time() {
  if (!report_timing) {
    return;
  }
  timespec exit_time;
  clock_gettime(CLOCK_MONOTONIC, &exit_time);
  const long long elapsed_ns =
      (exit_time.tv_sec - main_time.tv_sec) * 1000000000LL +
      (exit_time.tv_nsec - main_time.tv_nsec);
  std::printf("post_main_ns=%lld\n", elapsed_ns);
}

static void record_preinit_time() {
  clock_gettime(CLOCK_MONOTONIC, &preinit_time);
  std::atexit(report_exit_time);
}

__attribute__((section(".preinit_array"), used))
static void (*record_preinit_time_entry)() = record_preinit_time;

int main() {
  clock_gettime(CLOCK_MONOTONIC, &main_time);
  report_timing = std::getenv("SRCMOVE_STARTUP_REPORT_INIT") != nullptr;
  if (report_timing) {
    const long long elapsed_ns =
        (main_time.tv_sec - preinit_time.tv_sec) * 1000000000LL +
        (main_time.tv_nsec - preinit_time.tv_nsec);
    std::printf("pre_main_ns=%lld\n", elapsed_ns);
  }
  return 0;
}
"""
NEEDED_RE = re.compile(r"\(NEEDED\).*Shared library: \[([^]]+)]")
LOADER_VALUE_RE = re.compile(r"^\s*(?:\d+:\s*)?([^:]+):\s*(\d+)(?:\s+cycles)?")


@dataclass(frozen=True)
class Probe:
    name: str
    executable: Path
    command: tuple[str, ...]
    compile_command: tuple[str, ...] | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--srcmove", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--compiler", default="clang++")
    parser.add_argument("--srcreader-lib-dir", required=True, type=Path)
    parser.add_argument("--srcml-lib-dir", required=True, type=Path)
    parser.add_argument("--warmups", type=int, default=10)
    parser.add_argument("--repetitions", type=int, default=100)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def _parse_needed(text: str) -> list[str]:
    return sorted(set(NEEDED_RE.findall(text)))


def _parse_ldd(text: str) -> list[str]:
    libraries: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("linux-vdso"):
            continue
        if "=>" in line:
            name = line.split("=>", 1)[0].strip()
        else:
            name = Path(line.split(" ", 1)[0]).name
        if name:
            libraries.add(name)
    return sorted(libraries)


def _parse_loader_statistics(text: str) -> dict[str, int]:
    wanted = {
        "total startup time in dynamic loader": "startup_cycles",
        "time needed for relocation": "relocation_cycles",
        "number of relocations": "relocations",
        "number of relocations from cache": "cached_relocations",
        "number of relative relocations": "relative_relocations",
        "time needed to load objects": "load_object_cycles",
        "final number of relocations": "final_relocations",
        "final number of relocations from cache": "final_cached_relocations",
    }
    result: dict[str, int] = {}
    for line in text.splitlines():
        match = LOADER_VALUE_RE.match(line)
        if match is None:
            continue
        label, value = match.groups()
        key = wanted.get(label.strip())
        if key is not None:
            result[key] = int(value)
    return result


def _command_output(command: list[str], *, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        check=False,
    )
    return completed.stdout


def _compile_probe(
    *, compiler: str, output: Path, library_args: list[str]
) -> tuple[str, ...]:
    command = [
        compiler,
        "-std=c++17",
        "-O2",
        "-x",
        "c++",
        "-",
        "-o",
        str(output),
        *library_args,
    ]
    subprocess.run(command, input=PROBE_SOURCE, text=True, check=True)
    return tuple(command)


def _make_probes(args: argparse.Namespace, probe_dir: Path) -> list[Probe]:
    srcreader = args.srcreader_lib_dir.resolve()
    srcml = args.srcml_lib_dir.resolve()
    rpath = f"-Wl,-rpath,{srcreader}:{srcml}"
    force_load = ["-Wl,--no-as-needed"]
    definitions = [
        ("cpp_baseline", []),
        ("libxml2", [*force_load, "-lxml2"]),
        ("libxslt", [*force_load, "-lxslt"]),
        ("libexslt", [*force_load, "-lexslt"]),
        ("libsrcml", [f"-L{srcml}", *force_load, "-lsrcml", rpath]),
        (
            "libsrcreader",
            [f"-L{srcreader}", f"-L{srcml}", *force_load, "-lsrcreader", rpath],
        ),
        (
            "full_stack",
            [
                f"-L{srcreader}",
                f"-L{srcml}",
                *force_load,
                "-lsrcreader",
                "-lsrcml",
                "-lxml2",
                rpath,
            ],
        ),
    ]

    probes: list[Probe] = []
    for name, library_args in definitions:
        executable = probe_dir / name
        compile_command = _compile_probe(
            compiler=args.compiler, output=executable, library_args=library_args
        )
        probes.append(Probe(name, executable, (str(executable),), compile_command))

    srcmove = args.srcmove.resolve()
    probes.append(
        Probe("srcmove_version", srcmove, (str(srcmove), "--version"), None)
    )
    return probes


def _observe_probe(probe: Probe) -> dict[str, Any]:
    readelf = _command_output(["readelf", "-d", str(probe.executable)])
    ldd = _command_output(["ldd", str(probe.executable)])
    env = dict(os.environ)
    env["LD_DEBUG"] = "statistics"
    loader = _command_output(list(probe.command), env=env)
    lifecycle_ns: dict[str, int] = {}
    if probe.compile_command is not None:
        init_env = dict(os.environ)
        init_env["SRCMOVE_STARTUP_REPORT_INIT"] = "1"
        init_output = _command_output(list(probe.command), env=init_env)
        for line in init_output.splitlines():
            key, separator, value = line.partition("=")
            if separator and value.isdigit():
                lifecycle_ns[key] = int(value)
    return {
        "executable": str(probe.executable),
        "sha256": _sha256(probe.executable),
        "command": list(probe.command),
        "compile_command": list(probe.compile_command)
        if probe.compile_command is not None
        else None,
        "direct_needed": _parse_needed(readelf),
        "loaded_libraries": _parse_ldd(ldd),
        "loader_statistics": _parse_loader_statistics(loader),
        "pre_main_init_ns": lifecycle_ns.get("pre_main_ns"),
        "post_main_teardown_ns": lifecycle_ns.get("post_main_ns"),
    }


def _measure(
    probes: list[Probe], warmups: int, repetitions: int
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for repetition in range(warmups + repetitions):
        offset = repetition % len(probes)
        ordered = probes[offset:] + probes[:offset]
        for position, probe in enumerate(ordered):
            usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
            started = time.perf_counter_ns()
            completed = subprocess.run(
                probe.command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
            usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
            records.append(
                {
                    "phase": "warmup" if repetition < warmups else "measured",
                    "repetition": repetition,
                    "position": position,
                    "probe": probe.name,
                    "wall_ms": elapsed_ms,
                    "user_cpu_ms": (
                        usage_after.ru_utime - usage_before.ru_utime
                    )
                    * 1_000.0,
                    "system_cpu_ms": (
                        usage_after.ru_stime - usage_before.ru_stime
                    )
                    * 1_000.0,
                    "minor_page_faults": (
                        usage_after.ru_minflt - usage_before.ru_minflt
                    ),
                    "major_page_faults": (
                        usage_after.ru_majflt - usage_before.ru_majflt
                    ),
                    "exit_code": completed.returncode,
                }
            )
    return records


def _summarize(
    probes: list[Probe],
    observations: dict[str, dict[str, Any]],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_values = [
        float(record["wall_ms"])
        for record in records
        if record["phase"] == "measured" and record["probe"] == "cpp_baseline"
    ]
    baseline = median(baseline_values)
    result: dict[str, Any] = {}
    for probe in probes:
        rows = [
            record
            for record in records
            if record["phase"] == "measured" and record["probe"] == probe.name
        ]
        values = [float(row["wall_ms"]) for row in rows]
        cpu_values = [
            float(row["user_cpu_ms"]) + float(row["system_cpu_ms"])
            for row in rows
        ]
        minor_faults = [float(row["minor_page_faults"]) for row in rows]
        probe_median = median(values)
        result[probe.name] = {
            "median_ms": probe_median,
            "p10_ms": _percentile(values, 0.10),
            "p90_ms": _percentile(values, 0.90),
            "median_cpu_ms": median(cpu_values),
            "median_minor_page_faults": median(minor_faults),
            "increment_over_cpp_ms": probe_median - baseline,
            "exit_codes": sorted({int(row["exit_code"]) for row in rows}),
            "direct_needed": observations[probe.name]["direct_needed"],
            "loaded_library_count": len(
                observations[probe.name]["loaded_libraries"]
            ),
            "loader_statistics": observations[probe.name]["loader_statistics"],
            "pre_main_init_ms": (
                observations[probe.name]["pre_main_init_ns"] / 1_000_000.0
                if observations[probe.name]["pre_main_init_ns"] is not None
                else None
            ),
            "post_main_teardown_ms": (
                observations[probe.name]["post_main_teardown_ns"] / 1_000_000.0
                if observations[probe.name]["post_main_teardown_ns"] is not None
                else None
            ),
        }
    return result


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, sort_keys=True) + "\n")


def _write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# srcMove startup dependency study",
        "",
        "Warm-cache process startup measured with rotating probe order.",
        "",
        "| Probe | Wall ms | CPU ms | Added wall ms | Minor faults | Loader cycles | Pre-main ms | Post-main ms | Libraries |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, row in summary.items():
        init_text = (
            f"{row['pre_main_init_ms']:.3f}"
            if row["pre_main_init_ms"] is not None
            else "n/a"
        )
        teardown_text = (
            f"{row['post_main_teardown_ms']:.3f}"
            if row["post_main_teardown_ms"] is not None
            else "n/a"
        )
        lines.append(
            f"| {name} | {row['median_ms']:.3f} | {row['median_cpu_ms']:.3f} | "
            f"{row['increment_over_cpp_ms']:.3f} | "
            f"{row['median_minor_page_faults']:.0f} | "
            f"{row['loader_statistics'].get('startup_cycles', 0)} | "
            f"{init_text} | {teardown_text} | {row['loaded_library_count']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    if args.warmups < 0 or args.repetitions < 3:
        raise SystemExit(
            "error: warmups must be nonnegative and repetitions at least 3"
        )
    if not args.srcmove.is_file():
        raise SystemExit(f"error: srcMove executable not found: {args.srcmove}")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    probe_dir = output_dir / "probes"
    probe_dir.mkdir()

    probes = _make_probes(args, probe_dir)
    observations = {probe.name: _observe_probe(probe) for probe in probes}
    records = _measure(probes, args.warmups, args.repetitions)
    summary = _summarize(probes, observations, records)

    manifest = {
        "schema_version": 1,
        "cache_policy": "warm_os_cache",
        "warmups": args.warmups,
        "repetitions": args.repetitions,
        "compiler": args.compiler,
        "probes": observations,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_jsonl(output_dir / "raw.jsonl", records)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_report(output_dir / "report.md", summary)
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
