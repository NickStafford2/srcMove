from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS_ROOT = Path(__file__).resolve().parents[1]
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from support.tooling import (
    command_text,
    environment_with_tool,
    find_srcdiff,
    find_srcmove,
    format_process_failure,
    run_command,
)


def make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path.resolve()


class ToolDiscoveryTests(unittest.TestCase):
    def test_explicit_srcmove_wins_over_workspace_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            explicit = make_executable(root / "explicit" / "srcMove")
            _ = make_executable(root / "build" / "srcMove")

            with patch.dict(os.environ, {}, clear=True), patch(
                "support.tooling.shutil.which", return_value=None
            ):
                self.assertEqual(find_srcmove(root, explicit), explicit)

    def test_srcdiff_uses_workspace_build_before_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            workspace = Path(temp_name)
            repo_root = workspace / "srcMove"
            repo_root.mkdir()
            workspace_srcdiff = make_executable(
                workspace / "srcDiff" / "build" / "bin" / "srcdiff"
            )
            path_srcdiff = make_executable(workspace / "path" / "srcdiff")

            with patch.dict(os.environ, {}, clear=True), patch(
                "support.tooling.shutil.which", return_value=str(path_srcdiff)
            ):
                self.assertEqual(find_srcdiff(repo_root), workspace_srcdiff)

    def test_environment_override_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            override = make_executable(root / "override" / "srcMove")

            with patch.dict(
                os.environ, {"SRCMOVE_BIN": str(override)}, clear=True
            ), patch("support.tooling.shutil.which", return_value=None):
                self.assertEqual(find_srcmove(root), override)

    def test_invalid_explicit_path_does_not_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            _ = make_executable(root / "build" / "srcMove")

            with patch.dict(os.environ, {}, clear=True), patch(
                "support.tooling.shutil.which", return_value=None
            ):
                self.assertIsNone(find_srcmove(root, root / "missing" / "srcMove"))


class ProcessHelperTests(unittest.TestCase):
    def test_run_command_captures_text_output(self) -> None:
        result = run_command(["/bin/sh", "-c", "printf output; printf error >&2"])

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "output")
        self.assertEqual(result.stderr, "error")

    def test_failure_format_includes_both_streams(self) -> None:
        result = run_command(
            ["/bin/sh", "-c", "printf output; printf error >&2; exit 7"]
        )

        message = format_process_failure("example", result)
        self.assertIn("example failed", message)
        self.assertIn("exit code: 7", message)
        self.assertIn("output", message)
        self.assertIn("error", message)

    def test_environment_and_log_rendering_preserve_arguments(self) -> None:
        env = environment_with_tool(
            Path("/tmp/example/tool"), {"PATH": "/usr/bin", "KEEP": "yes"}
        )

        self.assertEqual(env["PATH"], "/tmp/example:/usr/bin")
        self.assertEqual(env["KEEP"], "yes")
        self.assertEqual(
            command_text(["tool", "path with spaces"]), "tool 'path with spaces'"
        )


if __name__ == "__main__":
    unittest.main()
