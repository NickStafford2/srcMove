"""Shared executable discovery and process helpers for srcMove tooling.

Test and benchmark runners should use this module instead of defining their own
PATH searches or ``subprocess.run`` wrappers.  Keeping this policy in one place
makes every entry point select the same workspace binaries and report command
failures consistently.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path


Command = Sequence[str | os.PathLike[str]]


def _existing_executable(path: Path | None) -> Path | None:
    if path is None:
        return None
    resolved = path.expanduser().resolve()
    return resolved if resolved.is_file() and os.access(resolved, os.X_OK) else None


def _from_environment(variable: str) -> Path | None:
    value = os.environ.get(variable)
    return _existing_executable(Path(value)) if value else None


def _from_path(name: str) -> Path | None:
    value = shutil.which(name)
    return _existing_executable(Path(value)) if value else None


def find_srcmove(repo_root: Path, explicit: Path | None = None) -> Path | None:
    """Find srcMove using one stable precedence order.

    Explicit CLI input wins, followed by ``SRCMOVE_BIN``, the normal workspace
    build directories, and finally ``PATH``.
    """

    if explicit is not None:
        return _existing_executable(explicit)
    if "SRCMOVE_BIN" in os.environ:
        return _from_environment("SRCMOVE_BIN")

    candidates = (
        _existing_executable(repo_root / "build" / "srcMove"),
        _existing_executable(repo_root / "build-release" / "srcMove"),
        _from_path("srcMove"),
    )
    return next((candidate for candidate in candidates if candidate is not None), None)


def find_srcdiff(repo_root: Path, explicit: Path | None = None) -> Path | None:
    """Find srcdiff using the sibling workspace before falling back to PATH."""

    if explicit is not None:
        return _existing_executable(explicit)
    if "SRCDIFF_BIN" in os.environ:
        return _from_environment("SRCDIFF_BIN")

    workspace_root = repo_root.parent
    candidates = (
        _existing_executable(workspace_root / "srcDiff" / "build" / "bin" / "srcdiff"),
        _existing_executable(workspace_root / "srcDiff-install" / "bin" / "srcdiff"),
        _existing_executable(
            workspace_root / "srcDiff" / "build-release-check" / "bin" / "srcdiff"
        ),
        _from_path("srcdiff"),
    )
    return next((candidate for candidate in candidates if candidate is not None), None)


def environment_with_tool(tool: Path, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return an environment with ``tool``'s directory first on PATH."""

    env = dict(os.environ if base is None else base)
    current_path = env.get("PATH", "")
    env["PATH"] = str(tool.parent) + (os.pathsep + current_path if current_path else "")
    return env


def command_text(command: Command) -> str:
    """Render a command for logs without losing argument boundaries."""

    return shlex.join(os.fspath(part) for part in command)


def run_command(
    command: Command,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a text-mode command without raising for a nonzero exit status."""

    return subprocess.run(
        [os.fspath(part) for part in command],
        cwd=cwd,
        env=dict(env) if env is not None else None,
        text=True,
        capture_output=capture_output,
        check=False,
    )


def format_process_failure(
    label: str,
    result: subprocess.CompletedProcess[str],
    extra: str = "",
) -> str:
    """Format a failed process consistently for test and benchmark output."""

    parts = [f"{label} failed"]
    if extra:
        parts.append(extra)
    parts.append(f"exit code: {result.returncode}")

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if stdout:
        parts.append("stdout:")
        parts.extend(f"  {line}" for line in stdout.splitlines())
    if stderr:
        parts.append("stderr:")
        parts.extend(f"  {line}" for line in stderr.splitlines())
    return "\n".join(parts)


def print_process_failure(
    label: str,
    result: subprocess.CompletedProcess[str],
    extra: str = "",
    *,
    indent: str = "  ",
) -> None:
    """Print ``format_process_failure`` with a consistent indentation."""

    for line in format_process_failure(label, result, extra).splitlines():
        print(f"{indent}{line}")
