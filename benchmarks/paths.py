"""Canonical ignored storage roots for benchmark inputs and results."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_ROOT = REPO_ROOT / "benchmark-cache"
DEFAULT_RESULTS_ROOT = REPO_ROOT / "benchmark-results"
