"""Durable, terminal-aware progress for repository history analysis."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import shutil
import sys
import threading
import time
from typing import Protocol, TextIO

from .contracts import PairStatus


_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_FAILED_STATUSES = frozenset(
    status.value
    for status in PairStatus
    if status not in (PairStatus.COMPLETED, PairStatus.NO_ANALYZABLE_CHANGE)
)
_FINISH_RESULTS = frozenset(
    {
        "complete",
        "complete_with_failures",
        "history_exhausted",
        "history_exhausted_with_failures",
        "interrupted",
        "failed",
    }
)


@dataclass(frozen=True, slots=True)
class AnalysisProgressStart:
    """Immutable durable counters at the start of an invocation."""

    name: str
    target_total: int | None
    covered: int
    analyzed: int
    skipped: int
    failed: int
    moves: int
    jobs: int

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("analysis name must be non-empty")
        values = (
            self.covered,
            self.analyzed,
            self.skipped,
            self.failed,
            self.moves,
        )
        if any(value < 0 for value in values):
            raise ValueError("progress counters must be non-negative")
        if self.target_total is not None and self.target_total < 0:
            raise ValueError("progress target must be non-negative")
        if self.jobs <= 0:
            raise ValueError("worker count must be positive")


@dataclass(frozen=True, slots=True)
class PairPublished:
    """A pair outcome that has crossed the durable publication boundary."""

    covered: int
    status: PairStatus | str
    move_count: int = 0

    def __post_init__(self) -> None:
        if self.covered < 0:
            raise ValueError("covered pair count must be non-negative")
        if self.move_count < 0:
            raise ValueError("move count must be non-negative")


class AnalysisObserver(Protocol):
    """Observe progress without participating in analysis control flow."""

    def analysis_started(self, event: AnalysisProgressStart) -> None: ...

    def pair_published(self, event: PairPublished) -> None: ...

    def analysis_finished(
        self, *, result: str = "complete", detail: str | None = None
    ) -> None: ...


class NullAnalysisObserver:
    """No-op observer for library callers and tests that do not need progress."""

    def analysis_started(self, event: AnalysisProgressStart) -> None:
        pass

    def pair_published(self, event: PairPublished) -> None:
        pass

    def analysis_finished(
        self, *, result: str = "complete", detail: str | None = None
    ) -> None:
        pass


class TerminalAnalysisObserver:
    """Show live TTY progress or sparse durable progress when redirected.

    The display advances only in :meth:`pair_published`. Output failures are
    deliberately contained so presentation cannot interrupt analysis.
    """

    def __init__(
        self,
        *,
        stream: TextIO | None = None,
        enabled: bool = True,
        refresh_seconds: float = 0.1,
        log_interval_seconds: float = 30.0,
    ) -> None:
        if refresh_seconds <= 0 or log_interval_seconds <= 0:
            raise ValueError("progress intervals must be positive")
        self.stream = stream if stream is not None else sys.stderr
        self.enabled = enabled
        self.refresh_seconds = refresh_seconds
        # An active redirected run must communicate at least every 30 seconds.
        self.log_interval_seconds = min(log_interval_seconds, 30.0)

        self.name = "history"
        self.target_total: int | None = None
        self.covered = 0
        self.analyzed = 0
        self.skipped = 0
        self.failed = 0
        self.moves = 0
        self.jobs = 0

        self._entered = False
        self._started = False
        self._finished = False
        self._io_failed = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._entered_at = 0.0
        self._last_log_at = 0.0
        self._last_bucket = -1
        self._samples: deque[tuple[float, int]] = deque(maxlen=64)
        try:
            self._live = bool(self.stream.isatty())
        except Exception:
            self._live = False

    def __enter__(self) -> "TerminalAnalysisObserver":
        with self._lock:
            if self._entered:
                return self
            self._entered = True
            self._entered_at = time.monotonic()
            self._last_log_at = self._entered_at
            if self.enabled:
                if self._live:
                    self._render_live_locked(self._entered_at)
                else:
                    self._write_locked("[history] preparing: 00:00\n")
        if self.enabled:
            self._thread = threading.Thread(
                target=self._refresh,
                name="repository-analysis-progress",
                daemon=True,
            )
            self._thread.start()
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        if exception is None:
            self.analysis_finished()
        else:
            self.analysis_finished(
                result=(
                    "interrupted"
                    if exception_type is not None
                    and issubclass(exception_type, KeyboardInterrupt)
                    else "failed"
                ),
                detail=str(exception),
            )

    def analysis_started(self, event: AnalysisProgressStart) -> None:
        # Supporting use without a context manager makes the observer harder to
        # misuse while preserving immediate preparation output in normal use.
        if not self._entered:
            self.__enter__()
        now = time.monotonic()
        with self._lock:
            if self._finished:
                return
            self.name = event.name
            self.target_total = event.target_total
            self.covered = event.covered
            self.analyzed = event.analyzed
            self.skipped = event.skipped
            self.failed = event.failed
            self.moves = event.moves
            self.jobs = event.jobs
            self._started = True
            self._samples.clear()
            self._samples.append((now, event.covered))
            self._last_bucket = self._bucket(event.covered)
            if self.enabled:
                if self._live:
                    self._render_live_locked(now)
                else:
                    self._write_log_locked("started", now)

    def pair_published(self, event: PairPublished) -> None:
        now = time.monotonic()
        with self._lock:
            if self._finished:
                return
            self.covered = max(self.covered, event.covered)
            status = (
                event.status.value
                if isinstance(event.status, PairStatus)
                else str(event.status)
            )
            if status == PairStatus.COMPLETED.value:
                self.analyzed += 1
            elif status == PairStatus.NO_ANALYZABLE_CHANGE.value:
                self.skipped += 1
            elif status in _FAILED_STATUSES or status:
                self.failed += 1
            self.moves += event.move_count
            self._samples.append((now, self.covered))
            while len(self._samples) > 2 and now - self._samples[0][0] > 120.0:
                self._samples.popleft()

            should_log = not self._live and self._crossed_milestone_locked()
            if self.enabled:
                if self._live:
                    self._render_live_locked(now)
                elif should_log:
                    self._write_log_locked("progress", now)

    def analysis_finished(
        self, *, result: str = "complete", detail: str | None = None
    ) -> None:
        if result not in _FINISH_RESULTS:
            raise ValueError(f"unknown progress finish result: {result!r}")
        with self._lock:
            if self._finished:
                return
            self._finished = True
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)

        now = time.monotonic()
        with self._lock:
            if not self.enabled or self._io_failed:
                return
            elapsed = _elapsed(now - (self._entered_at or now))
            detail_text = f" — {detail}" if detail else ""
            counters = self._counter_detail() if self._started else ""
            counter_text = f" — {counters}" if counters else ""
            icon = "✓" if result in {"complete", "history_exhausted"} else "!"
            if result == "failed":
                icon = "✗"
            label = result.replace("_", " ")
            if self._live:
                line = (
                    f"{icon} Analysis {self.name} {label}: {self._count_text()} "
                    f"in {elapsed}{counter_text}{detail_text}"
                )
                self._write_locked(f"\r\033[2K{self._truncate(line)}\n")
            else:
                self._write_locked(
                    f"[{self.name}] {label}: {self._count_text()} in "
                    f"{elapsed}{counter_text}{detail_text}\n"
                )

    def _refresh(self) -> None:
        delay = (
            self.refresh_seconds
            if self._live
            else min(1.0, self.log_interval_seconds)
        )
        while not self._stop.wait(delay):
            now = time.monotonic()
            with self._lock:
                if self._finished or not self.enabled:
                    return
                if self._live:
                    self._render_live_locked(now)
                elif now - self._last_log_at >= self.log_interval_seconds:
                    self._write_log_locked("progress", now)

    def _render_live_locked(self, now: float) -> None:
        elapsed_seconds = now - (self._entered_at or now)
        spinner = _SPINNER[
            int(elapsed_seconds / self.refresh_seconds) % len(_SPINNER)
        ]
        if not self._started:
            line = f"{spinner} Preparing history analysis {_elapsed(elapsed_seconds)}"
            self._write_locked(f"\r\033[2K{self._truncate(line)}")
            return

        bar = self._bar()
        eta = self._eta(now)
        detail = self._counter_detail()
        line = (
            f"{spinner} Analyzing {self.name} {bar} {self._count_text()} "
            f"{_elapsed(elapsed_seconds)}{eta} — {detail}"
        )
        self._write_locked(f"\r\033[2K{self._truncate(line.strip())}")

    def _write_log_locked(self, label: str, now: float) -> None:
        elapsed = _elapsed(now - (self._entered_at or now))
        if self._started:
            text = (
                f"[{self.name}] {label}: {self._count_text()} {elapsed} "
                f"— {self._counter_detail()}\n"
            )
        else:
            text = f"[history] {label}: {_elapsed(now - self._entered_at)}\n"
        self._write_locked(text)
        self._last_log_at = now

    def _write_locked(self, text: str) -> None:
        if self._io_failed:
            return
        try:
            self.stream.write(text)
            self.stream.flush()
        except Exception:
            self._io_failed = True

    def _counter_detail(self) -> str:
        workers = f"{self.jobs} worker" + ("" if self.jobs == 1 else "s")
        move_word = "move" if self.moves == 1 else "moves"
        return (
            f"{self.analyzed} analyzed · {self.skipped} skipped · "
            f"{self.failed} failed · {self.moves} {move_word} · {workers}"
        )

    def _count_text(self) -> str:
        if self.target_total is None:
            return f"{self.covered} pairs covered"
        if self.covered > self.target_total:
            return (
                f"{self.covered} pairs covered · target "
                f"{self.target_total} satisfied"
            )
        if self.target_total == 0:
            percent = 100
        else:
            percent = min(100, int(100 * self.covered / self.target_total))
        return f"{self.covered}/{self.target_total} {percent:3d}%"

    def _bar(self) -> str:
        if self.target_total is None or self.target_total <= 0:
            return ""
        width = 18
        filled = min(width, int(width * self.covered / self.target_total))
        return f"[{'\u2588' * filled}{'·' * (width - filled)}]"

    def _eta(self, now: float) -> str:
        if self.target_total is None or len(self._samples) < 4:
            return ""
        first_time, first_covered = self._samples[0]
        elapsed = now - first_time
        advanced = self.covered - first_covered
        remaining = self.target_total - self.covered
        if elapsed < 1.0 or advanced < 3 or remaining <= 0:
            return ""
        return f" ETA {_elapsed(remaining * elapsed / advanced)}"

    def _bucket(self, covered: int) -> int:
        if self.target_total is None or self.target_total <= 0:
            return -1
        if covered >= self.target_total:
            return 10
        # Ten-percent milestones are useful for long runs, but should not turn
        # a small run into one redirected log line per pair.
        step = max(10, math.ceil(self.target_total / 10))
        return covered // step

    def _crossed_milestone_locked(self) -> bool:
        bucket = self._bucket(self.covered)
        if bucket <= self._last_bucket:
            return False
        self._last_bucket = bucket
        return bucket > 0

    @staticmethod
    def _truncate(line: str) -> str:
        width = max(20, shutil.get_terminal_size(fallback=(100, 24)).columns - 1)
        if len(line) <= width:
            return line
        return f"{line[: max(0, width - 1)]}…"


def _elapsed(seconds: float) -> str:
    whole = max(0, int(seconds))
    minutes, seconds = divmod(whole, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
