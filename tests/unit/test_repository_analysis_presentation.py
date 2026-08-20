from __future__ import annotations

import unittest

from repository_analysis.presentation import render_run, render_status


class RepositoryAnalysisPresentationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.summary = {
            "analysis": {"name": "SQLite", "root": "/results/sqlite-300"},
            "completed_pair_count": 300,
            "checkpointed_pair_count": 0,
            "durable_pair_count": 300,
            "completed": 70,
            "no_analyzable_change": 211,
            "failed": 19,
            "statuses": {
                "completed": 70,
                "no_analyzable_change": 211,
                "srcdiff_failed": 18,
                "srcmove_failed": 1,
            },
            "move_group_count": 59,
            "move_pair_count": 67,
            "annotated_region_count": 156,
            "newest_commit": "3f523613528194d3487853ed6e5367c6f215ec4f",
            "oldest_completed_commit": "0a4af54a7e67e3cf87a7cec44d80870f5df260cf",
            "timings": {"srcdiff_seconds": 186.988, "srcmove_seconds": 43.022},
            "invocation": {
                "target_kind": "total_pairs",
                "target_value": "300",
                "result": "target_reached_with_failures",
                "wall_seconds": 127.054,
                "ended_at": "2026-08-20T17:58:22+00:00",
            },
        }

    def test_status_uses_human_terms_and_actionable_failure_summary(self) -> None:
        rendered = render_status(self.summary)

        self.assertIn("SQLite — target reached with failures", rendered)
        self.assertIn("Coverage   300/300 pairs (100%)", rendered)
        self.assertIn("Results    70 analyzed · 211 skipped · 19 failed", rendered)
        self.assertIn("Failures   18 srcDiff · 1 srcMove", rendered)
        self.assertIn(
            "Moves      59 groups · 67 move pairs · 156 annotated regions",
            rendered,
        )
        self.assertIn(
            "Time       2m 07s wall · 187.0s srcDiff work · 43.0s srcMove work",
            rendered,
        )
        self.assertIn("Frontier   3f523613 → 0a4af54a", rendered)
        self.assertTrue(
            rendered.endswith(
                "Inspect: srcmove-history list /results/sqlite-300 --failed"
            )
        )

    def test_run_has_final_heading_and_omits_status_percentage(self) -> None:
        rendered = render_run(self.summary)

        self.assertTrue(
            rendered.startswith(
                "SQLite history analysis reached its target with failures\n"
            )
        )
        self.assertIn("Coverage   300/300 pairs\n", rendered)
        self.assertNotIn("(100%)", rendered)
        self.assertIn("History    3f523613 → 0a4af54a", rendered)

    def test_nested_planned_shape_and_clean_singular_counts(self) -> None:
        rendered = render_run(
            {
                "analysis": {"name": "fixture", "root": "/tmp/fixture"},
                "state": "target_reached",
                "coverage": {"target": 1, "committed": 1, "durable": 1},
                "outcomes": {"analyzed": 1, "skipped": 0, "failed": 0},
                "moves": {"groups": 1, "pairs": 1, "annotated_regions": 1},
            }
        )

        self.assertIn("fixture history analysis complete", rendered)
        self.assertIn("Results    1 analyzed · 0 skipped · 0 failed", rendered)
        self.assertIn(
            "Moves      1 group · 1 move pair · 1 annotated region", rendered
        )
        self.assertNotIn("Failures", rendered)
        self.assertNotIn("Inspect:", rendered)

    def test_sparse_current_snapshot_remains_readable(self) -> None:
        rendered = render_status(
            {
                "completed_pair_count": 4,
                "completed": 2,
                "no_analyzable_change": 2,
                "failed": 0,
            }
        )

        self.assertIn("Repository — idle", rendered)
        self.assertIn("Coverage   4 pairs covered", rendered)
        self.assertIn("Results    2 analyzed · 2 skipped · 0 failed", rendered)
        self.assertNotIn("Analysis  ", rendered)

    def test_unknown_target_size_does_not_invent_a_percentage(self) -> None:
        rendered = render_status(
            {
                "analysis_root": "/tmp/all-history",
                "durable_pair_count": 327,
                "history_exhausted": True,
                "invocation": {"target_kind": "all", "target_value": None},
            }
        )

        self.assertIn("all-history — history exhausted", rendered)
        self.assertIn("Coverage   327 pairs covered", rendered)
        self.assertNotIn("%", rendered)

    def test_already_exceeded_target_does_not_render_over_one_hundred_percent(
        self,
    ) -> None:
        summary = dict(self.summary)
        summary["durable_pair_count"] = 300
        summary["completed_pair_count"] = 300
        summary["invocation"] = {
            "target_kind": "total_pairs",
            "target_value": "100",
            "result": "target_reached_with_failures",
        }

        rendered = render_status(summary)

        self.assertIn("300 pairs covered (target 100 satisfied)", rendered)
        self.assertNotIn("300%", rendered)


if __name__ == "__main__":
    unittest.main()
