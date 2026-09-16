#!/usr/bin/env python3
"""Regression tests for BigCloneBench case generation helpers.

These tests exist because IJaDataset files can contain standalone carriage
returns inside comments, while BigCloneBench source ranges are LF-based. The
generator must not let Python's universal newline splitting shift those ranges.


  This test checks one very specific bug.

  It creates a temporary file that looks roughly like this:

  class Example {
  /** first comment line\rsecond display line\rthird display line */
    void target() {
      call();
    }
  }

  The important part is the \r characters inside the comment. Python’s normal splitlines() treats those as real line breaks. If the generator used splitlines(), it would think the target() method starts later
  than it actually does.

  Then the test calls:

  extract_lines(source, 3, 5)

  And expects to get:

    void target() {
      call();
    }

  So the test proves: “when a BigCloneBench source file has standalone carriage returns inside comments, our generator still extracts by LF-based line numbers and does not drift.”

  It is not testing srcMove. It is testing that the benchmark input we feed into srcMove is extracted correctly.

"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = REPO_ROOT / "bigMoveBench" / "cases.py"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bigMoveBench import installation


def load_generator_module():
    spec = importlib.util.spec_from_file_location(
        "bigclonebench_generate", GENERATOR_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {GENERATOR_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BigCloneBenchGeneratorTests(unittest.TestCase):
    def test_known_false_positive_query_uses_function_metadata_and_judgments(self) -> None:
        generator = load_generator_module()

        query = generator.selection_query(
            25,
            None,
            known_false_positives=True,
            min_judges=2,
            min_confidence=3,
        )

        self.assertIn("FROM false_positives fp", query)
        self.assertNotIn("f1.tokens >=", query)
        self.assertNotIn("f2.tokens >=", query)
        self.assertIn("f1.internal = FALSE", query)
        self.assertIn("f2.internal = FALSE", query)
        self.assertIn("fp.min_judges >= 2", query)
        self.assertIn("fp.min_confidence >= 3", query)
        self.assertIn("AS min_tokens", query)
        self.assertNotIn("fp.min_tokens", query)
        self.assertNotIn("fp.internal", query)

    def test_positive_query_has_no_token_threshold(self) -> None:
        generator = load_generator_module()

        query = generator.selection_query(25, 1)

        self.assertIn("c.syntactic_type = 1", query)
        self.assertIn("c.internal = FALSE", query)
        self.assertNotIn("c.min_tokens >=", query)

    def test_preflight_reports_manual_prerequisites_without_downloading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            installation.shutil, "which", return_value=None
        ):
            failures = installation.preflight(Path(tmp) / "missing-BigCloneEval")

        self.assertTrue(any("database" in failure for failure in failures))
        self.assertTrue(any("H2 driver" in failure for failure in failures))
        self.assertTrue(any("IJaDataset" in failure for failure in failures))
        self.assertIn("Java executable not found on PATH", failures)

    def test_preflight_rejects_an_empty_ijadataset_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bce_dir = Path(tmp) / "BigCloneEval"
            (bce_dir / "bigclonebenchdb").mkdir(parents=True)
            (bce_dir / "bigclonebenchdb" / "bcb.h2.db").touch()
            (bce_dir / "libs").mkdir()
            (bce_dir / "libs" / "h2-1.3.176.jar").touch()
            (bce_dir / "ijadataset").mkdir()
            with mock.patch.object(
                installation.shutil, "which", return_value="/usr/bin/java"
            ):
                failures = installation.preflight(bce_dir)

        self.assertEqual(len(failures), 1)
        self.assertIn("IJaDataset Java corpus not found", failures[0])

    def test_preflight_accepts_reduced_ijadataset_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bce_dir = Path(tmp) / "BigCloneEval"
            (bce_dir / "bigclonebenchdb").mkdir(parents=True)
            (bce_dir / "bigclonebenchdb" / "bcb.h2.db").touch()
            (bce_dir / "libs").mkdir()
            (bce_dir / "libs" / "h2-1.3.176.jar").touch()
            source_dir = bce_dir / "ijadataset" / "bcb_reduced" / "2" / "default"
            source_dir.mkdir(parents=True)
            (source_dir / "131818.java").touch()
            with mock.patch.object(
                installation.shutil, "which", return_value="/usr/bin/java"
            ):
                failures = installation.preflight(bce_dir)

        self.assertEqual(failures, [])

    def test_source_path_supports_flat_and_reduced_layouts(self) -> None:
        generator = load_generator_module()

        with tempfile.TemporaryDirectory() as tmp:
            bce_dir = Path(tmp) / "BigCloneEval"
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
            with mock.patch.object(generator, "BCE_DIR", bce_dir):
                self.assertEqual(
                    generator.source_path("default", "131818.java", 2), reduced
                )

                flat = bce_dir / "ijadataset" / "default" / "131818.java"
                flat.parent.mkdir(parents=True)
                flat.touch()
                self.assertEqual(
                    generator.source_path("default", "131818.java", 2), flat
                )

    def test_extract_lines_uses_lf_ranges_when_comments_contain_cr(self) -> None:
        generator = load_generator_module()

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.java"
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
                generator.extract_lines(source, 3, 5),
                "  void target() {\n    call();\n  }\n",
            )

    def test_synthetic_archive_moves_between_stable_files(self) -> None:
        generator = load_generator_module()

        original, modified, original_range, modified_range = (
            generator.build_synthetic_move_archive(
                "BCBMove1_2",
                "  void movedFrom() {\n  }\n",
                "  void movedTo() {\n    call();\n  }\n",
            )
        )

        self.assertEqual(
            set(original),
            {generator.SYNTHETIC_SOURCE_PATH, generator.SYNTHETIC_DESTINATION_PATH},
        )
        self.assertEqual(set(modified), set(original))
        original_source = original[generator.SYNTHETIC_SOURCE_PATH]
        original_destination = original[generator.SYNTHETIC_DESTINATION_PATH]
        modified_source = modified[generator.SYNTHETIC_SOURCE_PATH]
        modified_destination = modified[generator.SYNTHETIC_DESTINATION_PATH]

        self.assertIn("class BCBMove1_2Source", original_source)
        self.assertIn("SOURCE_CONTEXT = 100", original_source)
        self.assertIn("void movedFrom()", original_source)
        self.assertNotIn("void movedFrom()", modified_source)
        self.assertIn("class BCBMove1_2Destination", modified_destination)
        self.assertIn("DESTINATION_CONTEXT = 200", modified_destination)
        self.assertIn("void movedTo()", modified_destination)
        self.assertNotIn("void movedTo()", original_destination)

        original_lines = original_source.splitlines()
        modified_lines = modified_destination.splitlines()
        self.assertEqual(
            "\n".join(original_lines[original_range[0] - 1 : original_range[1]]),
            "  void movedFrom() {\n  }",
        )
        self.assertEqual(
            "\n".join(modified_lines[modified_range[0] - 1 : modified_range[1]]),
            "  void movedTo() {\n    call();\n  }",
        )

        for source in (*original.values(), *modified.values()):
            self.assertEqual(source.count("{"), source.count("}"))

    def test_srcml_parses_synthetic_payloads_under_distinct_class_parents(self) -> None:
        generator = load_generator_module()
        srcml = REPO_ROOT.parent / "srcML-install" / "bin" / "srcml"
        if not srcml.is_file():
            discovered = shutil.which("srcml")
            if discovered is None:
                self.skipTest("srcml executable is unavailable")
            srcml = Path(discovered)

        original, modified, _, _ = generator.build_synthetic_move_archive(
            "BCBMove1_2",
            "  void movedFrom() {\n    call();\n  }\n",
            "  void movedTo() {\n    call();\n  }\n",
        )

        parsed = {}
        payload_sources = {
            "movedFrom": original[generator.SYNTHETIC_SOURCE_PATH],
            "movedTo": modified[generator.SYNTHETIC_DESTINATION_PATH],
        }
        for function_name, source in payload_sources.items():
            try:
                result = subprocess.run(
                    [str(srcml), "--language", "Java"],
                    input=source,
                    text=True,
                    capture_output=True,
                    check=False,
                )
            except OSError as error:
                self.skipTest(f"srcml executable cannot run here: {error}")
            self.assertEqual(result.returncode, 0, result.stderr)
            parsed[function_name] = ET.fromstring(result.stdout)

        def local_name(tag: str) -> str:
            return tag.rsplit("}", 1)[-1]

        def function_parent_names(root: ET.Element, function_name: str) -> list[str]:
            parents = {child: parent for parent in root.iter() for child in parent}
            function = next(
                node
                for node in root.iter()
                if local_name(node.tag) == "function"
                and any(
                    local_name(child.tag) == "name"
                    and "".join(child.itertext()) == function_name
                    for child in node
                )
            )
            ancestors = []
            current = parents[function]
            while current is not root:
                if local_name(current.tag) == "class":
                    name = next(
                        "".join(child.itertext())
                        for child in current
                        if local_name(child.tag) == "name"
                    )
                    ancestors.append(name)
                current = parents[current]
            return ancestors

        self.assertEqual(
            function_parent_names(parsed["movedFrom"], "movedFrom"),
            ["BCBMove1_2Source"],
        )
        self.assertEqual(
            function_parent_names(parsed["movedTo"], "movedTo"),
            ["BCBMove1_2Destination"],
        )

    def test_srcdiff_exposes_synthetic_payloads_as_delete_and_insert(self) -> None:
        generator = load_generator_module()
        srcdiff = REPO_ROOT.parent / "srcDiff" / "build" / "bin" / "srcdiff"
        if not srcdiff.is_file():
            discovered = shutil.which("srcdiff")
            if discovered is None:
                self.skipTest("srcdiff executable is unavailable")
            srcdiff = Path(discovered)

        original, modified, _, _ = generator.build_synthetic_move_archive(
            "BCBMove1_2",
            "  void moved() {\n    call();\n  }\n",
            "  void moved() {\n    call();\n  }\n",
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original_path = root / "original"
            modified_path = root / "modified"
            output_path = root / "diff.xml"
            generator._write_archive(original_path, original)
            generator._write_archive(modified_path, modified)
            try:
                result = subprocess.run(
                    [
                        str(srcdiff),
                        str(original_path),
                        str(modified_path),
                        "-o",
                        str(output_path),
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )
            except OSError as error:
                self.skipTest(f"srcdiff executable cannot run here: {error}")
            self.assertEqual(result.returncode, 0, result.stderr)
            diff_root = ET.parse(output_path).getroot()

        def local_name(tag: str) -> str:
            return tag.rsplit("}", 1)[-1]

        regions = {
            side: [
                node
                for node in diff_root.iter()
                if local_name(node.tag) == side
            ]
            for side in ("delete", "insert")
        }
        for side in ("delete", "insert"):
            self.assertTrue(regions[side], f"srcDiff emitted no {side} region")
            self.assertTrue(
                any("moved" in "".join(region.itertext()) for region in regions[side]),
                f"srcDiff {side} regions do not contain the moved payload",
            )


if __name__ == "__main__":
    unittest.main()
