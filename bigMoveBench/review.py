"""Generate deterministic AI- and human-review artifacts for Type-3 runs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from bigMoveBench.benchmark_cases import VerifiedBenchmarkCases
from bigMoveBench.evaluate import diagnostic_stage
from bigMoveBench.oracle import normalize_moved_text
from benchmarking.provenance import sha256_file


def _fragment_text(benchmark_cases: VerifiedBenchmarkCases, sha256: str) -> str:
    dataset_id = benchmark_cases.manifest["compiled_dataset"]["dataset_id"]
    path = (
        benchmark_cases.data_root
        / "bigclonebench"
        / "compiled"
        / dataset_id
        / "fragments"
        / sha256[:2]
        / f"{sha256}.java"
    )
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"compiled fragment is unavailable: {sha256}")
    contents = path.read_bytes()
    if hashlib.sha256(contents).hexdigest() != sha256:
        raise ValueError(f"compiled fragment checksum mismatch: {sha256}")
    return contents.decode("utf-8")


def _latest_attempts(journal_path: Path) -> dict[str, sqlite3.Row]:
    with sqlite3.connect(journal_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
SELECT current.*
FROM attempts AS current
WHERE current.status='terminal'
  AND NOT EXISTS (
    SELECT 1 FROM attempts AS newer
    WHERE newer.case_id=current.case_id AND newer.status='terminal'
      AND newer.attempt_ordinal > current.attempt_ordinal
  )
"""
        ).fetchall()
    return {str(row["case_id"]): row for row in rows}


def _ratio(common: int, maximum: int) -> float | None:
    return common / maximum if maximum else None


def _case_diagnosis(
    outcome: str,
    results: Mapping[str, Any],
    expected_from: str,
    expected_to: str,
) -> dict[str, Any]:
    if outcome == "oracle_pass":
        return {"stage": "selected", "reason": "expected_type3_move_selected"}
    if outcome == "wrong_classification":
        return {"stage": "classification", "reason": "wrong_match_kind"}

    diagnostics = results.get("diagnostics")
    if not isinstance(diagnostics, Mapping):
        return {
            "stage": diagnostic_stage(outcome, dict(results)),
            "reason": "diagnostics_unavailable",
        }
    candidates = diagnostics.get("candidates")
    pairs = diagnostics.get("type3_pairs")
    if not isinstance(candidates, list) or not isinstance(pairs, list):
        return {"stage": "candidate_generation", "reason": "invalid_diagnostics"}

    expected = {
        "delete": normalize_moved_text(expected_from),
        "insert": normalize_moved_text(expected_to),
    }
    matched: dict[str, list[Mapping[str, Any]]] = {"delete": [], "insert": []}
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        side = candidate.get("side")
        raw_text = candidate.get("raw_text")
        if side in matched and isinstance(raw_text, str):
            if normalize_moved_text(raw_text) == expected[side]:
                matched[side].append(candidate)

    if not matched["delete"] or not matched["insert"]:
        missing = [side for side in ("delete", "insert") if not matched[side]]
        return {
            "stage": "candidate_generation",
            "reason": "expected_candidate_missing",
            "missing_sides": missing,
            "matching_candidate_ids": {
                side: [value.get("candidate_id") for value in values]
                for side, values in matched.items()
            },
        }

    eligible = {
        side: [value for value in values if value.get("type3_eligible") is True]
        for side, values in matched.items()
    }
    if not eligible["delete"] or not eligible["insert"]:
        return {
            "stage": "candidate_eligibility",
            "reason": "expected_candidate_ineligible",
            "matching_candidates": matched,
        }

    pair_by_ids = {
        (pair.get("delete_candidate_id"), pair.get("insert_candidate_id")): pair
        for pair in pairs
        if isinstance(pair, Mapping)
    }
    matching_pairs: list[Mapping[str, Any]] = []
    same_construct = False
    size_compatible = False
    for deletion in eligible["delete"]:
        for insertion in eligible["insert"]:
            if deletion.get("construct") != insertion.get("construct"):
                continue
            same_construct = True
            line_sizes = (deletion.get("line_units"), insertion.get("line_units"))
            token_sizes = (
                deletion.get("token_units"),
                insertion.get("token_units"),
            )
            for left, right in (line_sizes, token_sizes):
                if isinstance(left, int) and isinstance(right, int) and max(left, right):
                    size_compatible |= min(left, right) * 10 >= max(left, right) * 7
            pair = pair_by_ids.get(
                (deletion.get("candidate_id"), insertion.get("candidate_id"))
            )
            if pair is not None:
                matching_pairs.append(pair)

    if not same_construct:
        return {"stage": "retrieval", "reason": "construct_kind_mismatch"}
    if not size_compatible:
        return {"stage": "retrieval", "reason": "size_window_rejected"}
    if not matching_pairs:
        return {"stage": "retrieval", "reason": "expected_pair_not_shortlisted"}

    ranked = sorted(
        matching_pairs,
        key=lambda pair: max(
            _ratio(int(pair.get("common_lines", 0)), int(pair.get("maximum_lines", 0)))
            or 0.0,
            _ratio(
                int(pair.get("common_tokens", 0)),
                int(pair.get("maximum_tokens", 0)),
            )
            or 0.0,
        ),
        reverse=True,
    )
    best = ranked[0]
    pair_outcome = str(best.get("outcome"))
    stage = {
        "below_threshold": "verification",
        "ambiguous_type2": "ambiguity",
        "selection_rejected": "selection",
        "selected": "granularity_or_oracle",
    }.get(pair_outcome, "retrieval_or_verification")
    return {
        "stage": stage,
        "reason": pair_outcome,
        "best_expected_pair": dict(best),
        "line_similarity": _ratio(
            int(best.get("common_lines", 0)), int(best.get("maximum_lines", 0))
        ),
        "token_similarity": _ratio(
            int(best.get("common_tokens", 0)), int(best.get("maximum_tokens", 0))
        ),
    }


def _fence(text: str, language: str = "java") -> str:
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text.rstrip()}\n{fence}"


def _atomic_write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_bundle(
    run_dir: Path,
    records: list[dict[str, Any]],
    attempts: Mapping[str, sqlite3.Row],
) -> dict[str, Any]:
    bundle_dir = run_dir / "type3-review"
    cases_dir = bundle_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    manifest_cases: list[dict[str, Any]] = []
    for record in records:
        attempt = attempts[record["case_id"]]
        srcdiff_attempt = run_dir / str(attempt["srcdiff_attempt_path"])
        srcmove_attempt = run_dir / str(attempt["srcmove_attempt_path"])
        srcdiff_xml = srcdiff_attempt / "srcdiff.xml"
        srcmove_xml = srcmove_attempt / "srcmove.xml"
        if not srcdiff_xml.is_file() or not srcmove_xml.is_file():
            raise ValueError(
                f"Type-3 review XML is unavailable for {record['case_id']}"
            )

        relative_dir = Path("cases") / f"{record['ordinal']:04d}"
        case_dir = bundle_dir / relative_dir
        case_dir.mkdir(parents=True, exist_ok=True)
        files = {
            "expected_source": "expected-source.java",
            "expected_destination": "expected-destination.java",
            "srcdiff_xml": "srcdiff.xml",
            "srcmove_xml": "srcmove.xml",
            "results": "results.json",
            "review": "review.json",
        }
        _atomic_write(case_dir / files["expected_source"], record["expected"]["from_text"])
        _atomic_write(
            case_dir / files["expected_destination"], record["expected"]["to_text"]
        )
        _atomic_write(case_dir / files["srcdiff_xml"], srcdiff_xml.read_text(encoding="utf-8"))
        _atomic_write(case_dir / files["srcmove_xml"], srcmove_xml.read_text(encoding="utf-8"))
        _atomic_write(
            case_dir / files["results"],
            json.dumps(record["results"], indent=2, sort_keys=True) + "\n",
        )
        _atomic_write(
            case_dir / files["review"],
            json.dumps(record, indent=2, sort_keys=True) + "\n",
        )
        manifest_cases.append(
            {
                "ordinal": record["ordinal"],
                "case_id": record["case_id"],
                "outcome": record["outcome"],
                "strength_stratum": record["strength_stratum"],
                "type3_both_similarity": record["type3_both_similarity"],
                "diagnosis": record["diagnosis"],
                "directory": relative_dir.as_posix(),
                "files": files,
            }
        )

    manifest = {"schema_version": 1, "case_count": len(records), "cases": manifest_cases}
    manifest_path = bundle_dir / "manifest.json"
    _atomic_write(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    zip_path = run_dir / "type3-review.zip"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{zip_path.name}.", dir=run_dir
    )
    os.close(descriptor)
    temporary_zip = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary_zip, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for path in sorted(bundle_dir.rglob("*")):
                if not path.is_file():
                    continue
                info = zipfile.ZipInfo(path.relative_to(bundle_dir).as_posix())
                info.date_time = (1980, 1, 1, 0, 0, 0)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, path.read_bytes())
        os.replace(temporary_zip, zip_path)
    finally:
        temporary_zip.unlink(missing_ok=True)
    return {
        "directory": {"path": bundle_dir.name},
        "manifest": {
            "path": str(manifest_path.relative_to(run_dir)),
            "sha256": sha256_file(manifest_path),
        },
        "zip": {"path": zip_path.name, "sha256": sha256_file(zip_path)},
    }


def _markdown(records: list[dict[str, Any]]) -> str:
    outcomes = Counter(str(record["outcome"]) for record in records)
    stages = Counter(str(record["diagnosis"]["stage"]) for record in records)
    lines = [
        "# BigMoveBench Type-3 review",
        "",
        "This report is derived from the canonical `type3-review.jsonl` bundle.",
        "Review whether the expected fragments represent a coherent move and whether",
        "srcMove's selected granularity and Type-3 classification are appropriate.",
        "",
        "## Summary",
        "",
        f"- Cases: {len(records)}",
        "- Outcomes: " + ", ".join(f"{key}={value}" for key, value in sorted(outcomes.items())),
        "- Diagnoses: " + ", ".join(f"{key}={value}" for key, value in sorted(stages.items())),
        "",
    ]
    ordered = sorted(records, key=lambda item: (item["outcome"] == "oracle_pass", item["ordinal"]))
    for record in ordered:
        verdict = "PASS" if record["outcome"] == "oracle_pass" else "REVIEW"
        lines.extend(
            [
                f"## Case {record['ordinal']} — {verdict} — {record['strength_stratum']}",
                "",
                f"- Case ID: `{record['case_id']}`",
                f"- Outcome: `{record['outcome']}`",
                f"- Dataset similarity: `{record['type3_both_similarity']}`",
                f"- Diagnosis: `{record['diagnosis']['stage']}` / `{record['diagnosis']['reason']}`",
                f"- Reported moves: `{record['results'].get('move_count', 0)}`",
                "- AI agrees?:",
                "- Human verdict:",
                "- Notes:",
                "",
                "### Expected source",
                "",
                _fence(record["expected"]["from_text"]),
                "",
                "### Expected destination",
                "",
                _fence(record["expected"]["to_text"]),
                "",
            ]
        )
        moves = record["results"].get("moves", [])
        if not moves:
            lines.extend(["### Actual moves", "", "No move was reported.", ""])
        for index, move in enumerate(moves, start=1):
            lines.extend(
                [
                    f"### Actual move {index}: {move.get('match_kind', 'unknown')}",
                    "",
                    (
                        f"Confidence `{move.get('confidence_milli')}`; utility "
                        f"`{move.get('selection_utility')}`; matched units "
                        f"`{move.get('matched_units')}`; reason "
                        f"`{move.get('selection_reason')}`."
                    ),
                    "",
                ]
            )
            for side in ("from", "to"):
                texts = move.get(f"{side}_raw_texts", [])
                for text_index, text in enumerate(texts, start=1):
                    lines.extend(
                        [
                            f"#### {side.title()} text {text_index}",
                            "",
                            _fence(str(text)),
                            "",
                        ]
                    )
    return "\n".join(lines).rstrip() + "\n"


def write_type3_review(
    run_dir: Path,
    *,
    journal_path: Path,
    benchmark_cases: VerifiedBenchmarkCases,
) -> dict[str, Any]:
    attempts = _latest_attempts(journal_path)
    database = benchmark_cases.directory / "benchmark_cases.sqlite"
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        cases = connection.execute(
            "SELECT * FROM cases WHERE pair_set='type3' ORDER BY ordinal"
        ).fetchall()

    records: list[dict[str, Any]] = []
    for case in cases:
        attempt = attempts.get(str(case["case_id"]))
        if attempt is None:
            raise ValueError(f"Type-3 case has no terminal attempt: {case['case_id']}")
        expected_from = _fragment_text(
            benchmark_cases, str(case["original_fragment_sha256"])
        )
        expected_to = _fragment_text(
            benchmark_cases, str(case["modified_fragment_sha256"])
        )
        results = json.loads(attempt["oracle_results_json"] or "{}")
        outcome = str(attempt["outcome"])
        records.append(
            {
                "schema_version": 1,
                "ordinal": int(case["ordinal"]),
                "case_id": str(case["case_id"]),
                "outcome": outcome,
                "diagnostic_stage": results.get(
                    "_oracle_diagnostic_stage", diagnostic_stage(outcome, results)
                ),
                "strength_stratum": case["type3_strength_stratum"],
                "type3_both_similarity": case["type3_both_similarity"],
                "min_tokens": case["min_tokens"],
                "functionality_id": case["representative_functionality_id"],
                "function_id_one": case["representative_function_id_one"],
                "function_id_two": case["representative_function_id_two"],
                "expected": {
                    "match_kind": case["expected_match_kind"],
                    "from_sha256": case["original_fragment_sha256"],
                    "to_sha256": case["modified_fragment_sha256"],
                    "from_lines": [case["from_start_line"], case["from_end_line"]],
                    "to_lines": [case["to_start_line"], case["to_end_line"]],
                    "from_text": expected_from,
                    "to_text": expected_to,
                },
                "diagnosis": _case_diagnosis(
                    outcome, results, expected_from, expected_to
                ),
                "oracle_failures": json.loads(attempt["oracle_failures_json"] or "[]"),
                "text_validation": json.loads(attempt["text_validation_json"] or "{}"),
                "results": results,
                "review": {"ai_agrees": None, "human_verdict": None, "notes": None},
            }
        )

    jsonl_path = run_dir / "type3-review.jsonl"
    markdown_path = run_dir / "type3-review.md"
    _atomic_write(
        jsonl_path,
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
    )
    _atomic_write(markdown_path, _markdown(records))
    return {
        "case_count": len(records),
        "jsonl": {"path": jsonl_path.name, "sha256": sha256_file(jsonl_path)},
        "markdown": {
            "path": markdown_path.name,
            "sha256": sha256_file(markdown_path),
        },
        "bundle": _write_bundle(run_dir, records, attempts),
    }
