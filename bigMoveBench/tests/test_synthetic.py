from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from bigMoveBench.synthetic import (
    SYNTHETIC_DESTINATION_PATH,
    SYNTHETIC_SOURCE_PATH,
    build_synthetic_move_archive,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_archive(root: Path, sources: dict[Path, str]) -> None:
    for relative, source in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


class BigMoveBenchSyntheticTests(unittest.TestCase):
    def test_archive_moves_between_stable_files(self) -> None:
        original, modified, original_range, modified_range = (
            build_synthetic_move_archive(
                "BCBMove1_2",
                "  void movedFrom() {\n  }\n",
                "  void movedTo() {\n    call();\n  }\n",
            )
        )

        self.assertEqual(
            set(original),
            {SYNTHETIC_SOURCE_PATH, SYNTHETIC_DESTINATION_PATH},
        )
        self.assertEqual(set(modified), set(original))
        original_source = original[SYNTHETIC_SOURCE_PATH]
        original_destination = original[SYNTHETIC_DESTINATION_PATH]
        modified_source = modified[SYNTHETIC_SOURCE_PATH]
        modified_destination = modified[SYNTHETIC_DESTINATION_PATH]

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

    def test_srcml_parses_payloads_under_distinct_class_parents(self) -> None:
        srcml = REPO_ROOT.parent / "srcML-install" / "bin" / "srcml"
        if not srcml.is_file():
            discovered = shutil.which("srcml")
            if discovered is None:
                self.skipTest("srcml executable is unavailable")
            srcml = Path(discovered)

        original, modified, _, _ = build_synthetic_move_archive(
            "BCBMove1_2",
            "  void movedFrom() {\n    call();\n  }\n",
            "  void movedTo() {\n    call();\n  }\n",
        )
        parsed = {}
        payload_sources = {
            "movedFrom": original[SYNTHETIC_SOURCE_PATH],
            "movedTo": modified[SYNTHETIC_DESTINATION_PATH],
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

        def class_parents(root: ET.Element, function_name: str) -> list[str]:
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
            names = []
            current = parents[function]
            while current is not root:
                if local_name(current.tag) == "class":
                    names.append(
                        next(
                            "".join(child.itertext())
                            for child in current
                            if local_name(child.tag) == "name"
                        )
                    )
                current = parents[current]
            return names

        self.assertEqual(
            class_parents(parsed["movedFrom"], "movedFrom"),
            ["BCBMove1_2Source"],
        )
        self.assertEqual(
            class_parents(parsed["movedTo"], "movedTo"),
            ["BCBMove1_2Destination"],
        )

    def test_srcdiff_exposes_payload_as_delete_and_insert(self) -> None:
        srcdiff = REPO_ROOT.parent / "srcDiff" / "build" / "bin" / "srcdiff"
        if not srcdiff.is_file():
            discovered = shutil.which("srcdiff")
            if discovered is None:
                self.skipTest("srcdiff executable is unavailable")
            srcdiff = Path(discovered)

        original, modified, _, _ = build_synthetic_move_archive(
            "BCBMove1_2",
            "  void moved() {\n    call();\n  }\n",
            "  void moved() {\n    call();\n  }\n",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original_path = root / "original"
            modified_path = root / "modified"
            output_path = root / "diff.xml"
            _write_archive(original_path, original)
            _write_archive(modified_path, modified)
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

        for side in ("delete", "insert"):
            regions = [
                node for node in diff_root.iter() if local_name(node.tag) == side
            ]
            self.assertTrue(regions, f"srcDiff emitted no {side} region")
            self.assertTrue(
                any("moved" in "".join(region.itertext()) for region in regions),
                f"srcDiff {side} regions do not contain the moved payload",
            )


if __name__ == "__main__":
    unittest.main()
