import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from bigMoveBench.browser.reader import list_cases, list_runs, show_case, show_source


class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / "cache"
        self.results = self.root / "results"
        self.run = self.results / "saved-run"
        self.dataset = "bcb-dataset-sha256-" + "c" * 64
        self.fragments = []
        for text in ("int before() { return 1; }", "int after() { return 2; }"):
            digest = hashlib.sha256(text.encode()).hexdigest()
            path = self.cache / "bigclonebench/compiled" / self.dataset / "fragments" / digest[:2] / f"{digest}.java"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            self.fragments.append(digest)
        self.journals = []
        for category, digit in (("type1", "1"), ("type2b", "2")):
            self._member(category, digit)
        summary = {"schema_version": 1, "experiment_id": "experiment", "status": "completed", "selected": 4,
                   "completed_at": "2026-10-05T06:00:00Z", "tool_sha256": {},
                   "member_summaries": [{"pair_set": category} for category in ("type1", "type2b")]}
        (self.run / "summary.json").write_text(json.dumps(summary))

    def _member(self, category, digit):
        identifier = "bmb-benchmark-cases-sha256-" + digit * 64
        directory = self.cache / "benchmark-cases" / identifier
        directory.mkdir(parents=True)
        database = directory / "benchmark_cases.sqlite"
        with sqlite3.connect(database) as connection:
            connection.executescript("""
CREATE TABLE cases(case_id TEXT, ordinal INTEGER, case_kind TEXT, expected_match_kind TEXT,
 type3_both_similarity REAL, type3_strength_stratum TEXT, min_tokens INTEGER,
 original_fragment_sha256 TEXT, modified_fragment_sha256 TEXT,
 from_start_line INTEGER, from_end_line INTEGER, to_start_line INTEGER, to_end_line INTEGER);
""")
            for ordinal in (1, 2):
                connection.execute("INSERT INTO cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    f"{category}-{ordinal}", ordinal, "positive", category, None, None, 50,
                    *self.fragments, 3, 4, 3, 4))
        manifest = {"schema_version": 1, "benchmark_cases_id": identifier,
                    "compiled_dataset": {"dataset_id": self.dataset},
                    "artifacts": {"benchmark_cases": {"path": database.name, "size_bytes": database.stat().st_size}}}
        manifest_path = directory / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        member = self.run / category
        member.mkdir(parents=True)
        journal = member / "execution.sqlite"
        self.journals.append(journal)
        with sqlite3.connect(journal) as connection:
            connection.executescript("""
CREATE TABLE run_metadata(singleton INTEGER, schema_version INTEGER, benchmark_cases_id TEXT, benchmark_cases_manifest_sha256 TEXT);
CREATE TABLE attempts(attempt_id TEXT, case_id TEXT, attempt_ordinal INTEGER, status TEXT, outcome TEXT,
 oracle_results_json TEXT, semantic_status TEXT, semantic_details_json TEXT, oracle_failures_json TEXT, text_validation_json TEXT);
""")
            connection.execute("INSERT INTO run_metadata VALUES (1,1,?,?)", (identifier, hashlib.sha256(manifest_path.read_bytes()).hexdigest()))
            for ordinal in (1, 2):
                result = {"move_count": 1 if ordinal == 1 else 0, "moves": [],
                          "_oracle_observed_match_kind": "type3" if ordinal == 1 else None,
                          "_oracle_reviewed_outcome": "oracle_pass" if ordinal == 1 else "srcmove_miss",
                          "_oracle_label_correction": {"id": "correction", "reviewed_match_kind": "type3"}}
                if ordinal == 1:
                    result["moves"] = [{"move_id": "move-1", "match_kind": "type3", "from_raw_texts": ["before"], "to_raw_texts": ["after"]}]
                connection.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?,?)", (
                    f"{category}-attempt-{ordinal}", f"{category}-{ordinal}", 0, "terminal",
                    "wrong_classification" if ordinal == 1 else "srcmove_miss", json.dumps(result),
                    "eligible", '{"reason":"payload_exposed"}', '["recorded reason"]', '{}'))

    def test_pagination_across_members_and_read_only_queries(self):
        before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in self.journals]
        self.assertEqual(list_runs(self.results)["default_run_id"], "saved-run")
        page = list_cases(self.results, self.cache, "saved-run", offset=1, limit=2)
        self.assertEqual(page["total"], 4)
        self.assertEqual(page["matched"], 4)
        self.assertEqual([item["case_id"] for item in page["items"]], ["type1-2", "type2b-1"])
        self.assertEqual(page["next_offset"], 3)
        self.assertNotIn("moves", page["items"][0])
        self.assertEqual(before, [hashlib.sha256(path.read_bytes()).hexdigest() for path in self.journals])

    def test_incomplete_runs_do_not_hide_completed_runs(self):
        pending = self.results / "pending-run"
        pending.mkdir()
        (pending / "summary.json").write_text(json.dumps({"status": "executing"}))
        self.assertEqual([item["run_id"] for item in list_runs(self.results)["items"]], ["saved-run"])

    def test_source_input_is_verified_and_confined_to_member(self):
        path = self.run / "type1/tool-attempts/srcdiff/attempt-one/srcdiff.xml"
        path.parent.mkdir(parents=True)
        path.write_text('<unit xmlns="http://www.srcML.org/srcML/src"/>')
        record = {"xml": {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}
        with sqlite3.connect(self.journals[0]) as connection:
            for column in ("srcdiff_admitted INTEGER", "srcdiff_record_json TEXT", "srcdiff_attempt_path TEXT"):
                connection.execute("ALTER TABLE attempts ADD COLUMN " + column)
            connection.execute("UPDATE attempts SET srcdiff_admitted=1,srcdiff_record_json=?,srcdiff_attempt_path=? WHERE case_id='type1-1'", (json.dumps(record), "tool-attempts/srcdiff/attempt-one"))
        source = show_source(self.results, self.cache, "saved-run", "type1", "type1-1")
        self.assertEqual(source["srcdiff_xml"], path.read_text())
        self.assertEqual(source["results"]["move_count"], 1)
        path.write_text("changed XML")
        with self.assertRaisesRegex(ValueError, "checksum differs"):
            show_source(self.results, self.cache, "saved-run", "type1", "type1-1")
        with sqlite3.connect(self.journals[0]) as connection:
            connection.execute("UPDATE attempts SET srcdiff_attempt_path='../escape'")
        with self.assertRaisesRegex(ValueError, "escapes"):
            show_source(self.results, self.cache, "saved-run", "type1", "type1-1")

    def test_wal_pages_are_read_without_changing_original_sidecars(self):
        with sqlite3.connect(self.journals[0]) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("UPDATE attempts SET outcome='oracle_pass' WHERE case_id='type1-1'")
            connection.commit()
            before = {p.name: p.read_bytes() for p in self.journals[0].parent.glob("execution.sqlite*")}
            page = list_cases(self.results, self.cache, "saved-run", category="type1")
            self.assertEqual(page["items"][0]["outcome"], "oracle_pass")
            self.assertEqual(before, {p.name: p.read_bytes() for p in self.journals[0].parent.glob("execution.sqlite*")})

    def test_detection_and_original_reviewed_outcomes_stay_separate(self):
        original = list_cases(self.results, self.cache, "saved-run", category="type2b", outcome="wrong_classification")
        self.assertEqual(original["matched"], 1)
        case = original["items"][0]
        self.assertTrue(case["complete_fragment_detected"])
        self.assertEqual(case["observed_match_kind"], "type3")
        reviewed = list_cases(self.results, self.cache, "saved-run", category="type2b", outcome="oracle_pass", basis="reviewed")
        self.assertEqual(reviewed["items"][0]["case_id"], case["case_id"])

    def test_case_details_include_exact_fragments_moves_and_misses(self):
        detail = show_case(self.results, self.cache, "saved-run", "type2b", "type2b-1")
        self.assertEqual(detail["original"]["text"], "int before() { return 1; }")
        self.assertEqual(detail["moves"][0]["from_raw_texts"], ["before"])
        self.assertEqual(detail["failures"], ["recorded reason"])
        self.assertIsNone(detail["diagnostics"])
        miss = show_case(self.results, self.cache, "saved-run", "type2b", "type2b-2")
        self.assertEqual(miss["moves"], [])
        self.assertFalse(miss["case"]["complete_fragment_detected"])

    def test_missing_and_corrupt_fragments_are_distinguished(self):
        digest = self.fragments[0]
        path = self.cache / "bigclonebench/compiled" / self.dataset / "fragments" / digest[:2] / f"{digest}.java"
        path.unlink()
        self.assertIsNone(show_case(self.results, self.cache, "saved-run", "type1", "type1-1")["original"]["text"])
        path.write_text("corrupt")
        with self.assertRaisesRegex(ValueError, "checksum"):
            show_case(self.results, self.cache, "saved-run", "type1", "type1-1")

    def test_latest_terminal_attempt_excludes_interrupted_retry(self):
        with sqlite3.connect(self.journals[0]) as connection:
            connection.execute("INSERT INTO attempts(attempt_id,case_id,attempt_ordinal,status,outcome) VALUES ('retry','type1-1',1,'terminal','srcmove_miss')")
            connection.execute("INSERT INTO attempts(attempt_id,case_id,attempt_ordinal,status) VALUES ('interrupted','type1-1',2,'interrupted')")
        page = list_cases(self.results, self.cache, "saved-run", category="type1")
        self.assertEqual(page["items"][0]["attempt_id"], "retry")
        self.assertEqual(page["items"][0]["outcome"], "srcmove_miss")
        self.assertEqual(page["matched"], 2)

    def test_unknown_ids_and_invalid_filters_are_rejected(self):
        with self.assertRaises(ValueError):
            list_cases(self.results, self.cache, "../saved-run")
        with self.assertRaises(ValueError):
            list_cases(self.results, self.cache, "saved-run", limit=101)
        with self.assertRaises(ValueError):
            list_cases(self.results, self.cache, "saved-run", category="other")
        with self.assertRaises(FileNotFoundError):
            show_case(self.results, self.cache, "saved-run", "type1", "unknown")
