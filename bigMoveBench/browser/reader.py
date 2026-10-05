"""Read-only, versioned projections of retained thesis benchmark runs.

Kept outside construction/execution modules so prepared experiment source
identities are unaffected. Uses only the standard library; never runs tools.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import shutil
import tempfile

CATEGORIES = ("type1", "type2b", "type2c", "type3", "known-false-positive")
SCHEMA_VERSION = 1


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Benchmark reference escapes its configured root.")
    return path


def _run(results_root, run_id):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,199}", run_id):
        raise ValueError("Invalid benchmark run ID.")
    directory = _inside(results_root, run_id)
    if not (directory / "summary.json").is_file():
        raise FileNotFoundError("Benchmark run is unavailable.")
    summary = _json(directory / "summary.json")
    if summary.get("schema_version") != 1 or not isinstance(summary.get("member_summaries"), list):
        raise ValueError("Unsupported thesis benchmark run summary.")
    if summary.get("status") != "completed" and summary.get("status") != "completed_with_tool_or_oracle_failures":
        raise ValueError("Only completed thesis runs can be browsed.")
    members = [item["pair_set"] for item in summary["member_summaries"]]
    if len(set(members)) != len(members) or any(member not in CATEGORIES for member in members):
        raise ValueError("Invalid benchmark member categories.")
    return directory, summary


def show_run(results_root: Path, run_id: str):
    _, summary = _run(results_root, run_id)
    return {"schema_version": SCHEMA_VERSION, "run_id": run_id, **summary}


def list_runs(results_root: Path):
    items = []
    if results_root.is_dir():
        for directory in results_root.iterdir():
            if not directory.is_dir() or not (directory / "summary.json").is_file():
                continue
            if _json(directory / "summary.json").get("status") not in {
                "completed", "completed_with_tool_or_oracle_failures"
            }:
                continue
            _, summary = _run(results_root, directory.name)
            items.append({
                "run_id": directory.name,
                "completed_at": summary.get("completed_at"),
                "selected": summary["selected"],
                "status": summary["status"],
                "experiment_id": summary["experiment_id"],
            })
    items.sort(key=lambda item: (item["completed_at"] or "", item["run_id"]), reverse=True)
    return {"schema_version": SCHEMA_VERSION, "items": items,
            "default_run_id": items[0]["run_id"] if items else None}


@contextmanager
def _member(directory, category, cache_root):
    journal = _inside(directory, f"{category}/execution.sqlite")
    if not journal.is_file():
        raise FileNotFoundError("Benchmark execution journal is unavailable.")
    # Completed journals may lack an SHM file after another reader closes.
    # A private snapshot lets SQLite recover committed WAL pages without
    # creating sidecars in the read-only evidence directory.
    with tempfile.TemporaryDirectory(prefix="bmb-browser-") as temporary:
        snapshot = Path(temporary) / journal.name
        shutil.copyfile(journal, snapshot)
        wal = journal.with_name(journal.name + "-wal")
        if wal.is_file():
            shutil.copyfile(wal, snapshot.with_name(snapshot.name + "-wal"))
        with closing(sqlite3.connect(snapshot)) as connection:
            yield from _member_connection(connection, cache_root)


def _member_connection(connection, cache_root):
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    metadata = connection.execute("SELECT * FROM run_metadata WHERE singleton=1").fetchone()
    if metadata is None or metadata["schema_version"] != 1:
        raise ValueError("Unsupported benchmark execution journal.")
    identifier = metadata["benchmark_cases_id"]
    if not re.fullmatch(r"bmb-benchmark-cases-sha256-[0-9a-f]{64}", identifier):
        raise ValueError("Invalid benchmark case collection identity.")
    case_directory = _inside(cache_root, f"benchmark-cases/{identifier}")
    manifest_path = case_directory / "manifest.json"
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != metadata["benchmark_cases_manifest_sha256"]:
        raise ValueError("Benchmark case manifest differs from the recorded run.")
    manifest = _json(manifest_path)
    if manifest.get("schema_version") != 1 or manifest.get("benchmark_cases_id") != identifier:
        raise ValueError("Unsupported benchmark case collection.")
    database = case_directory / "benchmark_cases.sqlite"
    declared = manifest["artifacts"]["benchmark_cases"]
    if declared.get("path") != database.name or database.stat().st_size != declared["size_bytes"]:
        raise ValueError("Benchmark case database declaration differs.")
    connection.execute("ATTACH DATABASE ? AS definitions", (database.as_uri() + "?mode=ro&immutable=1",))
    yield connection, manifest


# One row per test definition, using its latest committed terminal attempt.
_FROM = """
FROM definitions.cases AS c
LEFT JOIN attempts AS a ON a.case_id=c.case_id AND a.status='terminal'
AND NOT EXISTS (
    SELECT 1 FROM attempts AS newer WHERE newer.case_id=a.case_id
    AND newer.status='terminal' AND newer.attempt_ordinal > a.attempt_ordinal
)
"""
_OUTCOME = "coalesce(a.outcome, 'not_executed')"
_REVIEWED = "coalesce(json_extract(a.oracle_results_json, '$._oracle_reviewed_outcome'), a.outcome, 'not_executed')"
_OBSERVED = """coalesce(json_extract(a.oracle_results_json, '$._oracle_observed_match_kind'),
CASE WHEN json_array_length(a.oracle_results_json, '$.moves')=1
THEN json_extract(a.oracle_results_json, '$.moves[0].match_kind') END)"""
_FIELDS = f"""
c.case_id, c.ordinal, c.case_kind, c.expected_match_kind,
c.type3_both_similarity, c.type3_strength_stratum, c.min_tokens,
{_OUTCOME} AS outcome, {_REVIEWED} AS reviewed_outcome,
{_OBSERVED} AS observed_match_kind,
coalesce(json_extract(a.oracle_results_json, '$._oracle_label_correction.reviewed_match_kind'), c.expected_match_kind) AS reviewed_expected_match_kind,
json_extract(a.oracle_results_json, '$._oracle_label_correction.id') AS label_correction_id,
json_extract(a.oracle_results_json, '$.move_count') AS move_count,
json_extract(a.oracle_results_json, '$._oracle_diagnostic_stage') AS diagnostic_stage,
a.semantic_status, json_extract(a.semantic_details_json, '$.reason') AS semantic_reason,
a.attempt_id, a.attempt_ordinal
"""


def _case_summary(row, category):
    result = dict(row)
    result["category"] = category
    result["complete_fragment_detected"] = (
        result["outcome"] in {"oracle_pass", "wrong_classification"}
        if result["case_kind"] == "positive" and result["outcome"] != "not_executed" else None
    )
    return result


def list_cases(results_root: Path, cache_root: Path, run_id: str, *, category="", outcome="", basis="original", offset=0, limit=50, query=""):
    if category and category not in CATEGORIES:
        raise ValueError("Unknown benchmark category.")
    if basis not in {"original", "reviewed"} or offset < 0 or not 1 <= limit <= 100 or len(query) > 200:
        raise ValueError("Invalid benchmark filter or page.")
    directory, summary = _run(results_root, run_id)
    members = [item["pair_set"] for item in summary["member_summaries"]]
    clauses, parameters = [], []
    if outcome:
        clauses.append(f"{_REVIEWED if basis == 'reviewed' else _OUTCOME}=?")
        parameters.append(outcome)
    if query:
        clauses.append("(instr(lower(c.case_id), lower(?))>0 OR instr(lower(coalesce(a.oracle_failures_json,'')),lower(?))>0)")
        parameters.extend([query, query])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    matched, total, items, remaining_offset = 0, 0, [], offset
    outcomes = set()
    for member in members:
        with _member(directory, member, cache_root) as (connection, _):
            total += connection.execute("SELECT count(*) FROM definitions.cases").fetchone()[0]
            outcomes.update(row[0] for row in connection.execute(f"SELECT DISTINCT {_REVIEWED if basis == 'reviewed' else _OUTCOME} {_FROM}"))
            if category and member != category:
                continue
            count = connection.execute(f"SELECT count(*) {_FROM} {where}", parameters).fetchone()[0]
            matched += count
            if remaining_offset >= count:
                remaining_offset -= count
                continue
            capacity = limit - len(items)
            if capacity:
                rows = connection.execute(f"SELECT {_FIELDS} {_FROM} {where} ORDER BY c.ordinal LIMIT ? OFFSET ?", [*parameters, capacity, remaining_offset])
                items.extend(_case_summary(row, member) for row in rows)
            remaining_offset = 0
    return {"schema_version": SCHEMA_VERSION, "run_id": run_id, "items": items,
            "total": total, "matched": matched, "offset": offset,
            "next_offset": offset + limit if offset + limit < matched else None,
            "filters": {"categories": members, "outcomes": sorted(outcomes)}}


def _fragment(cache_root, manifest, digest):
    dataset = manifest["compiled_dataset"]["dataset_id"]
    if not re.fullmatch(r"bcb-dataset-sha256-[0-9a-f]{64}", dataset) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid fragment identity.")
    path = _inside(cache_root, f"bigclonebench/compiled/{dataset}/fragments/{digest[:2]}/{digest}.java")
    if not path.is_file():
        return {"sha256": digest, "text": None, "reason": "The original fragment is unavailable."}
    contents = path.read_bytes()
    if hashlib.sha256(contents).hexdigest() != digest:
        raise ValueError("Benchmark fragment checksum differs from its identity.")
    return {"sha256": digest, "text": contents.decode("utf-8"), "reason": None}


def show_case(results_root: Path, cache_root: Path, run_id: str, category: str, case_id: str):
    directory, summary = _run(results_root, run_id)
    if category not in [item["pair_set"] for item in summary["member_summaries"]]:
        raise ValueError("Unknown benchmark category.")
    with _member(directory, category, cache_root) as (connection, manifest):
        row = connection.execute(f"SELECT {_FIELDS} {_FROM} WHERE c.case_id=?", (case_id,)).fetchone()
        if row is None:
            raise FileNotFoundError("Benchmark case is unavailable.")
        case = dict(connection.execute("SELECT * FROM definitions.cases WHERE case_id=?", (case_id,)).fetchone())
        attempt = connection.execute("SELECT * FROM attempts WHERE attempt_id=?", (row["attempt_id"],)).fetchone()
        def retained(key, default):
            return json.loads(attempt[key] or json.dumps(default)) if attempt else default
        results = retained("oracle_results_json", {})
        return {
            "schema_version": SCHEMA_VERSION, "run_id": run_id,
            "case": _case_summary(row, category),
            "original": _fragment(cache_root, manifest, case["original_fragment_sha256"]),
            "modified": _fragment(cache_root, manifest, case["modified_fragment_sha256"]),
            "expected_ranges": {"from": [case["from_start_line"], case["from_end_line"]], "to": [case["to_start_line"], case["to_end_line"]]},
            "failures": retained("oracle_failures_json", []),
            "reviewed_failures": results.get("_oracle_reviewed_failures", retained("oracle_failures_json", [])),
            "label_correction": results.get("_oracle_label_correction"),
            "semantic_details": retained("semantic_details_json", {}),
            "text_validation": retained("text_validation_json", {}),
            "moves": results.get("moves", []),
            "match_kinds": results.get("match_kinds", {}),
            "diagnostics": results.get("diagnostics"),
            "results_available": bool(attempt and attempt["oracle_results_json"]),
            "tool_sha256": summary.get("tool_sha256", {}),
        }


def show_source(results_root: Path, cache_root: Path, run_id: str, category: str, case_id: str):
    """Return the exact retained positioned input and its scored move results."""
    directory, summary = _run(results_root, run_id)
    if category not in [item["pair_set"] for item in summary["member_summaries"]]:
        raise ValueError("Unknown benchmark category.")
    with _member(directory, category, cache_root) as (connection, _):
        row = connection.execute(f"SELECT {_FIELDS} {_FROM} WHERE c.case_id=?", (case_id,)).fetchone()
        if row is None:
            raise FileNotFoundError("Benchmark case is unavailable.")
        attempt = connection.execute("SELECT * FROM attempts WHERE attempt_id=?", (row["attempt_id"],)).fetchone()
        if not attempt or not attempt["oracle_results_json"] or not attempt["srcdiff_admitted"]:
            raise ValueError("Source view requires retained srcDiff input and completed srcMove results.")
        record = json.loads(attempt["srcdiff_record_json"])
        path = _inside(directory / category, attempt["srcdiff_attempt_path"] + "/srcdiff.xml")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != record["xml"]["sha256"]:
            raise ValueError("Retained srcDiff input checksum differs from the recorded attempt.")
        return {"schema_version": SCHEMA_VERSION, "run_id": run_id,
                "case": _case_summary(row, category), "srcdiff_xml": payload.decode("utf-8"),
                "results": json.loads(attempt["oracle_results_json"]),
                "tool_sha256": summary.get("tool_sha256", {})}
