"""Human-readable presentation for repository analysis command results.

The renderers deliberately accept mappings rather than database objects.  This
keeps terminal wording at the command boundary and lets the current flat query
record migrate to the planned nested result model without duplicating output
logic.
"""

from __future__ import annotations

import math
import shlex
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def render_status(summary: Mapping[str, Any]) -> str:
    """Render one read-only analysis snapshot for a person."""

    view = _SummaryView(summary)
    lines = [_heading(view), ""]
    lines.extend(_summary_lines(view))
    _append_failure_hint(lines, view)
    return "\n".join(lines)


def render_run(summary: Mapping[str, Any]) -> str:
    """Render the final summary of a create, resume, or extension run."""

    view = _SummaryView(summary)
    lines = [_heading(view), ""]
    lines.extend(_summary_lines(view))
    _append_failure_hint(lines, view)
    return "\n".join(lines)


def _heading(view: "_SummaryView") -> str:
    states = {
        "target reached with failures": "completed with failures",
        "history exhausted": "end of history reached",
        "running": "running",
        "interrupted": "interrupted",
        "failed": "failed",
    }
    state = states.get(view.state_label)
    return "Repository history" if state is None else f"Repository history — {state}"


def _summary_lines(view: "_SummaryView") -> list[str]:
    lines = [
        _field("Commit pairs", view.coverage_text),
        _field(
            "Outcomes",
            " · ".join(
                (
                    _count(view.analyzed, "compared", "compared"),
                    _count(
                        view.skipped,
                        "without analyzable change",
                        "without analyzable changes",
                    ),
                    _count(view.failed, "failed", "failed"),
                )
            ),
        ),
    ]
    if view.failed:
        lines.append(_field("Failures", view.failure_text))
    lines.append(
        _field(
            "Moves",
            view.moves_text,
        )
    )
    if view.time_text:
        lines.append(_field("Time", view.time_text))
    if view.frontier_text:
        lines.append(_field("Range", view.frontier_text))
    return lines


def _append_failure_hint(lines: list[str], view: "_SummaryView") -> None:
    if not view.failed or not view.root:
        return
    state = Path(view.root)
    command = f"srcmove-history -C {shlex.quote(str(state.parent))}"
    if state.name != ".srcmove":
        command += f" --state-dir {shlex.quote(state.name)}"
    lines.extend(("", f"Inspect: {command} list --failed"))


def _field(label: str, value: str) -> str:
    return f"{label:<10} {value}"


def _count(value: int, singular: str, plural: str) -> str:
    return f"{value} {singular if value == 1 else plural}"


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nonnegative_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return default
        return parsed if parsed >= 0 else default
    return default


def _seconds(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) and result >= 0 else None


def _wall_time(seconds: float) -> str:
    rounded = int(seconds + 0.5)
    hours, remainder = divmod(rounded, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {remaining_seconds:02d}s"
    if minutes:
        return f"{minutes}m {remaining_seconds:02d}s"
    return f"{remaining_seconds}s"


def _abbreviate(commit: str | None) -> str | None:
    return None if not commit else commit[:8]


def _state_words(state: str) -> str:
    return state.strip().lower().replace("-", " ").replace("_", " ")


class _SummaryView:
    def __init__(self, summary: Mapping[str, Any]) -> None:
        self.summary = summary
        self.analysis = _mapping(summary.get("analysis"))
        self.coverage = _mapping(summary.get("coverage"))
        self.outcomes = _mapping(summary.get("outcomes"))
        self.moves = _mapping(summary.get("moves"))
        self.timings = _mapping(summary.get("timings"))
        self.invocation = _mapping(summary.get("invocation"))

        root = self.analysis.get(
            "root", summary.get("analysis_root", summary.get("root"))
        )
        self.root = str(root) if root is not None else ""
        supplied_name = self.analysis.get(
            "name", summary.get("name", summary.get("repository_id"))
        )
        if supplied_name is None and self.root:
            supplied_name = Path(self.root).name
        self.name = str(supplied_name) if supplied_name is not None else "Repository"

        self.committed = _nonnegative_int(
            self.coverage.get("committed", summary.get("completed_pair_count"))
        )
        self.checkpointed = _nonnegative_int(
            self.coverage.get("checkpointed", summary.get("checkpointed_pair_count"))
        )
        durable = self.coverage.get("durable", summary.get("durable_pair_count"))
        self.durable = _nonnegative_int(
            durable, default=self.committed + self.checkpointed
        )
        self.target = self._target_value()
        self.history_exhausted = bool(summary.get("history_exhausted"))

        statuses = _mapping(summary.get("statuses"))
        self.analyzed = _nonnegative_int(
            self.outcomes.get(
                "analyzed", summary.get("completed", statuses.get("completed"))
            )
        )
        self.skipped = _nonnegative_int(
            self.outcomes.get(
                "skipped",
                summary.get(
                    "no_analyzable_change", statuses.get("no_analyzable_change")
                ),
            )
        )
        self.failed = _nonnegative_int(
            self.outcomes.get("failed", summary.get("failed")),
            default=sum(
                _nonnegative_int(count)
                for status, count in statuses.items()
                if str(status).endswith("_failed")
            ),
        )
        self.failure_counts = tuple(
            (str(status), _nonnegative_int(count))
            for status, count in statuses.items()
            if str(status).endswith("_failed") and _nonnegative_int(count)
        )

        self.move_groups = _nonnegative_int(
            self.moves.get("groups", summary.get("move_group_count"))
        )
        self.move_pairs = _nonnegative_int(
            self.moves.get("pairs", summary.get("move_pair_count"))
        )
        self.annotated_regions = _nonnegative_int(
            self.moves.get("annotated_regions", summary.get("annotated_region_count"))
        )
        move_types = _mapping(
            self.moves.get("by_type", summary.get("match_kinds"))
        )
        self.move_types = {
            str(name): _nonnegative_int(count)
            for name, count in move_types.items()
        }

    def _target_value(self) -> int | None:
        nested_target = self.coverage.get("target")
        if nested_target is None:
            target = _mapping(self.summary.get("target"))
            nested_target = target.get("value")
            target_kind = target.get("kind")
        else:
            target_kind = "pairs"
        if nested_target is None:
            nested_target = self.invocation.get("target_value")
            target_kind = self.invocation.get("target_kind")
        if target_kind not in (None, "pairs", "total_pairs"):
            return None
        if nested_target is None:
            return None
        parsed = _nonnegative_int(nested_target, default=-1)
        return parsed if parsed >= 0 else None

    @property
    def state_label(self) -> str:
        explicit = self.summary.get("state")
        if isinstance(explicit, str) and explicit.strip():
            return _state_words(explicit)
        if self.summary.get("writer_active") or self.summary.get("running"):
            return "running"
        result = self.invocation.get("result")
        if isinstance(result, str):
            words = _state_words(result)
            if words in {
                "target reached",
                "target reached with failures",
                "history exhausted",
                "interrupted",
                "idle",
                "failed",
                "running",
            }:
                return words
        if self.summary.get("history_exhausted") and (
            self.target is None or self.durable < self.target
        ):
            return "history exhausted"
        if self.target is not None and self.durable >= self.target:
            return "target reached with failures" if self.failed else "target reached"
        if self.invocation and self.invocation.get("ended_at") is None:
            return "interrupted"
        if result in ("error", "failed") or self.invocation.get("error"):
            return "failed"
        return "idle"

    @property
    def coverage_text(self) -> str:
        result = f"{self.durable} processed"
        details: list[str] = []
        if self.target is not None:
            details.append(f"target {self.target}")
        if self.history_exhausted:
            details.append("end of history reached")
        elif self.target is not None and self.durable >= self.target:
            details.append("more history remains")
        return result if not details else f"{result} ({'; '.join(details)})"

    @property
    def moves_text(self) -> str:
        parts = [_count(self.move_groups, "detected", "detected")]
        labels = {"exact": "exact", "type2": "Type 2", "type3": "Type 3"}
        for name in ("exact", "type2", "type3"):
            count = self.move_types.get(name, 0)
            if count:
                parts.append(f"{count} {labels[name]}")
        for name, count in sorted(self.move_types.items()):
            if name not in labels and count:
                parts.append(f"{count} {name}")
        return " · ".join(parts)

    @property
    def failure_text(self) -> str:
        if not self.failure_counts:
            return _count(self.failed, "failure", "failures")
        labels = {
            "export_failed": "export",
            "srcdiff_failed": "srcDiff",
            "srcmove_failed": "srcMove",
            "orchestration_failed": "orchestration",
        }
        return " · ".join(
            f"{count} "
            f"{labels.get(status, status.removesuffix('_failed').replace('_', ' '))}"
            for status, count in sorted(self.failure_counts)
        )

    @property
    def time_text(self) -> str:
        wall = _seconds(
            self.timings.get(
                "cumulative_wall_seconds",
                self.summary.get(
                    "cumulative_wall_seconds",
                    self.invocation.get(
                        "wall_seconds", self.summary.get("wall_seconds")
                    ),
                ),
            )
        )
        srcdiff = _seconds(self.timings.get("srcdiff_seconds"))
        srcmove = _seconds(self.timings.get("srcmove_seconds"))
        parts: list[str] = []
        if wall is not None:
            parts.append(f"{_wall_time(wall)} elapsed")
        if srcdiff is not None:
            parts.append(f"{_wall_time(srcdiff)} srcDiff")
        if srcmove is not None:
            parts.append(f"{_wall_time(srcmove)} srcMove")
        return " · ".join(parts)

    @property
    def frontier_text(self) -> str:
        newest = self.summary.get("newest_commit")
        oldest = self.summary.get(
            "oldest_completed_commit", self.summary.get("frontier_commit")
        )
        abbreviated_newest = _abbreviate(str(newest)) if newest else None
        abbreviated_oldest = _abbreviate(str(oldest)) if oldest else None
        if abbreviated_newest and abbreviated_oldest:
            return (
                f"newest {abbreviated_newest} · "
                f"oldest {abbreviated_oldest}"
            )
        return abbreviated_newest or abbreviated_oldest or ""
