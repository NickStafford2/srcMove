from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from repository_analysis.configuration import (
    HistoryConfiguration,
    create_history_configuration,
    load_history_configuration,
    render_history_configuration,
)
from repository_analysis.inputs import AnalysisConfiguration


class RepositoryAnalysisConfigurationTests(unittest.TestCase):
    def test_configuration_round_trips_analysis_and_run_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            configuration = HistoryConfiguration(
                analysis=AnalysisConfiguration(
                    selected_directory="src",
                    excluded_suffixes=(".py", ".txt"),
                    use_archive=False,
                    use_position=True,
                    source_encoding="ISO-8859-1",
                    srcdiff_timeout_seconds=12,
                    srcmove_timeout_seconds=3,
                ),
                jobs=6,
            )

            create_history_configuration(root, configuration)

            self.assertEqual(load_history_configuration(root), configuration)
            rendered = (root / "config.toml").read_text(encoding="utf-8")
            self.assertIn("excluded_suffixes = [\".py\", \".txt\"]", rendered)
            self.assertIn("jobs = 6", rendered)

    def test_default_directory_round_trips_through_dot(self) -> None:
        configuration = HistoryConfiguration()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            create_history_configuration(root, configuration)

            self.assertIn(
                'selected_directory = "."',
                render_history_configuration(configuration),
            )
            self.assertEqual(load_history_configuration(root), configuration)

    def test_loader_rejects_unknown_missing_and_invalid_values(self) -> None:
        baseline = render_history_configuration(HistoryConfiguration())
        mutations = {
            "unknown": baseline + "unknown = true\n",
            "missing": baseline.replace("jobs = 1\n", ""),
            "bad jobs": baseline.replace("jobs = 1", "jobs = true"),
            "bad suffix": baseline.replace(
                "excluded_suffixes = []", 'excluded_suffixes = ["py"]'
            ),
            "bad schema": baseline.replace("schema_version = 1", "schema_version = 2"),
        }
        for name, content in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "config.toml").write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_history_configuration(root)

    def test_create_never_overwrites_existing_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            path = create_history_configuration(root, HistoryConfiguration())
            before = path.read_bytes()

            with self.assertRaisesRegex(ValueError, "already exists"):
                create_history_configuration(root, HistoryConfiguration(jobs=8))

            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
