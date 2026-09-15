from __future__ import annotations

import unittest
from pathlib import Path

from repository_analysis.report import (
    CommitPairMaximum,
    ReportSnapshot,
    render_report,
)


class RepositoryAnalysisReportTests(unittest.TestCase):
    def test_report_uses_explicit_commit_pair_terminology(self) -> None:
        report = render_report(self._snapshot())

        self.assertIn(
            "Move prevalence\n"
            "  Detected moves              65\n"
            "  Commit pairs with ≥1 move   16 of 81 (19.8%)",
            report,
        )
        self.assertIn("Distribution across compared commit pairs", report)
        self.assertIn("Slowest commit pair", report)
        self.assertNotIn("Annotated regions", report)
        self.assertNotIn("Slowest pair", report)

    def test_report_states_scope_concentration_and_detection_limits(self) -> None:
        report = render_report(self._snapshot())

        self.assertIn("140 of 6,360 commit pairs (2.2%)", report)
        self.assertIn(
            "Commit pair 103 contributes 39 of 65 detections (60.0%).",
            report,
        )
        self.assertIn(
            "Type 3 approximate matches account for 41 of 65 detections (63.1%).",
            report,
        )
        self.assertIn("not manually validated ground truth", report)
        self.assertIn("No commit pair processing failures", report)

    @staticmethod
    def _snapshot() -> ReportSnapshot:
        return ReportSnapshot(
            repository_name="notepad-plus-plus",
            repository=Path("/repository"),
            analysis_root=Path("/repository/.srcmove"),
            newest_commit="de0a77ba" * 5,
            oldest_commit="5c9ecc6a" * 5,
            newest_date="2026-08-17",
            oldest_date="2026-05-17",
            total_history_commit_pairs=6360,
            covered_commit_pairs=140,
            compared_commit_pairs=81,
            no_analyzable_change_commit_pairs=59,
            failures=(),
            changed_paths=784,
            analyzable_paths=368,
            move_groups=65,
            move_bearing_commit_pairs=16,
            match_kinds=(("exact", 20), ("type2", 4), ("type3", 41)),
            within_file_moves=52,
            cross_file_moves=13,
            unclassified_location_moves=0,
            group_kinds=(("copy_or_repeat", 1), ("move_1_to_1", 64)),
            mean_moves=65 / 81,
            median_moves=0.0,
            p95_moves=2.0,
            maximum=CommitPairMaximum(
                number=103,
                old_commit="c69b22ef" * 5,
                new_commit="597276d0" * 5,
                moves=39,
            ),
            cumulative_wall_seconds=118.043,
            srcdiff_seconds=267.29,
            srcmove_seconds=74.204,
            mean_commit_pair_seconds=4.452,
            median_commit_pair_seconds=2.9,
            p95_commit_pair_seconds=11.796,
            maximum_commit_pair_seconds=43.697,
            exclusion_counts=((".xml", 195), (".html", 30)),
            selected_directory=None,
            excluded_suffixes=(".py",),
            use_position=False,
            source_encoding="UTF-8",
            srcdiff_sha256="a" * 64,
            srcmove_sha256="b" * 64,
            fingerprint_schemas=(("pair_outcome", 1),),
            history_exhausted=False,
        )


if __name__ == "__main__":
    unittest.main()
