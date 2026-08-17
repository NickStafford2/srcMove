from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "benchmark" / "bigclonebench_cases.json"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.bigclonebench.adapter import BigCloneBenchAdapter
from benchmarks.bigclonebench.evaluate import write_evaluation
from benchmarks.corpus import create_preparation, generate_corpus, run_corpus
from benchmarks.provenance import sha256_file


def write_executable(path: Path, source: str) -> Path:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)
    return path


class BigCloneBenchPipelineTests(unittest.TestCase):
    def test_fixture_corpus_replays_across_builds_and_reconciles_outcomes(self) -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cases_dir = root / "cases"
            cases_dir.mkdir()
            manifest = {
                "schema_version": 2,
                "syntactic_type": 1,
                "clone_type": "type1",
                "dedupe": "raw-text-pair",
                "row_count_before_deduplication": len(fixture["cases"]),
                "selected_count": len(fixture["cases"]),
                "cases": fixture["cases"],
                "selection": {
                    "role": "tuning",
                    "method": "fixture_census",
                    "pair_direction": "fragment_one_deleted_fragment_two_inserted",
                },
            }
            (cases_dir / "bcb_t1_manifest.json").write_text(json.dumps(manifest))
            for case_id in fixture["cases"]:
                case_dir = cases_dir / case_id
                case_dir.mkdir()
                (case_dir / "original.java").write_text(f"// {case_id}\nclass Old {{}}\n")
                (case_dir / "modified.java").write_text(f"// {case_id}\nclass New {{}}\n")
                metadata = {
                    "source": "BigCloneBench fixture",
                    "syntactic_type": fixture["syntactic_type"],
                    "fragment_relation": {
                        "raw_text_identical": True,
                        "trimmed_text_identical": True,
                    },
                    "expected": fixture["expected"],
                }
                (case_dir / "metadata.json").write_text(json.dumps(metadata))

            srcdiff = write_executable(
                root / "srcdiff-fixture",
                """#!/usr/bin/env python3
import sys
from pathlib import Path
case_id = Path(sys.argv[-3]).parents[1].name
output = Path(sys.argv[sys.argv.index('-o') + 1])
if case_id == 'upstream-failure':
    raise SystemExit(23)
if case_id == 'semantic-ineligible':
    body = '<name>aligned</name>'
else:
    body = ("<diff:delete><function pos:start='3:1|3:1' pos:end='4:1|4:1'>"
            "void moved() {}</function></diff:delete>"
            "<diff:insert><function pos:start='5:1|5:1' pos:end='6:1|6:1'>"
            "void moved() {}</function></diff:insert>")
output.write_text("<unit xmlns='http://www.srcML.org/srcML/src' "
                  "xmlns:diff='http://www.srcML.org/srcDiff/diff' "
                  "xmlns:pos='http://www.srcML.org/srcML/position' "
                  f"case='{case_id}'>{body}</unit>")
""",
            )
            srcmove_source = """#!/usr/bin/env python3
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
input_xml, output_xml = Path(sys.argv[1]), Path(sys.argv[2])
case_id = ET.parse(input_xml).getroot().attrib['case']
if case_id == 'srcmove-tool-failure':
    raise SystemExit(31)
kind = 'type2' if case_id == 'wrong-classification' else 'exact'
moves = [] if case_id == 'srcmove-miss' else [{
    'match_kind': kind,
    'from_raw_texts': ['void moved() {\\n}\\n'],
    'to_raw_texts': ['void moved() {\\n}\\n'],
    'from_xpaths': ['/src:unit/diff:delete[1]'],
    'to_xpaths': ['/src:unit/diff:insert[1]'],
}]
results = {'move_count': len(moves), 'match_kinds': {kind: len(moves)}, 'moves': moves}
Path(sys.argv[sys.argv.index('--results') + 1]).write_text(json.dumps(results))
output_xml.write_text("<unit xmlns='http://www.srcML.org/srcML/src' "
    "xmlns:diff='http://www.srcML.org/srcDiff/diff' "
    "xmlns:mv='http://www.srcML.org/srcMove' "
    "xmlns:pos='http://www.srcML.org/srcML/position'>"
    "<diff:delete mv:id='m1' mv:to='target' pos:start='3:1|3:1' pos:end='4:1|4:1'/>"
    "<diff:insert mv:id='m1' mv:from='source' pos:start='5:1|5:1' pos:end='6:1|6:1'/>"
    "</unit>")
"""
            srcmove_a = write_executable(root / "srcmove-build-a", srcmove_source)
            srcmove_b = write_executable(
                root / "srcmove-build-b", srcmove_source + "\n# second build\n"
            )

            data_root = root / "benchmark-data"
            adapter = BigCloneBenchAdapter(cases_dir, 1)
            _, preparation = create_preparation(
                data_root=data_root, adapter=adapter, source=adapter.source_manifest()
            )
            corpus_dir, corpus = generate_corpus(
                data_root=data_root,
                preparation=preparation["preparation_id"],
                srcdiff=srcdiff,
                timeout_seconds=2.0,
                use_position=True,
                use_archive=False,
                semantic_validator=BigCloneBenchAdapter.validate_semantics,
                semantic_oracle={"name": "fixture", "version": 1},
            )
            corpus_manifest_checksum = sha256_file(corpus_dir / "manifest.json")

            summaries = []
            runs = []
            for executable in (srcmove_a, srcmove_b):
                run_dir, run = run_corpus(
                    data_root=data_root,
                    corpus=corpus_dir,
                    srcmove=executable,
                    timeout_seconds=2.0,
                    require_semantic_eligible=True,
                )
                runs.append(run)
                summaries.append(
                    write_evaluation(
                        run_dir=run_dir,
                        run_manifest=run,
                        corpus_dir=corpus_dir,
                        corpus_manifest=corpus,
                    )
                )

            self.assertEqual(sha256_file(corpus_dir / "manifest.json"), corpus_manifest_checksum)
            self.assertNotEqual(summaries[0]["run_id"], summaries[1]["run_id"])
            self.assertNotEqual(
                runs[0]["observation"]["executables"]["srcMove"]["artifact"]["sha256"],
                runs[1]["observation"]["executables"]["srcMove"]["artifact"]["sha256"],
            )
            expected_counts = {
                "selected": 6,
                "eligible": 4,
                "executed": 4,
                "upstream_failure": 1,
                "srcdiff_semantic_ineligible": 1,
                "srcmove_tool_failure": 1,
                "srcmove_miss": 1,
                "wrong_classification": 1,
                "oracle_failure": 0,
                "oracle_pass": 1,
                "strict_passes": 1,
                "encoding_tolerant_passes": 0,
            }
            for summary in summaries:
                self.assertEqual(summary["counts"], expected_counts)
                rows_path = data_root / "runs" / summary["run_id"] / "cases.csv"
                with rows_path.open(encoding="utf-8") as stream:
                    rows = list(csv.DictReader(stream))
                wrong = next(row for row in rows if row["case_id"] == "wrong-classification")
                self.assertEqual(wrong["outcome"], "wrong_classification")
                self.assertEqual(wrong["expected_match_kind"], "exact")
                self.assertEqual(wrong["observed_match_kind"], "type2")
                self.assertNotEqual(wrong["outcome"], "oracle_pass")


if __name__ == "__main__":
    unittest.main()
