from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bigMoveBench.generated_objects import GeneratedObjectStore
from bigMoveBench.synthetic import (
    STABLE_DESTINATION_ROLE,
    STABLE_SOURCE_ROLE,
)


class GeneratedObjectStoreTests(unittest.TestCase):
    def test_reuses_stable_objects_across_pair_combinations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = GeneratedObjectStore(Path(temporary))
            fragments = {
                "a": "void a() {\n  first();\n}\n",
                "b": "void b() {\n  second();\n}\n",
                "c": "void c() {\n  third();\n}\n",
            }
            pairs = (("a", "b"), ("a", "c"), ("b", "c"), ("c", "a"))
            cases = []
            for source, destination in pairs:
                cases.append(
                    (
                        store.publish(STABLE_SOURCE_ROLE, fragments[source]),
                        store.publish(STABLE_DESTINATION_ROLE, None),
                        store.publish(STABLE_SOURCE_ROLE, None),
                        store.publish(
                            STABLE_DESTINATION_ROLE, fragments[destination]
                        ),
                    )
                )

            self.assertEqual(cases[0][0].object_id, cases[1][0].object_id)
            self.assertEqual(cases[1][3].object_id, cases[2][3].object_id)
            self.assertTrue(all(case[1] == cases[0][1] for case in cases))
            self.assertTrue(all(case[2] == cases[0][2] for case in cases))
            self.assertEqual(
                len(list(store.directory.glob("*.java"))),
                8,
                "three source payloads, three destination payloads, and two empties",
            )

    def test_stable_wrapper_identity_does_not_depend_on_pairing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = GeneratedObjectStore(Path(temporary))
            fragment = "void moved() {\n  call();\n}\n"
            source = store.publish(STABLE_SOURCE_ROLE, fragment)
            repeated = store.publish(STABLE_SOURCE_ROLE, fragment)
            destination = store.publish(STABLE_DESTINATION_ROLE, fragment)

            self.assertEqual(source, repeated)
            self.assertNotEqual(source.object_id, destination.object_id)
            self.assertEqual(source.payload_range, (3, 5))
            self.assertEqual(destination.payload_range, (3, 5))
            self.assertIn("class BigMoveBenchSource", source.path.read_text())
            self.assertIn(
                "class BigMoveBenchDestination", destination.path.read_text()
            )
            self.assertFalse(source.path.stat().st_mode & 0o222)
            self.assertFalse(destination.path.stat().st_mode & 0o222)

    def test_rejects_corrupted_published_object(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = GeneratedObjectStore(Path(temporary))
            fragment = "void moved() {}\n"
            published = store.publish(STABLE_SOURCE_ROLE, fragment)
            published.path.chmod(0o644)
            published.path.write_text("corrupted\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "content mismatch"):
                store.publish(STABLE_SOURCE_ROLE, fragment)

    def test_rejects_unknown_role_without_creating_store(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = GeneratedObjectStore(Path(temporary))
            with self.assertRaisesRegex(ValueError, "unsupported"):
                store.publish("unknown", "void moved() {}\n")
            self.assertFalse(store.directory.exists())

    def test_rejects_empty_payload_as_distinct_from_empty_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = GeneratedObjectStore(Path(temporary))
            empty_wrapper = store.publish(STABLE_SOURCE_ROLE, None)
            with self.assertRaisesRegex(ValueError, "nonempty or None"):
                store.publish(STABLE_SOURCE_ROLE, "")
            self.assertIsNone(empty_wrapper.payload_range)
            self.assertEqual(len(list(store.directory.glob("*.java"))), 1)


if __name__ == "__main__":
    unittest.main()
