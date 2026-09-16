"""Canonical ignored storage roots shared by benchmark components."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_ROOT = REPO_ROOT / "benchmark-results"
