from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from repository_analysis import (
    CaptureObservation,
    PairOutcome,
    PairReceiptPublisher,
    PairStatus,
    PairWorkItem,
    ProcessOutcome,
    RetentionPolicy,
    VerifiedArtifact,
    resume_pairs,
)


def work_item(sequence: int) -> PairWorkItem:
    return PairWorkItem(
        sequence=sequence,
        old_commit=f"old-{sequence}",
        new_commit=f"new-{sequence}",
        fingerprint=f"fingerprint-{sequence}",
    )


def completed_outcome(root: Path, item: PairWorkItem) -> PairOutcome:
    worker = root / f"worker-{item.sequence}-{item.fingerprint}"
    worker.mkdir(exist_ok=True)
    results = worker / "results.json"
    metrics = {
        "move_count": 0,
        "move_group_count": 0,
        "move_pair_count": 0,
        "annotated_region_count": 0,
    }
    content = (json.dumps(metrics, sort_keys=True) + "\n").encode()
    results.write_bytes(content)
    return PairOutcome(
        work_item=item,
        status=PairStatus.COMPLETED,
        artifacts=(
            VerifiedArtifact(
                path=results,
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                kind="json_results",
                validation_status="valid",
                producing_stage="srcmove",
            ),
        ),
        metrics=tuple(metrics.items()),
    )


def positive_outcome(root: Path, item: PairWorkItem) -> PairOutcome:
    outcome = completed_outcome(root, item)
    worker = outcome.artifacts[0].path.parent
    artifacts = []
    for stage in ("srcdiff", "srcmove"):
        path = worker / f"{stage}.xml"
        path.write_bytes(stage.encode())
        artifacts.append(
            VerifiedArtifact(
                path=path,
                size_bytes=len(stage),
                sha256=hashlib.sha256(stage.encode()).hexdigest(),
                kind="xml",
                validation_status="valid",
                producing_stage=stage,
            )
        )
    metrics = dict(outcome.metrics)
    metrics.update(
        move_count=1,
        move_group_count=1,
        move_pair_count=1,
        annotated_region_count=2,
    )
    return replace(
        outcome,
        artifacts=(*artifacts, *outcome.artifacts),
        metrics=tuple(metrics.items()),
    )


def receipt(root: Path, sequence: int) -> dict[str, object]:
    return json.loads(
        (root / "pairs" / f"{sequence:06d}.json").read_text(encoding="utf-8")
    )


def capture(path: Path | None, content: bytes = b"") -> CaptureObservation:
    if path is not None:
        path.write_bytes(content)
    return CaptureObservation(
        path=path,
        total_bytes=len(content),
        retained_bytes=len(content),
        omitted_bytes=0,
        truncated=False,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def failed_outcome(root: Path, item: PairWorkItem) -> PairOutcome:
    worker = root / f"failed-worker-{item.sequence}"
    worker.mkdir()
    partial = worker / "srcdiff.xml"
    partial.write_bytes(b"partial")
    artifact = VerifiedArtifact(
        path=partial,
        size_bytes=7,
        sha256=hashlib.sha256(b"partial").hexdigest(),
        kind="xml",
        validation_status="malformed",
        producing_stage="srcdiff",
    )
    process = ProcessOutcome(
        command=("srcdiff",),
        working_directory=worker,
        started_at="2026-08-20T00:00:00+00:00",
        completed_at="2026-08-20T00:00:01+00:00",
        elapsed_seconds=1.0,
        termination_status="exited",
        exit_code=1,
        signal_number=None,
        timed_out=False,
        spawn_error=None,
        cleanup_signals=(),
        process_group_cleaned=True,
        stdout=capture(worker / "stdout.bin", b"failure log"),
        stderr=capture(None),
        peak_rss_bytes=None,
        oom_kill_observed=False,
        output_artifact=artifact,
        validation_error="malformed",
    )
    return PairOutcome(
        work_item=item,
        status=PairStatus.SRCDIFF_FAILED,
        srcdiff_process=process,
        artifacts=(artifact,),
        error="srcDiff failed",
    )


class VerifiedResumeTests(unittest.TestCase):
    def test_resume_with_zero_some_and_all_verified_pairs(self) -> None:
        for verified_count in (0, 2, 4):
            with (
                self.subTest(verified_count=verified_count),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                root = Path(temporary_directory)
                items = [work_item(sequence) for sequence in range(4)]
                publisher = PairReceiptPublisher(root)
                for item in items[:verified_count]:
                    publisher(completed_outcome(root, item))
                (root / "summary.json").write_text("stale\n", encoding="utf-8")
                calls: list[int] = []

                def execute(item: PairWorkItem) -> PairOutcome:
                    calls.append(item.sequence)
                    return completed_outcome(root, item)

                stats = resume_pairs(
                    items,
                    execute,
                    analysis_root=root,
                    worker_count=2,
                )

                self.assertEqual(stats.verified_count, verified_count)
                self.assertEqual(calls, list(range(verified_count, 4)))
                self.assertEqual(stats.execution.submitted_count, 4 - verified_count)
                self.assertEqual(stats.summary["selected_pairs"], 4)
                self.assertEqual(stats.summary["completed"], 4)
                self.assertEqual(stats.summary["move_count"], 0)
                self.assertEqual(
                    sorted(path.name for path in (root / "pairs").glob("*.json")),
                    [f"{sequence:06d}.json" for sequence in range(4)],
                )
                self.assertTrue((root / "summary.csv").is_file())
                self.assertEqual(
                    json.loads((root / "summary.json").read_text())["selected_pairs"],
                    4,
                )

    def test_all_verified_resume_does_not_open_worker_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            item = work_item(0)
            PairReceiptPublisher(root)(completed_outcome(root, item))

            class MustNotOpen:
                @contextmanager
                def open_worker(self):
                    raise AssertionError("verified resume opened a worker")
                    yield

            stats = resume_pairs(
                [item], MustNotOpen(), analysis_root=root, worker_count=2
            )

            self.assertEqual(stats.execution.submitted_count, 0)

    def test_unsealed_worker_evidence_is_ignored_before_first_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            interrupted = root / "repository-analysis-worker-interrupted" / "pair"
            interrupted.mkdir(parents=True)
            evidence = interrupted / "partial.xml"
            evidence.write_text("partial", encoding="utf-8")
            item = work_item(0)
            calls: list[int] = []

            def execute(requested: PairWorkItem) -> PairOutcome:
                calls.append(requested.sequence)
                return completed_outcome(root, requested)

            resume_pairs([item], execute, analysis_root=root, worker_count=1)

            self.assertEqual(calls, [0])
            self.assertEqual(evidence.read_text(encoding="utf-8"), "partial")

    def test_interrupted_pair_storage_is_preserved_before_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            interrupted = root / "pairs" / "000000" / "artifacts"
            interrupted.mkdir(parents=True)
            evidence = interrupted / "partial.xml"
            evidence.write_text("partial", encoding="utf-8")

            resume_pairs(
                [work_item(0)],
                lambda item: completed_outcome(root, item),
                analysis_root=root,
                worker_count=1,
            )

            preserved = list((root / "unsealed-pairs").glob("pair-000000-*"))
            self.assertEqual(len(preserved), 1)
            self.assertEqual(
                (preserved[0] / "artifacts" / "partial.xml").read_text(),
                "partial",
            )
            self.assertTrue((root / "pairs" / "000000.json").is_file())
            self.assertTrue((root / "pairs" / "000000").is_dir())

    def test_failed_receipt_verifies_retained_evidence_and_empty_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            item = work_item(0)
            PairReceiptPublisher(root)(failed_outcome(root, item))

            stats = resume_pairs(
                [item],
                lambda requested: self.fail("verified failure was re-executed"),
                analysis_root=root,
                worker_count=1,
            )

            self.assertEqual(stats.verified_count, 1)
            self.assertEqual(stats.summary["failed"], 1)

            record = receipt(root, 0)
            receipt_path = root / "pairs" / "000000.json"
            malformed = json.loads(json.dumps(record))
            malformed_capture = malformed["srcdiff_process"]["stdout"]
            malformed_capture["retained_bytes"] = 0
            malformed_capture["omitted_bytes"] = malformed_capture["total_bytes"]
            malformed_capture["truncated"] = True
            malformed_capture["path"] = None
            malformed_capture["retained_sha256"] = None
            receipt_path.write_text(json.dumps(malformed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "required retained capture"):
                resume_pairs(
                    [item],
                    lambda requested: self.fail("malformed failure was executed"),
                    analysis_root=root,
                    worker_count=1,
                )

            receipt_path.write_text(json.dumps(record), encoding="utf-8")
            stdout = root / record["srcdiff_process"]["stdout"]["path"]
            stdout.write_bytes(b"changed log")
            with self.assertRaisesRegex(ValueError, "size drift|checksum drift"):
                resume_pairs(
                    [item],
                    lambda requested: self.fail("corrupt failure was executed"),
                    analysis_root=root,
                    worker_count=1,
                )

    def test_positive_xml_policy_verifies_both_retained_tool_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            item = work_item(0)
            policy = RetentionPolicy(retain_positive_xml=True)
            PairReceiptPublisher(root, retention_policy=policy)(
                positive_outcome(root, item)
            )

            stats = resume_pairs(
                [item],
                lambda requested: self.fail("verified positive pair was executed"),
                analysis_root=root,
                worker_count=1,
                retention_policy=policy,
            )
            self.assertEqual(stats.verified_count, 1)

            record = receipt(root, 0)
            srcdiff = next(
                artifact
                for artifact in record["artifacts"]
                if artifact["producing_stage"] == "srcdiff"
            )
            (root / srcdiff["path"]).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "size drift|checksum drift"):
                resume_pairs(
                    [item],
                    lambda requested: self.fail("corrupt positive pair was executed"),
                    analysis_root=root,
                    worker_count=1,
                    retention_policy=policy,
                )

    def test_acknowledges_only_new_suffix_and_rejects_invalid_requested_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            items = [work_item(sequence) for sequence in range(3)]
            PairReceiptPublisher(root)(completed_outcome(root, items[0]))
            acknowledgements: list[int] = []

            resume_pairs(
                items,
                lambda item: completed_outcome(root, item),
                analysis_root=root,
                worker_count=2,
                acknowledge_pair=lambda outcome: acknowledgements.append(
                    outcome.work_item.sequence
                ),
            )

            self.assertEqual(acknowledgements, [1, 2])

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            publisher = PairReceiptPublisher(root)
            publisher(completed_outcome(root, work_item(0)))
            publisher(completed_outcome(root, work_item(1)))
            with self.assertRaisesRegex(ValueError, "no requested work item"):
                resume_pairs(
                    [work_item(0)],
                    lambda item: completed_outcome(root, item),
                    analysis_root=root,
                    worker_count=1,
                )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            PairReceiptPublisher(root)(completed_outcome(root, work_item(0)))
            with self.assertRaisesRegex(ValueError, "expected 1, got 2"):
                resume_pairs(
                    [work_item(0), work_item(2)],
                    lambda item: completed_outcome(root, item),
                    analysis_root=root,
                    worker_count=1,
                )

    def test_resume_rejects_identity_and_fingerprint_drift_before_execution(
        self,
    ) -> None:
        cases = {
            "old commit": replace(work_item(0), old_commit="different-old"),
            "new commit": replace(work_item(0), new_commit="different-new"),
            "fingerprint": replace(work_item(0), fingerprint="different-config-tool"),
        }
        for name, requested in cases.items():
            with (
                self.subTest(name=name),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                root = Path(temporary_directory)
                PairReceiptPublisher(root)(completed_outcome(root, work_item(0)))
                calls: list[int] = []

                with self.assertRaisesRegex(ValueError, "drift"):
                    resume_pairs(
                        [requested],
                        lambda item: calls.append(item.sequence),
                        analysis_root=root,
                        worker_count=1,
                    )

                self.assertEqual(calls, [])

    def test_resume_rejects_missing_modified_and_symlinked_artifacts(self) -> None:
        for damage in ("missing", "size", "checksum", "symlink", "directory"):
            with (
                self.subTest(damage=damage),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                root = Path(temporary_directory)
                PairReceiptPublisher(root)(completed_outcome(root, work_item(0)))
                record = receipt(root, 0)
                artifact = next(
                    value
                    for value in record["artifacts"]
                    if value["kind"] == "json_results"
                )
                retained = root / artifact["path"]
                if damage == "missing":
                    retained.unlink()
                elif damage == "size":
                    retained.write_bytes(retained.read_bytes() + b"x")
                elif damage == "checksum":
                    content = retained.read_bytes()
                    retained.write_bytes(bytes([content[0] ^ 1]) + content[1:])
                elif damage == "symlink":
                    outside = root / "outside.json"
                    outside.write_bytes(retained.read_bytes())
                    retained.unlink()
                    retained.symlink_to(outside)
                else:
                    retained.unlink()
                    retained.mkdir()
                calls: list[int] = []

                with self.assertRaisesRegex(
                    ValueError,
                    "missing|size drift|checksum drift|symbolic link|"
                    "not a regular file",
                ):
                    resume_pairs(
                        [work_item(0)],
                        lambda item: calls.append(item.sequence),
                        analysis_root=root,
                        worker_count=1,
                    )

                self.assertEqual(calls, [])

    def test_resume_rejects_unsafe_paths_schema_and_policy_drift(self) -> None:
        cases = {
            "absolute": ("artifact_path", "/tmp/outside"),
            "traversal": ("artifact_path", "../outside"),
            "schema": ("schema_version", 999),
            "policy": ("retention_policy", {"completed_zero_move": "receipt_only"}),
        }
        for name, (field, value) in cases.items():
            with (
                self.subTest(name=name),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                root = Path(temporary_directory)
                PairReceiptPublisher(root)(completed_outcome(root, work_item(0)))
                path = root / "pairs" / "000000.json"
                record = json.loads(path.read_text(encoding="utf-8"))
                if field == "artifact_path":
                    artifact = next(
                        artifact
                        for artifact in record["artifacts"]
                        if artifact["kind"] == "json_results"
                    )
                    artifact["path"] = value
                else:
                    record[field] = value
                path.write_text(json.dumps(record), encoding="utf-8")
                calls: list[int] = []

                with self.assertRaises(ValueError):
                    resume_pairs(
                        [work_item(0)],
                        lambda item: calls.append(item.sequence),
                        analysis_root=root,
                        worker_count=1,
                    )

                self.assertEqual(calls, [])

    def test_resumed_and_fresh_results_are_identical_across_worker_counts(self) -> None:
        items = [work_item(sequence) for sequence in range(6)]
        outputs: list[tuple[dict[str, object], list[dict[str, object]]]] = []
        for worker_count, verified_count in ((1, 0), (3, 3)):
            with tempfile.TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                publisher = PairReceiptPublisher(root)
                for item in items[:verified_count]:
                    publisher(completed_outcome(root, item))
                stats = resume_pairs(
                    items,
                    lambda item: completed_outcome(root, item),
                    analysis_root=root,
                    worker_count=worker_count,
                )
                normalized_summary = {
                    key: value
                    for key, value in stats.summary.items()
                    if key != "summary_csv"
                }
                normalized_receipts = [
                    {
                        key: value
                        for key, value in receipt(root, sequence).items()
                        if key not in {"timings", "srcdiff_process", "srcmove_process"}
                    }
                    for sequence in range(len(items))
                ]
                outputs.append((normalized_summary, normalized_receipts))

        self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
