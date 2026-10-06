from __future__ import annotations

import unittest
from pathlib import Path

from bigMoveBench.contracts import (
    InputPair,
    SemanticResult,
    SemanticStatus,
)


class BigMoveBenchContractTests(unittest.TestCase):
    def test_semantic_status_vocabulary(self) -> None:
        """Keep the four semantic-admission status values explicit and stable."""
        self.assertEqual(
            [status.value for status in SemanticStatus],
            ["eligible", "ineligible", "not_applicable", "not_checked"],
        )

    def test_pair_and_semantic_defaults_are_independent(self) -> None:
        """Construct a source pair and a semantic result with empty metadata and details by default."""
        pair = InputPair("one", Path("old.cpp"), Path("new.cpp"))
        result = SemanticResult(SemanticStatus.NOT_APPLICABLE)

        self.assertEqual(dict(pair.metadata), {})
        self.assertEqual(dict(result.details), {})


if __name__ == "__main__":
    unittest.main()
