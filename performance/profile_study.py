#!/usr/bin/env python3
"""Capture a focused srcMove profiler study as JSONL plus median summaries."""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from pathlib import Path
from statistics import median
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarking.contracts import RunMode
from benchmarking.storage import write_json_atomic
from performance.benchmark import load_workloads, run_performance


INTEGER_FIELDS = {
    "sequence",
    "repetition",
    "position_in_pair",
    "exit_code",
    "peak_rss_bytes",
    "workload_size_bytes",
    "workload_xml_element_count",
    "workload_srcml_unit_count",
    "workload_diff_delete_region_count",
    "workload_diff_insert_region_count",
    "workload_diff_region_count",
}
FLOAT_FIELDS = {
    "wall_seconds",
    "cpu_user_seconds",
    "cpu_system_seconds",
    "cpu_total_seconds",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--srcmove", required=True, type=Path)
    parser.add_argument("--workload", required=True, action="append")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args()


def _number(key: str, value: str) -> Any:
    if value == "":
        return None
    if key in INTEGER_FIELDS or (
        key.startswith("internal_") and not key.endswith("_ms")
    ):
        return int(value)
    if key in FLOAT_FIELDS or key.endswith("_ms"):
        return float(value)
    return value


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _load_records(run_dir: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    executable = manifest["observation"]["executables"]["current"]
    source = executable.get("receipt", {}).get("sources", {}).get("srcMove", {})
    records: list[dict[str, Any]] = []
    with (run_dir / "raw.csv").open(encoding="utf-8", newline="") as stream:
        for raw in csv.DictReader(stream):
            record = {key: _number(key, value) for key, value in raw.items()}
            attempt_dir = run_dir / str(record["attempt_path"])
            attempt = json.loads((attempt_dir / "attempt.json").read_text())
            results = json.loads((attempt_dir / "results.json").read_text())
            record.update(
                {
                    "executable_sha256": executable["artifact"]["sha256"],
                    "source_commit": source.get("commit"),
                    "output_size_bytes": attempt.get("xml", {}).get("size_bytes"),
                    "regions_total": results.get("regions_total"),
                    "candidates_total": results.get("candidates_total"),
                    "groups_total": results.get("groups_total"),
                    "move_group_count": results.get("move_group_count"),
                    "match_kinds": results.get("match_kinds", {}),
                }
            )
            records.append(record)
    return records


def _result_medians(records: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    workloads = sorted({str(record["workload"]) for record in records})
    for workload in workloads:
        rows = [
            record
            for record in records
            if record["phase"] == "measured"
            and record["status"] == "success"
            and record["workload"] == workload
        ]
        result[workload] = {}
        for key in (
            "regions_total",
            "candidates_total",
            "groups_total",
            "move_group_count",
            "output_size_bytes",
        ):
            values = [row[key] for row in rows if row.get(key) is not None]
            result[workload][key] = median(values) if values else None
        result[workload]["match_kinds"] = rows[0].get("match_kinds", {}) if rows else {}
    return result


def _report(summary: dict[str, Any], results: dict[str, Any]) -> str:
    workloads = summary["variants"]["current"]["workloads"]
    metric_names = (
        "wall_seconds",
        "peak_rss_bytes",
        "internal_pipeline.total_ms",
        "internal_pipeline.parse_regions_ms",
        "internal_pipeline.filter_candidates_ms",
        "internal_pipeline.registry_ms",
        "internal_pipeline.content_groups_ms",
        "internal_pipeline.annotation_ms",
        "internal_pipeline.summary_ms",
        "internal_annotation.copy_unmodified_ms",
        "internal_annotation.patch_tagged_ms",
        "internal_content_groups.type3_build_ms",
    )
    lines = ["# srcMove focused profiling study", ""]
    for name in sorted(workloads):
        metrics = workloads[name]["metrics"]
        lines.extend([f"## {name}", ""])
        for metric_name in metric_names:
            metric = metrics.get(metric_name)
            if metric is not None:
                lines.append(f"- `{metric_name}` median: {metric['median']}")
        counts = results[name]
        lines.append(
            "- result counts: "
            f"regions={counts['regions_total']}, candidates={counts['candidates_total']}, "
            f"groups={counts['groups_total']}, moves={counts['move_group_count']}, "
            f"match_kinds={json.dumps(counts['match_kinds'], sort_keys=True)}"
        )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ("manifest.json", "raw.jsonl", "summary.json", "report.md"):
        if (output_dir / name).exists():
            raise FileExistsError(f"study artifact already exists: {output_dir / name}")

    run_dir, manifest, summary = run_performance(
        output_root=output_dir / "capture",
        variants={"current": args.srcmove.expanduser().resolve()},
        workloads=load_workloads(args.workload),
        warmups=args.warmups,
        repetitions=args.repetitions,
        seed=args.seed,
        timeout_seconds=300.0,
        cache_policy="warm_os_cache",
        mode=RunMode.DEVELOPMENT,
        run_id=args.run_id,
    )
    records = _load_records(run_dir, manifest)
    result_medians = _result_medians(records)
    study_summary = {**summary, "result_medians": result_medians}
    study_manifest = {
        **manifest,
        "study_artifacts": {
            "raw_jsonl": "raw.jsonl",
            "summary": "summary.json",
            "report": "report.md",
            "capture_run": str(run_dir.relative_to(output_dir)),
        },
    }
    write_json_atomic(output_dir / "manifest.json", study_manifest)
    _write_jsonl(output_dir / "raw.jsonl", records)
    write_json_atomic(output_dir / "summary.json", study_summary)
    (output_dir / "report.md").write_text(
        _report(study_summary, result_medians), encoding="utf-8"
    )
    print(output_dir)
    return 1 if summary["counts"]["measured_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
