from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from repository_analysis.compact import (
    COMPACT_FAILURE_LOG_LIMIT,
    compact_pair_outcome,
)
from repository_analysis.contracts import (
    CaptureObservation,
    ChangedPath,
    PairOutcome,
    PairStatus,
    PairWorkItem,
    ProcessOutcome,
    VerifiedArtifact,
)
from repository_analysis.process import (
    ArtifactValidationError,
    validate_results_artifact,
)


def item() -> PairWorkItem:
    return PairWorkItem(0, "old", "new", "fingerprint")


class CompactPairTests(unittest.TestCase):
    def test_path_exclusion_reasons_are_retained_as_compact_counts(self) -> None:
        paths = (
            ChangedPath(
                "A",
                "linked.cpp",
                "000000",
                "120000",
                "0" * 40,
                "1" * 40,
                ("unsupported_git_mode: symlink",),
            ),
            ChangedPath(
                "A",
                "vendor/module",
                "000000",
                "160000",
                "0" * 40,
                "2" * 40,
                ("unsupported_git_mode: submodule",),
            ),
        )
        outcome = PairOutcome(
            item(),
            PairStatus.NO_ANALYZABLE_CHANGE,
            changed_paths=paths,
        )

        compact = compact_pair_outcome(outcome)

        self.assertEqual(
            json.loads(compact.metrics_json)["path_exclusion_counts"],
            {
                "unsupported_git_mode: submodule": 1,
                "unsupported_git_mode: symlink": 1,
            },
        )

    def test_success_keeps_locations_and_text_digests_without_raw_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raw_text = "a very large moved source region"
            results = {
                "move_count": 1,
                "move_group_count": 1,
                "move_pair_count": 1,
                "annotated_region_count": 2,
                "moves": [
                    {
                        "match_kind": "exact",
                        "from_xpaths": ["/unit[1]/function[1]"],
                        "to_xpaths": ["/unit[1]/function[2]"],
                        "from_raw_texts": [raw_text],
                        "to_raw_texts": [raw_text],
                    }
                ],
                "group_kinds": {"one_to_one": 1},
                "match_kinds": {"exact": 1, "type2": 0},
            }
            content = json.dumps(results).encode("utf-8")
            path = root / "results.json"
            path.write_bytes(content)
            artifact = VerifiedArtifact(
                path,
                len(content),
                hashlib.sha256(content).hexdigest(),
                "json_results",
                "valid",
                "srcmove",
            )
            outcome = PairOutcome(
                item(),
                PairStatus.COMPLETED,
                artifacts=(artifact,),
                metrics=(
                    ("move_count", 1),
                    ("move_group_count", 1),
                    ("move_pair_count", 1),
                    ("annotated_region_count", 2),
                ),
                timings=(("pair_seconds", 1.25),),
            )

            compact = compact_pair_outcome(outcome)

            self.assertEqual(len(compact.moves), 1)
            self.assertEqual(
                json.loads(compact.moves[0].from_xpaths_json),
                ["/unit[1]/function[1]"],
            )
            digest = json.loads(compact.moves[0].from_text_digests_json)[0]
            self.assertEqual(digest["size_bytes"], len(raw_text.encode("utf-8")))
            self.assertEqual(
                digest["sha256"],
                hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
            )
            self.assertNotIn(raw_text.encode("utf-8"), compact.metrics_json)
            self.assertEqual(
                json.loads(compact.metrics_json)["match_kinds"]["exact"], 1
            )

    def test_failure_embeds_only_the_bounded_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            retained = b"headtail"
            capture_path = root / "stderr.bin"
            capture_path.write_bytes(retained)
            empty = CaptureObservation(
                None, 0, 0, 0, False, hashlib.sha256(b"").hexdigest()
            )
            capture = CaptureObservation(
                capture_path,
                1000,
                len(retained),
                1000 - len(retained),
                True,
                hashlib.sha256(b"unretained-full-stream").hexdigest(),
            )
            process = ProcessOutcome(
                command=("srcdiff",),
                working_directory=root,
                started_at="start",
                completed_at="end",
                elapsed_seconds=2.0,
                termination_status="exited",
                exit_code=1,
                signal_number=None,
                timed_out=False,
                spawn_error=None,
                cleanup_signals=(),
                process_group_cleaned=True,
                stdout=empty,
                stderr=capture,
                peak_rss_bytes=1024,
                oom_kill_observed=False,
                output_artifact=None,
                validation_error=None,
            )
            outcome = PairOutcome(
                item(),
                PairStatus.SRCDIFF_FAILED,
                srcdiff_process=process,
                error="srcDiff exited 1",
            )

            compact = compact_pair_outcome(outcome)

            evidence = json.loads(compact.evidence_json)
            self.assertEqual(
                evidence["srcdiff"]["stderr"]["durable_retained_bytes"],
                len(retained),
            )
            self.assertNotIn("working_directory", evidence["srcdiff"])
            self.assertNotIn("command", evidence["srcdiff"])

    def test_durable_failure_capture_has_a_smaller_storage_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            retained = b"h" * (COMPACT_FAILURE_LOG_LIMIT // 2) + b"t" * (
                COMPACT_FAILURE_LOG_LIMIT
            )
            capture_path = root / "stderr.bin"
            capture_path.write_bytes(retained)
            empty = CaptureObservation(
                None, 0, 0, 0, False, hashlib.sha256(b"").hexdigest()
            )
            capture = CaptureObservation(
                capture_path,
                len(retained),
                len(retained),
                0,
                False,
                hashlib.sha256(retained).hexdigest(),
            )
            process = ProcessOutcome(
                command=("srcdiff",),
                working_directory=root,
                started_at="start",
                completed_at="end",
                elapsed_seconds=1.0,
                termination_status="exited",
                exit_code=1,
                signal_number=None,
                timed_out=False,
                spawn_error=None,
                cleanup_signals=(),
                process_group_cleaned=True,
                stdout=empty,
                stderr=capture,
                peak_rss_bytes=None,
                oom_kill_observed=False,
                output_artifact=None,
                validation_error=None,
            )

            compact = compact_pair_outcome(
                PairOutcome(
                    item(),
                    PairStatus.SRCDIFF_FAILED,
                    srcdiff_process=process,
                    error="failed",
                )
            )

            evidence = json.loads(compact.evidence_json)["srcdiff"]["stderr"]
            self.assertEqual(
                evidence["durable_retained_bytes"], COMPACT_FAILURE_LOG_LIMIT
            )
            self.assertEqual(
                evidence["durable_omitted_bytes"],
                len(retained) - COMPACT_FAILURE_LOG_LIMIT,
            )

    def test_success_rejects_results_that_cannot_be_investigated_later(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            content = json.dumps(
                {
                    "move_count": 1,
                    "move_group_count": 1,
                    "move_pair_count": 1,
                    "annotated_region_count": 2,
                    "group_kinds": {},
                    "match_kinds": {},
                }
            ).encode()
            path = root / "results.json"
            path.write_bytes(content)
            artifact = VerifiedArtifact(
                path,
                len(content),
                hashlib.sha256(content).hexdigest(),
                "json_results",
                "valid",
                "srcmove",
            )
            outcome = PairOutcome(
                item(),
                PairStatus.COMPLETED,
                artifacts=(artifact,),
                metrics=(
                    ("move_count", 1),
                    ("move_group_count", 1),
                    ("move_pair_count", 1),
                    ("annotated_region_count", 2),
                ),
            )

            with self.assertRaisesRegex(ValueError, "moves do not match"):
                compact_pair_outcome(outcome)

    def test_admission_rejects_results_that_compaction_cannot_store(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "results.json"
            path.write_text(
                json.dumps(
                    {
                        "move_count": 1,
                        "move_group_count": 1,
                        "move_pair_count": 1,
                        "annotated_region_count": 2,
                        "moves": [{}],
                        "group_kinds": {},
                        "match_kinds": {},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ArtifactValidationError, "match kind"):
                validate_results_artifact(path)


if __name__ == "__main__":
    unittest.main()
