from __future__ import annotations

import unittest

from benchmarking.identity import canonical_json, content_identifier


class BenchmarkIdentityTests(unittest.TestCase):
    def test_canonical_identity_ignores_object_key_order(self) -> None:
        left = {"schema_version": 1, "cases": ["a", "b"], "scope": None}
        right = {"scope": None, "cases": ["a", "b"], "schema_version": 1}

        self.assertEqual(canonical_json(left), canonical_json(right))
        self.assertEqual(
            content_identifier("input-snapshot", left),
            content_identifier("input-snapshot", right),
        )

    def test_canonical_identity_preserves_array_order_and_content(self) -> None:
        baseline = {"schema_version": 1, "checksums": ["one", "two"]}
        reordered = {"schema_version": 1, "checksums": ["two", "one"]}
        changed = {"schema_version": 1, "checksums": ["one", "three"]}

        self.assertNotEqual(
            content_identifier("corpus", baseline),
            content_identifier("corpus", reordered),
        )
        self.assertNotEqual(
            content_identifier("corpus", baseline),
            content_identifier("corpus", changed),
        )


if __name__ == "__main__":
    unittest.main()
