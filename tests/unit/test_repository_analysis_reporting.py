from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

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
                PairOutcome(
                    work_item=work_item(0),
                    status=PairStatus.COMPLETED,
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

            first = PairOutcome(
                work_item=work_item(0), status=PairStatus.COMPLETED
            )
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
            self.assertEqual(publisher.summary()["selected_pairs"], 0)

    def test_zero_move_seal_retains_results_but_discards_xml(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            worker = root / "worker"
            worker.mkdir()
            xml = worker / "srcmove.xml"
            xml.write_text("<unit/>", encoding="utf-8")
            results = worker / "results.json"
            results.write_text('{"move_count":0}\n', encoding="utf-8")
            outcome = PairOutcome(
                work_item=work_item(0),
                status=PairStatus.COMPLETED,
                artifacts=(
                    file_artifact(xml, kind="xml", stage="srcmove"),
                    file_artifact(results, kind="json_results", stage="srcmove"),
                ),
                metrics=(("move_count", 0),),
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
            xml = worker / "srcmove.xml"
            xml.write_text("<unit/>", encoding="utf-8")
            results = worker / "results.json"
            results.write_text('{"move_count":1}\n', encoding="utf-8")
            outcome = PairOutcome(
                work_item=work_item(0),
                status=PairStatus.COMPLETED,
                artifacts=(
                    file_artifact(xml, kind="xml", stage="srcmove"),
                    file_artifact(results, kind="json_results", stage="srcmove"),
                ),
                metrics=(("move_count", 1),),
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
                        metrics=(("move_count", 0),),
                    )
                )

            self.assertFalse((root / "pairs" / "000000.json").exists())
            self.assertTrue(outside.exists())


if __name__ == "__main__":
    unittest.main()
