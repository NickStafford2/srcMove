"""Small statistical summaries shared by benchmark components."""

from __future__ import annotations

import statistics
from typing import Sequence


def describe(values: Sequence[float]) -> dict[str, int | float | None]:
    """Return robust summary statistics for a numeric sample."""

    if not values:
        return {"n": 0, "median": None, "mad": None, "min": None, "max": None}
    median = statistics.median(values)
    return {
        "n": len(values),
        "median": median,
        "mad": statistics.median(abs(value - median) for value in values),
        "min": min(values),
        "max": max(values),
    }
