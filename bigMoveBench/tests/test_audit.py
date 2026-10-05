from __future__ import annotations

import csv
import io
import json
from contextlib import closing, redirect_stderr
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from bigMoveBench.audit import (Queries, eligible_coverage, overlap_accounting,
                                population, readonly, resolve_dataset, sampling_report,
                                selection_inventory, selection_metrics)
from bigMoveBench.catalog import compile_exports
from bigMoveBench.selection import _catalog_connection, create_selection
from bigMoveBench.selection_index import build_index, open_index
from bigMoveBench.tests.test_selection_index import compile_fixture
from bigMoveBench.tests.test_catalog import pair_row, write_export
from benchmarking.provenance import sha256_file


class AuditTests(unittest.TestCase):
    def test_directional_row_frames_share_one_unordered_content_pair(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            frames = [{'frame_id': str(n), 'direction': {
                       'original_fragment_sha256': a, 'modified_fragment_sha256': b},
                       'functionality_ids': [7]} for n, (a, b) in enumerate([('a', 'b'), ('b', 'a')])]
            (directory / 'frames.jsonl').write_text('\n'.join(json.dumps(f) for f in frames))
            manifest = {'selection_id': 'fixture', 'request': {'pair_set': 'type1'},
                        'artifacts': {'frames': {'path': 'frames.jsonl'}}}
            with patch('bigMoveBench.audit.load_selection', return_value=manifest):
                result = selection_metrics(directory, type('Dataset', (), {'dataset_id': 'fixture'})())
            self.assertEqual(result['distinct_content_pairs'], 1)
            self.assertEqual(result['directional_case_count'], 2)
            self.assertEqual(result['distinct_directional_inputs'], 2)
            self.assertEqual(result['distinct_fragment_contents'], 2)

    def test_three_way_category_overlap_is_not_counted_as_three_excess_pairs(self):
        result = overlap_accounting({'type1': 3, 'type2b': 2, 'type3': 4},
            [('a', 'type1', 'type2b'), ('a', 'type1', 'type3'),
             ('a', 'type2b', 'type3'), ('b', 'type1', 'type3')])
        self.assertEqual(result['pairs_in_multiple_categories'], 2)
        self.assertEqual(result['excess_memberships'], 3)
        self.assertEqual(result['distinct_eligible_content_pairs'], 6)
        self.assertFalse(result['category_counts_sum_to_distinct_total'])

    def test_real_fixture_multiplicity_conflicts_failures_and_readonly(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stderr(io.StringIO()):
            root = Path(temporary)
            compile_fixture(root, repetitions=1)
            exports = root / 'exports'
            with (exports / 'positive.csv').open() as stream:
                rows = list(csv.DictReader(stream))
            rows.append(rows[0])  # One repeated imported assertion, not a new catalog row.
            missing = pair_row()
            missing.update(functionality_id=9000, function_id_one=90001, function_id_two=90002)
            rows.extend([missing, missing])  # Both endpoints missing, source multiplicity two.
            write_export(exports / 'positive.csv', rows)
            compiled = compile_exports(bce_dir=root / 'BigCloneEval', data_root=root / 'data',
                exports={'positive': exports / 'positive.csv', 'known_false_positive': exports / 'false.csv'},
                compile_scope={'fixture': 'audit'})
            path = root / 'index.sqlite'
            build_index(compiled, path)
            before = [sha256_file(p) for p in (path, compiled.directory / 'catalog.sqlite')]
            resolved, identity = resolve_dataset(path, root / 'data')
            self.assertEqual(resolved.dataset_id, compiled.dataset_id)
            self.assertEqual(identity['dataset_id'], compiled.dataset_id)
            self.assertEqual(len(list((root / 'data/bigclonebench/compiled').glob('bcb-dataset-*'))), 2)
            with closing(open_index(compiled, path)) as index, closing(_catalog_connection(compiled)) as source:
                p = population(source, index, Queries(30))
                self.assertEqual(p['imported_source_rows'] - p['catalog_rows'], 2)
                self.assertEqual(p['unavailable_catalog_rows'], 1)
                self.assertEqual(p['unavailable_source_rows'], 2)
                self.assertEqual(p['content_pairs_excluded_for_label_conflicts'], 1)
                self.assertEqual(p['conflict_catalog_rows'], 2)
                self.assertEqual(p['discrepancies'], [])
                self.assertEqual(p['extraction_failure_reasons'][0]['materializations'], 2)
                self.assertEqual(p['extraction_failure_reasons'][0]['functions'], 2)
                self.assertEqual(p['extraction_failure_reasons'][0]['catalog_rows'], 1)
                self.assertEqual(p['extraction_failure_reasons'][0]['source_rows'], 2)
                coverage = eligible_coverage(source, path, Queries(30))
                self.assertEqual(coverage['distinct_fragment_contents'], 16)
                self.assertEqual(coverage['represented_functionality_ids'], list(range(101, 109)))
                self.assertEqual(p['category_accounting']['distinct_eligible_content_pairs'], 8)
            self.assertEqual(before, [sha256_file(p) for p in (path, compiled.directory / 'catalog.sqlite')])
            with closing(readonly(path)) as connection:
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("DELETE FROM counts")
            # Frozen/sample filenames never imply a final experiment designation.
            inventory = selection_inventory(root / 'data', compiled, [])
            self.assertEqual(inventory['final_selections'], [])
            report = sampling_report(compiled, p['eligible_by_category_and_band'])
            self.assertEqual(report['all_type2b_while_sampling_others']['verified_eligible_pairs'], 1)
            selected, manifest, _ = create_selection(compiled, data_root=root / 'data',
                pair_set='type1', mode='sample', sample_size=100, seed=19)
            inventory = selection_inventory(root / 'data', compiled, [])
            self.assertEqual(len(inventory['existing_selection_inventory']), 1)
            self.assertEqual(inventory['final_selections'], [])
            final = selection_inventory(root / 'data', compiled, [selected])['final_selections'][0]
            self.assertEqual(final['selection_id'], manifest['selection_id'])
            self.assertEqual(final['request']['sample']['seed'], 19)
            self.assertEqual(final['distinct_content_pairs'], 1)
            self.assertEqual(final['directional_case_count'], 1)
            self.assertEqual(final['distinct_fragment_contents'], 2)
            self.assertEqual(final['represented_functionality_ids'], [101])

    def test_optional_query_budget_does_not_return_partial_counts(self):
        with sqlite3.connect(':memory:') as connection, redirect_stderr(io.StringIO()):
            queries = Queries(0.000001)
            rows = queries.run(connection, 'expensive',
                'WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<1000000) SELECT SUM(x) FROM n',
                optional=True)
            self.assertIsNone(rows)
            self.assertEqual(len(queries.omitted), 1)
