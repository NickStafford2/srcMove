from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from repository_analysis import (
    CaptureObservation,
    PairOutcome,
    PairReceiptPublisher,
    PairStatus,
    PairWorkItem,
    ProcessOutcome,
    VerifiedArtifact,
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


if __name__ == "__main__":
    unittest.main()
