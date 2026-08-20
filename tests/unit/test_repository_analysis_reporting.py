from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import repository_analysis.reporting as reporting_module
from repository_analysis import (
    CaptureObservation,
    PairOutcome,
    PairReceiptPublisher,
    PairStatus,
    PairWorkItem,
    ProcessOutcome,
    VerifiedArtifact,
    RetentionPolicy,
    pair_receipt,
)


def work_item(sequence: int) -> PairWorkItem:
    return PairWorkItem(
        sequence=sequence,
        old_commit=f"old-{sequence}",
        new_commit=f"new-{sequence}",
        fingerprint=f"fingerprint-{sequence}",
    )


def capture(path: Path | None = None) -> CaptureObservation:
    return CaptureObservation(
        path=path,
        total_bytes=3,
        retained_bytes=3,
        omitted_bytes=0,
        truncated=False,
        sha256="capture-checksum",
    )


def failed_process(root: Path, artifact: VerifiedArtifact) -> ProcessOutcome:
    return ProcessOutcome(
        command=("srcdiff", "old", "new"),
        working_directory=root,
        started_at="2026-08-20T00:00:00+00:00",
        completed_at="2026-08-20T00:00:01+00:00",
        elapsed_seconds=1.0,
        termination_status="exited",
        exit_code=0,
        signal_number=None,
        timed_out=False,
        spawn_error=None,
        cleanup_signals=(),
        process_group_cleaned=True,
        stdout=capture(root / "stdout.bin"),
        stderr=capture(),
        peak_rss_bytes=1024,
        oom_kill_observed=False,
        output_artifact=artifact,
        validation_error="archive output must contain child units",
    )


def file_artifact(path: Path, *, kind: str, stage: str) -> VerifiedArtifact:
    content = path.read_bytes()
    return VerifiedArtifact(
        path=path,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        kind=kind,
        validation_status="valid",
        producing_stage=stage,
    )


def completed_outcome(
    root: Path,
    sequence: int,
    *,
    metrics: tuple[tuple[str, int], ...] = (),
    timings: tuple[tuple[str, float], ...] = (),
) -> PairOutcome:
    normalized = {
        "move_count": 0,
        "move_group_count": 0,
        "move_pair_count": 0,
        "annotated_region_count": 0,
    }
    normalized.update(metrics)
    worker = root / f"worker-{sequence}"
    worker.mkdir(exist_ok=True)
    results = worker / "results.json"
    results.write_text(json.dumps(normalized) + "\n", encoding="utf-8")
    return PairOutcome(
        work_item=work_item(sequence),
        status=PairStatus.COMPLETED,
        artifacts=(
            file_artifact(results, kind="json_results", stage="srcmove"),
        ),
        metrics=tuple(normalized.items()),
        timings=timings,
    )


class PairReceiptTests(unittest.TestCase):
    def test_failure_receipt_preserves_process_and_artifact_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            artifact = VerifiedArtifact(
                path=root / "srcdiff.xml",
                size_bytes=12,
                sha256="artifact-checksum",
                kind="xml",
                validation_status="invalid_structure",
                producing_stage="srcdiff",
                producing_command=("srcdiff", "old", "new"),
                shape="archive",
                details=(("error", "empty archive"),),
            )
            outcome = PairOutcome(
                work_item=work_item(0),
                status=PairStatus.SRCDIFF_FAILED,
                srcdiff_process=failed_process(root, artifact),
                artifacts=(artifact,),
                error="srcDiff artifact validation failed",
            )

            receipt = pair_receipt(outcome)

            self.assertEqual(receipt["status"], "srcdiff_failed")
            self.assertEqual(receipt["pair_fingerprint"], "fingerprint-0")
            self.assertEqual(
                receipt["srcdiff_process"]["termination_status"], "exited"
            )
            self.assertTrue(receipt["srcdiff_process"]["process_group_cleaned"])
            self.assertEqual(
                receipt["srcdiff_process"]["output_artifact"]["validation_status"],
                "invalid_structure",
            )
            self.assertEqual(receipt["artifacts"][0]["sha256"], "artifact-checksum")

    def test_publisher_writes_ordered_atomic_receipts_and_constant_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            publisher = PairReceiptPublisher(root)
            outcomes = (
                completed_outcome(
                    root,
                    0,
                    metrics=(
                        ("move_count", 1),
                        ("move_group_count", 1),
                        ("move_pair_count", 2),
                        ("annotated_region_count", 3),
                    ),
                    timings=(("pair_seconds", 1.25),),
                ),
                PairOutcome(
                    work_item=work_item(1),
                    status=PairStatus.NO_ANALYZABLE_CHANGE,
                    timings=(("pair_seconds", 0.25),),
                ),
                PairOutcome(
                    work_item=work_item(2),
                    status=PairStatus.SRCDIFF_FAILED,
                    timings=(("pair_seconds", 0.5),),
                ),
            )

            for outcome in outcomes:
                publisher(outcome)

            receipts = sorted((root / "pairs").glob("*.json"))
            self.assertEqual(
                [path.name for path in receipts],
                ["000000.json", "000001.json", "000002.json"],
            )
            self.assertEqual(
                [json.loads(path.read_text())["sequence"] for path in receipts],
                [0, 1, 2],
            )
            self.assertEqual(list((root / "pairs").glob(".*.tmp-*")), [])
            self.assertEqual(
                publisher.summary(),
                {
                    "schema_version": 1,
                    "selected_pairs": 3,
                    "completed": 1,
                    "no_analyzable_change": 1,
                    "failed": 1,
                    "statuses": {
                        "completed": 1,
                        "no_analyzable_change": 1,
                        "srcdiff_failed": 1,
                    },
                    "move_count": 1,
                    "move_group_count": 1,
                    "move_pair_count": 2,
                    "annotated_region_count": 3,
                    "timings": {"pair_seconds": 2.0},
                },
            )

    def test_publisher_rejects_out_of_order_or_duplicate_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            publisher = PairReceiptPublisher(Path(temporary_directory))
            second = PairOutcome(
                work_item=work_item(1), status=PairStatus.COMPLETED
            )
            with self.assertRaisesRegex(ValueError, "expected 0, got 1"):
                publisher(second)

            first = completed_outcome(Path(temporary_directory), 0)
            publisher(first)
            with self.assertRaisesRegex(ValueError, "expected 1, got 0"):
                publisher(first)

    def test_existing_receipt_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pairs = root / "pairs"
            pairs.mkdir()
            destination = pairs / "000000.json"
            destination.write_text('{"existing":true}\n', encoding="utf-8")
            publisher = PairReceiptPublisher(root)

            with self.assertRaises(FileExistsError):
                publisher(
                    PairOutcome(
                        work_item=work_item(0), status=PairStatus.COMPLETED
                    )
                )

            self.assertEqual(destination.read_text(), '{"existing":true}\n')
            with self.assertRaisesRegex(ValueError, "unsupported pair receipt schema"):
                publisher.summary()

    def test_zero_move_seal_retains_results_but_discards_xml(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            worker = root / "worker"
            worker.mkdir()
            srcdiff_xml = worker / "srcdiff.xml"
            srcdiff_xml.write_text("<unit/>", encoding="utf-8")
            srcmove_xml = worker / "srcmove.xml"
            srcmove_xml.write_text("<unit/>", encoding="utf-8")
            results = worker / "results.json"
            results.write_text(
                '{"move_count":0,"move_group_count":0,'
                '"move_pair_count":0,"annotated_region_count":0}\n',
                encoding="utf-8",
            )
            outcome = PairOutcome(
                work_item=work_item(0),
                status=PairStatus.COMPLETED,
                artifacts=(
                    file_artifact(srcdiff_xml, kind="xml", stage="srcdiff"),
                    file_artifact(srcmove_xml, kind="xml", stage="srcmove"),
                    file_artifact(results, kind="json_results", stage="srcmove"),
                ),
                metrics=(
                    ("move_count", 0),
                    ("move_group_count", 0),
                    ("move_pair_count", 0),
                    ("annotated_region_count", 0),
                ),
            )

            PairReceiptPublisher(root)(outcome)

            receipt_path = root / "pairs" / "000000.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertTrue(receipt["sealed"])
            self.assertEqual(receipt["schema_version"], 2)
            records = {entry["kind"]: entry for entry in receipt["artifacts"]}
            self.assertIsNone(records["xml"]["path"])
            self.assertEqual(records["xml"]["retention"], "not_retained")
            retained_path = root / records["json_results"]["path"]
            self.assertEqual(retained_path.read_bytes(), results.read_bytes())
            self.assertEqual(records["json_results"]["retention"], "analysis_owned")
            self.assertNotIn(str(worker), receipt_path.read_text(encoding="utf-8"))

    def test_positive_xml_retention_is_explicit_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            worker = root / "worker"
            worker.mkdir()
            srcdiff_xml = worker / "srcdiff.xml"
            srcdiff_xml.write_text("<unit/>", encoding="utf-8")
            srcmove_xml = worker / "srcmove.xml"
            srcmove_xml.write_text("<unit/>", encoding="utf-8")
            results = worker / "results.json"
            results.write_text(
                '{"move_count":1,"move_group_count":1,'
                '"move_pair_count":1,"annotated_region_count":2}\n',
                encoding="utf-8",
            )
            outcome = PairOutcome(
                work_item=work_item(0),
                status=PairStatus.COMPLETED,
                artifacts=(
                    file_artifact(srcdiff_xml, kind="xml", stage="srcdiff"),
                    file_artifact(srcmove_xml, kind="xml", stage="srcmove"),
                    file_artifact(results, kind="json_results", stage="srcmove"),
                ),
                metrics=(
                    ("move_count", 1),
                    ("move_group_count", 1),
                    ("move_pair_count", 1),
                    ("annotated_region_count", 2),
                ),
            )
            publisher = PairReceiptPublisher(
                root,
                retention_policy=RetentionPolicy(retain_positive_xml=True),
            )

            publisher(outcome)

            receipt = json.loads(
                (root / "pairs" / "000000.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                receipt["retention_policy"]["completed_positive"],
                "results_and_xml",
            )
            self.assertTrue(
                all(entry["path"] is not None for entry in receipt["artifacts"])
            )

    def test_positive_xml_policy_requires_both_tool_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            worker = root / "worker"
            worker.mkdir()
            srcmove_xml = worker / "srcmove.xml"
            srcmove_xml.write_text("<unit/>", encoding="utf-8")
            results = worker / "results.json"
            results.write_text(
                '{"move_count":1,"move_group_count":1,'
                '"move_pair_count":1,"annotated_region_count":2}\n',
                encoding="utf-8",
            )
            outcome = PairOutcome(
                work_item=work_item(0),
                status=PairStatus.COMPLETED,
                artifacts=(
                    file_artifact(srcmove_xml, kind="xml", stage="srcmove"),
                    file_artifact(results, kind="json_results", stage="srcmove"),
                ),
                metrics=(
                    ("move_count", 1),
                    ("move_group_count", 1),
                    ("move_pair_count", 1),
                    ("annotated_region_count", 2),
                ),
            )

            with self.assertRaisesRegex(ValueError, "srcDiff and srcMove XML"):
                PairReceiptPublisher(
                    root,
                    retention_policy=RetentionPolicy(retain_positive_xml=True),
                )(outcome)

            self.assertFalse((root / "pairs" / "000000").exists())

    def test_failed_seal_retains_partial_output_and_bounded_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            worker = root / "worker"
            worker.mkdir()
            partial = worker / "srcdiff.xml"
            partial.write_bytes(b"partial xml")
            stdout = worker / "srcdiff.stdout.bin"
            stdout.write_bytes(b"bounded log")
            artifact = file_artifact(partial, kind="xml", stage="srcdiff")
            process = failed_process(worker, artifact)
            process = replace(
                process,
                stdout=CaptureObservation(
                    path=stdout,
                    total_bytes=len(stdout.read_bytes()),
                    retained_bytes=len(stdout.read_bytes()),
                    omitted_bytes=0,
                    truncated=False,
                    sha256=hashlib.sha256(stdout.read_bytes()).hexdigest(),
                ),
            )
            outcome = PairOutcome(
                work_item=work_item(0),
                status=PairStatus.SRCDIFF_FAILED,
                srcdiff_process=process,
                artifacts=(artifact,),
            )

            PairReceiptPublisher(root)(outcome)

            receipt = json.loads(
                (root / "pairs" / "000000.json").read_text(encoding="utf-8")
            )
            artifact_record = receipt["artifacts"][0]
            capture_record = receipt["srcdiff_process"]["stdout"]
            self.assertEqual(
                (root / artifact_record["path"]).read_bytes(), b"partial xml"
            )
            self.assertEqual(
                (root / capture_record["path"]).read_bytes(), b"bounded log"
            )
            self.assertEqual(
                capture_record["retained_sha256"],
                hashlib.sha256(b"bounded log").hexdigest(),
            )

    def test_sealing_refuses_symlinked_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "analysis"
            root.mkdir()
            outside = Path(temporary_directory) / "outside-results.json"
            outside.write_text('{"move_count":0}\n', encoding="utf-8")
            worker = root / "worker"
            worker.mkdir()
            linked = worker / "results.json"
            linked.symlink_to(outside)
            content = outside.read_bytes()
            artifact = VerifiedArtifact(
                path=linked,
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                kind="json_results",
                validation_status="valid",
                producing_stage="srcmove",
            )

            with self.assertRaisesRegex(ValueError, "symbolic link"):
                PairReceiptPublisher(root)(
                    PairOutcome(
                        work_item=work_item(0),
                        status=PairStatus.COMPLETED,
                        artifacts=(artifact,),
                        metrics=(
                            ("move_count", 0),
                            ("move_group_count", 0),
                            ("move_pair_count", 0),
                            ("annotated_region_count", 0),
                        ),
                    )
                )

            self.assertFalse((root / "pairs" / "000000.json").exists())
            self.assertTrue(outside.exists())

    def test_completed_seal_requires_results_and_complete_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            publisher = PairReceiptPublisher(root)
            metrics = (
                ("move_count", 0),
                ("move_group_count", 0),
                ("move_pair_count", 0),
                ("annotated_region_count", 0),
            )

            with self.assertRaisesRegex(ValueError, "one valid results.json"):
                publisher(
                    PairOutcome(
                        work_item=work_item(0),
                        status=PairStatus.COMPLETED,
                        metrics=metrics,
                    )
                )

            self.assertFalse((root / "pairs" / "000000.json").exists())
            self.assertFalse((root / "pairs" / "000000").exists())
            publisher(completed_outcome(root, 0))
            self.assertTrue((root / "pairs" / "000000.json").is_file())

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            worker = root / "worker"
            worker.mkdir()
            results = worker / "results.json"
            results.write_text('{"move_count":0}\n', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "missing metric"):
                PairReceiptPublisher(root)(
                    PairOutcome(
                        work_item=work_item(0),
                        status=PairStatus.COMPLETED,
                        artifacts=(
                            file_artifact(
                                results, kind="json_results", stage="srcmove"
                            ),
                        ),
                        metrics=(("move_count", 0),),
                    )
                )

            self.assertFalse((root / "pairs" / "000000.json").exists())
            self.assertFalse((root / "pairs" / "000000").exists())

    def test_finalization_rebuilds_aggregate_and_chronological_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            publisher = PairReceiptPublisher(root)
            outcomes = (
                completed_outcome(
                    root,
                    0,
                    metrics=(
                        ("move_count", 2),
                        ("move_group_count", 1),
                        ("move_pair_count", 2),
                        ("annotated_region_count", 3),
                    ),
                    timings=(("pair_seconds", 1.0),),
                ),
                PairOutcome(
                    work_item=work_item(1),
                    status=PairStatus.NO_ANALYZABLE_CHANGE,
                    timings=(("pair_seconds", 0.25),),
                ),
                PairOutcome(
                    work_item=work_item(2),
                    status=PairStatus.SRCDIFF_FAILED,
                    timings=(("pair_seconds", 0.5),),
                    error="=unsafe spreadsheet formula",
                ),
            )
            for outcome in outcomes:
                publisher(outcome)

            published = publisher.finalize()

            summary_path = root / "summary.json"
            csv_path = root / "summary.csv"
            self.assertEqual(
                json.loads(summary_path.read_text(encoding="utf-8")), published
            )
            summary_lines = summary_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(summary_lines[0], "{")
            self.assertTrue(summary_lines[1].startswith('  "'))
            self.assertEqual(summary_lines[-1], "}")
            self.assertTrue(summary_path.read_bytes().endswith(b"}\n"))
            self.assertEqual(published["selected_pairs"], 3)
            self.assertEqual(published["move_count"], 2)
            self.assertEqual(published["summary_csv"]["rows"], 3)
            self.assertEqual(
                published["summary_csv"]["sha256"],
                hashlib.sha256(csv_path.read_bytes()).hexdigest(),
            )
            with csv_path.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([row["sequence"] for row in rows], ["0", "1", "2"])
            self.assertEqual(
                [row["status"] for row in rows],
                ["completed", "no_analyzable_change", "srcdiff_failed"],
            )
            self.assertEqual(rows[2]["move_count"], "")
            self.assertEqual(rows[2]["error"], "'=unsafe spreadsheet formula")
            self.assertEqual(rows[0]["receipt_path"], "pairs/000000.json")
            self.assertEqual(
                PairReceiptPublisher(root).summary(),
                {
                    **{
                        key: value
                        for key, value in published.items()
                        if key != "summary_csv"
                    },
                    "schema_version": 1,
                },
            )

            first_csv = csv_path.read_bytes()
            first_summary = summary_path.read_bytes()
            publisher.finalize()
            self.assertEqual(csv_path.read_bytes(), first_csv)
            self.assertEqual(summary_path.read_bytes(), first_summary)
            self.assertEqual(list(root.glob(".*.tmp-*")), [])

    def test_reporting_rejects_unsealed_and_noncontiguous_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pairs = root / "pairs"
            pairs.mkdir()
            unsealed = pair_receipt(
                PairOutcome(
                    work_item=work_item(0), status=PairStatus.COMPLETED
                )
            )
            (pairs / "000000.json").write_text(
                json.dumps(unsealed), encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "not sealed"):
                PairReceiptPublisher(root).finalize()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pairs = root / "pairs"
            pairs.mkdir()
            later = pair_receipt(
                PairOutcome(
                    work_item=work_item(1), status=PairStatus.COMPLETED
                )
            )
            later["sealed"] = True
            (pairs / "000001.json").write_text(
                json.dumps(later), encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "must be contiguous"):
                PairReceiptPublisher(root).finalize()

    def test_reporting_never_aggregates_missing_completed_metrics_as_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pairs = root / "pairs"
            pairs.mkdir()
            incomplete = pair_receipt(
                PairOutcome(
                    work_item=work_item(0),
                    status=PairStatus.COMPLETED,
                    metrics=(("move_count", 0),),
                )
            )
            incomplete["sealed"] = True
            (pairs / "000000.json").write_text(
                json.dumps(incomplete), encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "missing metric"):
                PairReceiptPublisher(root).summary()

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pairs = root / "pairs"
            pairs.mkdir()
            no_results = pair_receipt(
                PairOutcome(
                    work_item=work_item(0),
                    status=PairStatus.COMPLETED,
                    metrics=(
                        ("move_count", 0),
                        ("move_group_count", 0),
                        ("move_pair_count", 0),
                        ("annotated_region_count", 0),
                    ),
                )
            )
            no_results["sealed"] = True
            (pairs / "000000.json").write_text(
                json.dumps(no_results), encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "retained valid results.json"):
                PairReceiptPublisher(root).summary()

    def test_failed_report_publication_never_changes_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            publisher = PairReceiptPublisher(root)
            publisher(completed_outcome(root, 0))
            receipt = root / "pairs" / "000000.json"
            before = receipt.read_bytes()

            with (
                mock.patch(
                    "repository_analysis.reporting._replace_derived_file",
                    side_effect=OSError("injected publication failure"),
                ),
                self.assertRaisesRegex(OSError, "publication failure"),
            ):
                publisher.finalize()

            self.assertEqual(receipt.read_bytes(), before)
            self.assertEqual(list(root.glob(".*.tmp-*")), [])
            self.assertFalse((root / "summary.json").exists())

    def test_summary_hash_detects_crash_between_csv_and_json_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            publisher = PairReceiptPublisher(root)
            publisher(completed_outcome(root, 0))
            publisher.finalize()
            summary_path = root / "summary.json"
            old_summary = json.loads(summary_path.read_text(encoding="utf-8"))
            publisher(
                PairOutcome(
                    work_item=work_item(1),
                    status=PairStatus.NO_ANALYZABLE_CHANGE,
                )
            )
            real_replace = reporting_module._replace_derived_file

            def fail_json_replacement(temporary: Path, destination: Path) -> None:
                if destination.name == "summary.json":
                    raise OSError("injected summary replacement failure")
                real_replace(temporary, destination)

            with (
                mock.patch(
                    "repository_analysis.reporting._replace_derived_file",
                    side_effect=fail_json_replacement,
                ),
                self.assertRaisesRegex(OSError, "summary replacement failure"),
            ):
                publisher.finalize()

            self.assertEqual(
                json.loads(summary_path.read_text(encoding="utf-8")), old_summary
            )
            self.assertNotEqual(
                hashlib.sha256((root / "summary.csv").read_bytes()).hexdigest(),
                old_summary["summary_csv"]["sha256"],
            )
            self.assertEqual(list(root.glob(".*.tmp-*")), [])


if __name__ == "__main__":
    unittest.main()
