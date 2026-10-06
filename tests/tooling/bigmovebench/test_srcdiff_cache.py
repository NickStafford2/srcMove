from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bigMoveBench.srcdiff_cache import DevelopmentSrcdiffCache


CASE_ID = "bcb-generated-input-sha256-" + "a" * 64


class DevelopmentSrcdiffCacheTests(unittest.TestCase):
    def test_round_trip_and_corrupt_entry_miss(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = DevelopmentSrcdiffCache(root / "cache")
            source = root / "source.xml"
            source.write_text("<unit>payload</unit>\n", encoding="utf-8")

            entry = cache.store(
                case_id=CASE_ID,
                wrapper_version=4,
                source=source,
            )
            restored = root / "restored.xml"
            self.assertTrue(
                cache.restore(
                    case_id=CASE_ID,
                    wrapper_version=4,
                    destination=restored,
                )
            )
            self.assertEqual(restored.read_bytes(), source.read_bytes())

            entry.write_bytes(b"not gzip")
            self.assertFalse(
                cache.restore(
                    case_id=CASE_ID,
                    wrapper_version=4,
                    destination=root / "damaged.xml",
                )
            )


if __name__ == "__main__":
    unittest.main()
