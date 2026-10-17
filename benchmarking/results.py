"""Shared schema-3 admission, independent of atomic scoring oracles."""
from __future__ import annotations
from typing import Any
from srcmove_runtime.results_schema import validate_results


def validate_results_schema(results: Any, *, require_xpaths: bool = False) -> list[str]:
    # Every schema-3 endpoint requires a locator, irrespective of oracle mode.
    try:
        validate_results(results)
    except (ValueError, TypeError) as error:
        return [str(error)]
    return []
