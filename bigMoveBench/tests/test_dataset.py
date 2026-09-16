from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bigMoveBench.dataset import extract_lines, source_path


class BigCloneBenchDatasetTests(unittest.TestCase):
    def test_source_path_supports_flat_and_reduced_layouts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bce_dir = Path(temporary) / "BigCloneEval"
            reduced = (
                bce_dir
                / "ijadataset"
                / "bcb_reduced"
                / "2"
                / "default"
                / "131818.java"
            )
            reduced.parent.mkdir(parents=True)
            reduced.touch()
            self.assertEqual(
                source_path(bce_dir, "default", "131818.java", 2), reduced
            )

            flat = bce_dir / "ijadataset" / "default" / "131818.java"
            flat.parent.mkdir(parents=True)
            flat.touch()
            self.assertEqual(
                source_path(bce_dir, "default", "131818.java", 2), flat
            )

    def test_extract_lines_uses_lf_ranges_when_comments_contain_cr(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.java"
            source.write_text(
                "class Example {\n"
                "/** first comment line\rsecond display line\rthird display line */\n"
                "  void target() {\n"
                "    call();\n"
                "  }\n"
                "}\n",
                encoding="utf-8",
                newline="",
            )

            self.assertEqual(
                extract_lines(source, 3, 5),
                "  void target() {\n    call();\n  }\n",
            )


if __name__ == "__main__":
    unittest.main()
