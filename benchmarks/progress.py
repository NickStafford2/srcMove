"""Compact terminal-aware progress reporting for benchmark pipelines."""

from __future__ import annotations

import shutil
import sys
import threading
import time
from typing import TextIO


_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _elapsed(seconds: float) -> str:
    whole = max(0, int(seconds))
    minutes, seconds = divmod(whole, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


class ProgressDisplay:
    """Render one live TTY line, with sparse durable output when redirected."""

    def __init__(
        self,
        phase: str,
        *,
        total: int | None = None,
        detail: str = "",
        stream: TextIO | None = None,
        enabled: bool = True,
        refresh_seconds: float = 0.1,
        log_interval_seconds: float = 30.0,
    ) -> None:
        self.phase = phase
        self.total = total
        self.detail = detail
        self.stream = stream or sys.stderr
        self.enabled = enabled
        self.refresh_seconds = refresh_seconds
        self.log_interval_seconds = log_interval_seconds
        self.completed = 0
        self._started = time.monotonic()
        self._last_log = self._started
        self._last_bucket = -1
        self._active = False
        self._finished = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._live = bool(getattr(self.stream, "isatty", lambda: False)())

    def __enter__(self) -> "ProgressDisplay":
        self.start()
        return self

    def __exit__(self, exception_type, exception, traceback) -> None:
        if self._finished:
            return
        if exception is None:
            self.finish()
        else:
            self.finish(f"failed: {exception}", success=False)

    def start(self) -> None:
        if self._active:
            return
        self._active = True
        if not self.enabled:
            return
        if self._live:
            self._render_live()
        else:
            self._write_log("started")
        self._thread = threading.Thread(target=self._refresh, daemon=True)
        self._thread.start()

    def update(self, completed: int | None = None, *, detail: str | None = None) -> None:
        with self._lock:
            if completed is not None:
                self.completed = completed
            if detail is not None:
                self.detail = detail
            if not self.enabled:
                return
            should_log = not self._live and self._crossed_log_bucket()
        if self._live:
            self._render_live()
        elif should_log:
            self._write_log("progress")

    def advance(self, *, detail: str | None = None) -> None:
        self.update(self.completed + 1, detail=detail)

    def set_total(self, total: int, *, completed: int | None = None) -> None:
        with self._lock:
            self.total = total
            if completed is not None:
                self.completed = completed

    def event(self, message: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._live:
                self.stream.write("\r\033[2K")
            self.stream.write(f"! {self.phase}: {message}\n")
            self.stream.flush()
        if self._live:
            self._render_live()

    def finish(
        self,
        detail: str | None = None,
        *,
        success: bool = True,
        completion: str | None = None,
    ) -> None:
        if self._finished:
            return
        if detail is not None:
            with self._lock:
                self.detail = detail
        if not self.enabled:
            self._active = False
            self._finished = True
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        with self._lock:
            elapsed = _elapsed(time.monotonic() - self._started)
            count = self._count_text()
            suffix = f" — {self.detail}" if self.detail else ""
            if self._live:
                icon = "✓" if success else "✗"
                result = completion or count
                line = f"{icon} {self.phase} {result} in {elapsed}{suffix}".strip()
                self.stream.write(f"\r\033[2K{self._truncate(line)}\n")
            else:
                status = completion or ("complete" if success else "failed")
                if completion is not None and self.total is None:
                    self.stream.write(
                        f"[{self.phase}] {status} in {elapsed}{suffix}\n"
                    )
                else:
                    self.stream.write(
                        f"[{self.phase}] {status}: {count} in {elapsed}{suffix}\n"
                    )
            self.stream.flush()
            self._active = False
            self._finished = True

    def _refresh(self) -> None:
        while not self._stop.wait(self.refresh_seconds if self._live else 1.0):
            if self._live:
                self._render_live()
                continue
            with self._lock:
                due = time.monotonic() - self._last_log >= self.log_interval_seconds
            if due:
                self._write_log("still working")

    def _render_live(self) -> None:
        with self._lock:
            elapsed_seconds = time.monotonic() - self._started
            spinner = _SPINNER[
                int(elapsed_seconds / self.refresh_seconds) % len(_SPINNER)
            ]
            count = self._count_text()
            bar = self._bar()
            detail = f" — {self.detail}" if self.detail else ""
            line = (
                f"{spinner} {self.phase} {bar} {count} "
                f"{_elapsed(elapsed_seconds)}{detail}"
            )
            self.stream.write(f"\r\033[2K{self._truncate(line.strip())}")
            self.stream.flush()

    def _write_log(self, status: str) -> None:
        with self._lock:
            elapsed = _elapsed(time.monotonic() - self._started)
            count = self._count_text()
            detail = f" — {self.detail}" if self.detail else ""
            self.stream.write(f"[{self.phase}] {status}: {count} {elapsed}{detail}\n")
            self.stream.flush()
            self._last_log = time.monotonic()

    def _bar(self) -> str:
        if self.total is None or self.total <= 0:
            return ""
        width = 18
        filled = min(width, int(width * self.completed / self.total))
        return f"[{'█' * filled}{'·' * (width - filled)}]"

    def _count_text(self) -> str:
        if self.total is None:
            return "working"
        percent = (
            100
            if self.total == 0
            else min(100, int(100 * self.completed / self.total))
        )
        return f"{self.completed}/{self.total} {percent:3d}%"

    def _crossed_log_bucket(self) -> bool:
        if self.total is None or self.total <= 0:
            return False
        bucket = min(10, int(10 * self.completed / self.total))
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
