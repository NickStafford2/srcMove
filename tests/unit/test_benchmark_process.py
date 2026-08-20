from __future__ import annotations

import json
import hashlib
import signal
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FAKE_TOOL = REPO_ROOT / "tests" / "fixtures" / "benchmark" / "fake_tool.py"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.process import (
    execute_attempt,
    recover_interrupted_attempts,
    validate_srcdiff_xml,
    write_json_atomic,
)


def fake_command(outcome: str):
    return lambda output: [
        sys.executable,
        str(FAKE_TOOL),
        outcome,
        "--output",
        str(output),
    ]


def single_file_validator(path: Path):
    return validate_srcdiff_xml(path, "single_file")


class ProcessAttemptTests(unittest.TestCase):
    def run_attempt(self, root: Path, outcome: str, **overrides):
        arguments = {
            "attempts_root": root / "attempts",
            "stage": "srcdiff",
            "case_id": "tiny",
            "command_factory": fake_command(outcome),
            "cwd": root,
            "timeout_seconds": 2.0,
            "timeout_grace_seconds": 0.05,
            "xml_validator": single_file_validator,
            "output_filename": "partial.srcdiff.xml",
        }
        arguments.update(overrides)
        return execute_attempt(**arguments)

    def test_success_is_admitted_with_atomic_terminal_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            attempt_dir, attempt = self.run_attempt(
                Path(temporary_directory), "valid-single"
            )

            self.assertTrue(attempt["admitted"])
            self.assertEqual(attempt["termination"], {"status": "exited", "exit_code": 0})
            self.assertEqual(attempt["xml"]["status"], "valid")
            self.assertTrue((attempt_dir / "attempt.json").is_file())
            self.assertFalse((attempt_dir / "started.json").exists())
            self.assertEqual(list(attempt_dir.glob(".attempt.json.tmp-*")), [])
            self.assertIn(
                attempt["resource_usage"]["peak_rss_status"],
                {"observed", "unavailable"},
            )

    def test_process_and_xml_failures_remain_distinct(self) -> None:
        outcomes = {
            "nonzero": ("exited", "missing"),
            "signal": ("signaled", "missing"),
            "missing-output": ("exited", "missing"),
            "empty-output": ("exited", "empty"),
            "malformed": ("exited", "malformed"),
            "invalid-structure": ("exited", "invalid_structure"),
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for outcome, (termination, xml) in outcomes.items():
                with self.subTest(outcome=outcome):
                    _, attempt = self.run_attempt(root, outcome)
                    self.assertFalse(attempt["admitted"])
                    self.assertEqual(attempt["termination"]["status"], termination)
                    self.assertEqual(attempt["xml"]["status"], xml)

    def test_sigkill_is_not_assumed_to_be_out_of_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            _, attempt = self.run_attempt(Path(temporary_directory), "sigkill")

            self.assertEqual(attempt["termination"]["signal_number"], signal.SIGKILL)
            self.assertEqual(
                attempt["resource_failure"], "unknown_resource_failure"
            )

    def test_spawn_failure_has_a_terminal_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            attempt_dir, attempt = execute_attempt(
                attempts_root=root / "attempts",
                stage="srcdiff",
                case_id="spawn",
                command_factory=lambda output: [
                    str(root / "does-not-exist"),
                    str(output),
                ],
                cwd=root,
                timeout_seconds=1.0,
                xml_validator=single_file_validator,
                output_filename="partial.srcdiff.xml",
            )

            self.assertEqual(attempt["termination"]["status"], "spawn_failed")
            self.assertTrue((attempt_dir / "attempt.json").is_file())

    def test_timeout_force_kills_the_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            _, attempt = self.run_attempt(
                Path(temporary_directory),
                "timeout-tree",
                timeout_seconds=0.5,
                timeout_grace_seconds=0.05,
            )

            self.assertEqual(attempt["termination"]["status"], "timed_out")
            self.assertEqual(
                [entry["name"] for entry in attempt["cleanup_signals"]],
                ["SIGTERM", "SIGKILL"],
            )

    def test_logs_are_bounded_but_describe_the_full_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            script = root / "large_output.py"
            valid_xml = (
                "<unit xmlns='http://www.srcML.org/srcML/src' "
                "xmlns:diff='http://www.srcML.org/srcDiff'/>"
            )
            script.write_text(
                "import os,sys\n"
                "from pathlib import Path\n"
                f"Path(sys.argv[1]).write_text({valid_xml!r})\n"
                "os.write(1, b'a' * 200)\n"
                "os.write(2, b'b' * 180)\n",
                encoding="utf-8",
            )
            attempt_dir, attempt = execute_attempt(
                attempts_root=root / "attempts",
                stage="srcdiff",
                case_id="logs",
                command_factory=lambda output: [sys.executable, str(script), str(output)],
                cwd=root,
                timeout_seconds=2.0,
                xml_validator=single_file_validator,
                output_filename="partial.srcdiff.xml",
                log_limit=40,
            )

            self.assertEqual(attempt["stdout"]["total_bytes"], 200)
            self.assertEqual(attempt["stdout"]["retained_bytes"], 40)
            self.assertEqual(attempt["stdout"]["omitted_bytes"], 160)
            self.assertTrue(attempt["stdout"]["truncated"])
            self.assertEqual(
                attempt["stdout"]["sha256"], hashlib.sha256(b"a" * 200).hexdigest()
            )
            self.assertEqual((attempt_dir / "stdout.bin").read_bytes(), b"a" * 40)
            self.assertEqual(attempt["stderr"]["total_bytes"], 180)

    def test_abandoned_staging_is_recovered_but_never_admitted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            attempts = Path(temporary_directory) / "attempts"
            abandoned = attempts / "attempt-abandoned"
            abandoned.mkdir(parents=True)
            write_json_atomic(
                abandoned / "started.json",
                {
                    "schema_version": 1,
                    "attempt_id": "attempt-abandoned",
                    "case_id": "tiny",
                },
            )
            (abandoned / "partial.srcdiff.xml").write_text(
                "<unit/>", encoding="utf-8"
            )

            self.assertEqual(
                recover_interrupted_attempts(attempts), ["attempt-abandoned"]
            )
            recovered = json.loads(
                (abandoned / "attempt.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                recovered["termination"]["status"], "orchestration_interrupted"
            )
            self.assertFalse(recovered["admitted"])


if __name__ == "__main__":
    unittest.main()
