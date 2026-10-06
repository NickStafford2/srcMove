from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from srcmove_history.benchmarks.reference_repositories import (
    ensure_reference_repository,
    load_reference_configuration,
    normalize_repository_subdirectory,
)


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class ReferenceRepositoryTests(unittest.TestCase):
    def test_checked_in_registry_has_documented_repositories(self) -> None:
        registry = REPO_ROOT / "reference-repositories/repositories.json"
        for name in (
            "sqlite",
            "notepadpp",
            "opencv",
            "linux",
            "open-nicad",
            "deckard",
            "sourcerercc",
            "gumtree",
        ):
            configuration = load_reference_configuration(registry, name)
            self.assertTrue(configuration.url)
            self.assertTrue(configuration.checkout)

    def test_reference_implementations_are_reference_only(self) -> None:
        registry = REPO_ROOT / "reference-repositories/repositories.json"
        for name in ("open-nicad", "deckard", "sourcerercc", "gumtree"):
            configuration = load_reference_configuration(registry, name)
            self.assertEqual(configuration.roles, ("reference",))

    def test_configuration_contains_only_reference_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "repositories.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "repositories": {
                            "project": {
                                "checkout": "project",
                                "url": "https://example.invalid/project.git",
                                "analysis_directory": "src/core",
                                "roles": ["history"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            configuration = load_reference_configuration(path, "project")

            self.assertEqual(configuration.name, "project")
            self.assertEqual(
                configuration.url, "https://example.invalid/project.git"
            )
            self.assertEqual(configuration.checkout, "project")
            self.assertEqual(configuration.analysis_directory, "src/core")
            self.assertEqual(configuration.roles, ("history",))

    def test_repository_subdirectory_must_remain_inside_repository(self) -> None:
        self.assertEqual(normalize_repository_subdirectory("/src/", "test"), "src")
        self.assertIsNone(normalize_repository_subdirectory(".", "test"))
        with self.assertRaisesRegex(RuntimeError, "stay within"):
            normalize_repository_subdirectory("../outside", "test")

    def test_reference_clone_can_be_prepared_and_reused_offline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            source.mkdir()
            git(source, "init", "--initial-branch=main")
            git(source, "config", "user.name", "Reference Test")
            git(source, "config", "user.email", "reference@example.invalid")
            (source / "sample.c").write_text("int value;\n", encoding="utf-8")
            git(source, "add", "sample.c")
            git(source, "commit", "-m", "initial")
            remote = root / "remote.git"
            subprocess.run(
                ["git", "clone", "--bare", str(source), str(remote)],
                check=True,
                capture_output=True,
                text=True,
            )
            clone = root / "references" / "project"

            self.assertTrue(
                ensure_reference_repository(
                    str(remote), clone, offline=False, update=False
                )
            )
            self.assertFalse(
                ensure_reference_repository(
                    str(remote), clone, offline=True, update=False
                )
            )

    def test_offline_mode_rejects_a_missing_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "missing"
            with self.assertRaisesRegex(RuntimeError, "missing in offline mode"):
                ensure_reference_repository(
                    "https://example.invalid/project.git",
                    destination,
                    offline=True,
                    update=False,
                )


if __name__ == "__main__":
    unittest.main()
