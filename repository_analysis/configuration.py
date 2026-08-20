"""Editable repository-local configuration for repository history analysis."""

from __future__ import annotations

import json
import os
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .inputs import AnalysisConfiguration


CONFIG_FILE_NAME = "config.toml"
CONFIG_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class HistoryConfiguration:
    analysis: AnalysisConfiguration = AnalysisConfiguration()
    jobs: int = 1

    def __post_init__(self) -> None:
        if (
            isinstance(self.jobs, bool)
            or not isinstance(self.jobs, int)
            or self.jobs <= 0
        ):
            raise ValueError("configuration run.jobs must be a positive integer")


def load_history_configuration(analysis_root: Path) -> HistoryConfiguration:
    path = analysis_root / CONFIG_FILE_NAME
    if path.is_symlink() or not path.is_file():
        raise ValueError(
            f"repository analysis is not initialized: {path}; "
            "run srcmove-history init first"
        )
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"repository-analysis configuration is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"repository-analysis configuration must be a TOML table: {path}")
    _require_fields(value, {"schema_version", "analysis", "run"}, "configuration")
    schema_version = value["schema_version"]
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != CONFIG_SCHEMA_VERSION
    ):
        raise ValueError(
            f"unsupported repository-analysis configuration schema: "
            f"{schema_version!r}"
        )
    analysis = _table(value["analysis"], "analysis")
    _require_fields(
        analysis,
        {
            "selected_directory",
            "excluded_suffixes",
            "use_position",
            "source_encoding",
            "srcdiff_timeout_seconds",
            "srcmove_timeout_seconds",
        },
        "analysis",
    )
    suffixes = analysis["excluded_suffixes"]
    if not isinstance(suffixes, list):
        raise ValueError("configuration analysis.excluded_suffixes must be an array")
    selected_directory = analysis["selected_directory"]
    if not isinstance(selected_directory, str):
        raise ValueError("configuration analysis.selected_directory must be a string")
    frozen = AnalysisConfiguration(
        selected_directory=selected_directory,
        excluded_suffixes=tuple(suffixes),
        use_position=analysis["use_position"],
        source_encoding=analysis["source_encoding"],
        srcdiff_timeout_seconds=analysis["srcdiff_timeout_seconds"],
        srcmove_timeout_seconds=analysis["srcmove_timeout_seconds"],
    )
    run = _table(value["run"], "run")
    _require_fields(run, {"jobs"}, "run")
    return HistoryConfiguration(analysis=frozen, jobs=run["jobs"])


def create_history_configuration(
    analysis_root: Path, configuration: HistoryConfiguration
) -> Path:
    path = analysis_root / CONFIG_FILE_NAME
    if path.exists() or path.is_symlink():
        raise ValueError(f"repository-analysis configuration already exists: {path}")
    temporary = analysis_root / f".{CONFIG_FILE_NAME}.tmp-{uuid.uuid4().hex}"
    try:
        with temporary.open("xb") as stream:
            stream.write(render_history_configuration(configuration).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(analysis_root)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def render_history_configuration(configuration: HistoryConfiguration) -> str:
    analysis = configuration.analysis
    lines = [
        "# Edit analysis settings before the first run. Afterward they are frozen.",
        f"schema_version = {CONFIG_SCHEMA_VERSION}",
        "",
        "[analysis]",
    ]
    selected_directory = analysis.selected_directory or "."
    lines.append(f"selected_directory = {_toml_string(selected_directory)}")
    suffixes = ", ".join(_toml_string(value) for value in analysis.excluded_suffixes)
    lines.extend(
        (
            f"excluded_suffixes = [{suffixes}]",
            f"use_position = {_toml_boolean(analysis.use_position)}",
            f"source_encoding = {_toml_string(analysis.source_encoding)}",
            f"srcdiff_timeout_seconds = {analysis.srcdiff_timeout_seconds}",
            f"srcmove_timeout_seconds = {analysis.srcmove_timeout_seconds}",
            "",
            "# Run settings remain editable after analysis begins.",
            "[run]",
            f"jobs = {configuration.jobs}",
            "",
        )
    )
    return "\n".join(lines)


def _require_fields(
    value: dict[str, Any],
    required: set[str],
    context: str,
    *,
    optional: set[str] | None = None,
) -> None:
    allowed = required | (optional or set())
    missing = required - set(value)
    unknown = set(value) - allowed
    if missing:
        raise ValueError(f"configuration {context} is missing: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(
            f"configuration {context} contains unknown fields: "
            + ", ".join(sorted(unknown))
        )


def _table(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"configuration {context} must be a table")
    return value


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_boolean(value: bool) -> str:
    return "true" if value else "false"


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
