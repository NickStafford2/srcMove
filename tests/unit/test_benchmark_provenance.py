from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RECEIPT_EMITTER = REPO_ROOT / "benchmarks" / "emit_build_receipt.py"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.contracts import RunMode
from benchmarks.provenance import (
    build_receipt_identifier,
    collect_run_observation,
    observe_executable,
    observe_repository,
    sha256_file,
)


def run_git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        check=True,
    )


def create_repository(root: Path) -> Path:
    repository = root / "repository"
    repository.mkdir()
    run_git(repository, "init", "--quiet")
    run_git(repository, "config", "user.name", "Benchmark Test")
    run_git(repository, "config", "user.email", "benchmark@example.invalid")
    (repository / "source.cpp").write_text("int value = 1;\n", encoding="utf-8")
    run_git(repository, "add", "source.cpp")
    run_git(repository, "commit", "--quiet", "-m", "initial")
    return repository


def write_receipt(path: Path, artifact: Path, checksum: str) -> None:
    artifacts = [
        {
            "name": artifact.name,
            "sha256": checksum,
            "size_bytes": artifact.stat().st_size,
        }
    ]
    build = {
        "entry_point": "test",
        "configuration": "Debug",
        "cmake_options": {},
        "compiler": {"id": "TestCompiler", "version": "1.0"},
    }
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "receipt_id": build_receipt_identifier(
                    sources={},
                    source_lock=None,
                    build=build,
                    artifacts=artifacts,
                ),
                "artifacts": artifacts,
                "sources": {},
                "source_lock": None,
                "build": build,
                "tests": {"status": "not_run"},
            }
        ),
        encoding="utf-8",
    )


class RepositoryObservationTests(unittest.TestCase):
    def test_clean_dirty_and_missing_repositories_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = create_repository(root)

            clean = observe_repository(repository)
            self.assertEqual(clean["status"], "observed")
            self.assertFalse(clean["tracked_dirty"])
            self.assertEqual(clean["untracked_sources"], [])

            (repository / "source.cpp").write_text(
                "int value = 2;\n", encoding="utf-8"
            )
            dirty = observe_repository(repository)
            self.assertTrue(dirty["tracked_dirty"])
            self.assertIsNotNone(dirty["tracked_diff_sha256"])

            missing = observe_repository(root / "missing")
            self.assertEqual(missing["status"], "unavailable")

    def test_relevant_untracked_sources_include_content_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = create_repository(Path(temporary_directory))
            (repository / "new.hpp").write_text("int added;\n", encoding="utf-8")
            (repository / "scratch.bin").write_bytes(b"ignored by source inventory")

            observation = observe_repository(repository)

            self.assertEqual(
                [entry["path"] for entry in observation["untracked_sources"]],
                ["new.hpp"],
            )
            self.assertEqual(
                observation["untracked_sources"][0]["sha256"],
                sha256_file(repository / "new.hpp"),
            )


class ExecutableProvenanceTests(unittest.TestCase):
    def test_verified_stale_unverified_unavailable_and_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            executable = root / "srcMove"
            executable.write_bytes(b"binary version one")
            receipt = root / "receipt.json"

            no_receipt = observe_executable(executable, receipt)
            self.assertEqual(no_receipt["provenance_status"], "unverified")
            self.assertEqual(no_receipt["receipt_validation"], "missing")

            receipt.write_text("not json", encoding="utf-8")
            malformed = observe_executable(executable, receipt)
            self.assertEqual(malformed["provenance_status"], "unverified")
            self.assertEqual(malformed["receipt_validation"], "malformed")

            write_receipt(receipt, executable, sha256_file(executable))
            verified = observe_executable(executable, receipt)
            self.assertEqual(verified["provenance_status"], "verified")

            executable.write_bytes(b"binary version two")
            stale = observe_executable(executable, receipt)
            self.assertEqual(stale["provenance_status"], "stale")

            unavailable = observe_executable(root / "missing", receipt)
            self.assertEqual(unavailable["provenance_status"], "unavailable")


class BuildReceiptTests(unittest.TestCase):
    def test_emitter_creates_a_stable_valid_receipt_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = create_repository(root)
            executable = root / "srcMove"
            executable.write_bytes(b"linked srcMove")
            receipt = root / "srcMove.build-receipt.json"
            source_lock = root / "workspace.lock.json"
            source_lock.write_text('{"schema_version": 1}\n', encoding="utf-8")
            command = [
                sys.executable,
                str(RECEIPT_EMITTER),
                "--output",
                str(receipt),
                "--artifact",
                str(executable),
                "--repository",
                f"srcMove={repository}",
                "--source-lock",
                str(source_lock),
                "--build-entry-point",
                "cmake --build <build-dir> --target srcMove",
                "--configuration",
                "Release",
                "--cmake-options",
                '{"cxx_standard":"17"}',
                "--compiler-id",
                "TestCompiler",
                "--compiler-version",
                "1.0",
            ]

            first = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(first.returncode, 0, first.stderr)
            first_receipt = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(first_receipt["tests"]["status"], "not_run")
            self.assertEqual(
                observe_executable(executable, receipt)["provenance_status"],
                "verified",
            )

            second = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(second.returncode, 0, second.stderr)
            second_receipt = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(
                first_receipt["receipt_id"], second_receipt["receipt_id"]
            )
            self.assertEqual(list(root.glob(".*.tmp-*")), [])

    def test_run_observation_keeps_binary_verification_separate_from_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = create_repository(root)
            executable = root / "srcMove"
            executable.write_bytes(b"linked srcMove")
            receipt = Path(f"{executable}.build-receipt.json")
            input_xml = root / "input.xml"
            input_xml.write_text("<unit/>\n", encoding="utf-8")

            command = [
                sys.executable,
                str(RECEIPT_EMITTER),
                "--output",
                str(receipt),
                "--artifact",
                str(executable),
                "--repository",
                f"srcMove={repository}",
                "--build-entry-point",
                "cmake --build <build-dir> --target srcMove",
                "--configuration",
                "Debug",
                "--compiler-id",
                "TestCompiler",
                "--compiler-version",
                "1.0",
            ]
            subprocess.run(command, capture_output=True, check=True)
            (repository / "source.cpp").write_text(
                "int value = 2;\n", encoding="utf-8"
            )

            observation = collect_run_observation(
                mode=RunMode.DEVELOPMENT,
                repositories={"srcMove": repository},
                executables={"srcMove": executable},
                inputs={"srcdiff": input_xml},
            )

            binary = observation["executables"]["srcMove"]
            self.assertEqual(binary["provenance_status"], "verified")
            self.assertEqual(
                binary["current_source_relationships"]["srcMove"], "differs"
            )
            self.assertEqual(observation["mode"], "development")
            self.assertTrue(
                observation["environment"]["environment_id"].startswith(
                    "environment-sha256-"
                )
            )
            self.assertEqual(
                observation["inputs"]["srcdiff"]["sha256"], sha256_file(input_xml)
            )


if __name__ == "__main__":
    unittest.main()
