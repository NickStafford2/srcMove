from __future__ import annotations

import argparse
import io
import json
import tempfile
import unittest
from contextlib import closing, redirect_stderr
from dataclasses import replace
from pathlib import Path

from bigMoveBench.catalog import compile_exports
from bigMoveBench.generate_frozen_profiles import generate
from bigMoveBench.frozen_profiles import create_frozen_selection
from bigMoveBench.selection_index import build_index, open_index, sample_frames, LOOKUP_SQL
from bigMoveBench.selection import (_catalog_connection, _frame_inventory, _type3_frame_inventory,
    content_label_conflict_ids, type3_stratum, _indexed_row_query)
from bigMoveBench.tests import test_catalog
from benchmarking.provenance import sha256_file

def compile_fixture(root: Path, repetitions=4):
    bce = test_catalog.BigCloneBenchCompiledDatasetTests().create_bce(root)
    positive = []
    negative = []
    for index, (category, strength) in enumerate(
        [(category, strength) for category, strength in
         ((1, 1.), (2, 1.), (3, 1.), (3, .95), (3, .8), (3, .6), (3, .4), (0, .4))
         for _ in range(repetitions)], start=1
    ):
        functionality = 100 + index
        reduced = bce / "ijadataset" / "bcb_reduced" / str(functionality)
        for source_type, name in (("default", "A"), ("sample", "B")):
            (reduced / source_type).mkdir(parents=True)
            (reduced / source_type / f"{name}.java").write_text(
                f"class {name} {{\n  void method{index}{name}() {{\n    call{index}{name}();\n  }}\n}}\n")
        row = test_catalog.pair_row()
        row.update(functionality_id=functionality, function_id_one=index * 2 + 1000,
                   function_id_two=index * 2 + 1001, syntactic_type=category or 3,
                   similarity_line=strength, similarity_token=strength)
        (positive if category else negative).append(row)
    positive.append(test_catalog.pair_row())
    negative.append(test_catalog.pair_row())
    exports = root / "exports"
    exports.mkdir()
    test_catalog.write_export(exports / "positive.csv", positive)
    test_catalog.write_export(exports / "false.csv", negative)
    return compile_exports(bce_dir=bce, data_root=root / "data",
        exports={"positive": exports / "positive.csv", "known_false_positive": exports / "false.csv"},
        compile_scope={"fixture": "selection-index"})


class SelectionIndexTests(unittest.TestCase):
    def test_index_matches_reference_inventory_and_uses_indexed_lookups(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stderr(io.StringIO()):
            root = Path(temporary)
            compiled = compile_fixture(root)
            before = sha256_file(compiled.directory / 'catalog.sqlite')
            path = root / 'selection-v1.sqlite'
            report = build_index(compiled, path)
            self.assertEqual(before, sha256_file(compiled.directory / 'catalog.sqlite'))
            with closing(open_index(compiled, path)) as index, closing(_catalog_connection(compiled)) as source:
                conflicts = content_label_conflict_ids(source)
                self.assertEqual(len(conflicts), index.execute('SELECT COUNT(*) FROM exclusions').fetchone()[0])
                evidence = json.loads(index.execute('SELECT evidence FROM exclusions').fetchone()[0])
                self.assertEqual({r['pair_kind'] for r in evidence['rows']}, {'positive','known_false_positive'})
                for cat in ('type1', 'type2b', 'type2c', 'known-false-positive'):
                    inventory = list(_frame_inventory(source, cat, 'exact-unordered-fragment-pair', conflicts))
                    self.assertEqual(index.execute('SELECT frames,catalog_rows,source_rows FROM counts WHERE category=?', (cat,)).fetchone(),
                                     (len(inventory), sum(r[1] for r in inventory), sum(r[2] for r in inventory)))
                inventory = list(_type3_frame_inventory(source, 'exact-unordered-fragment-pair', conflicts))
                for band, n, rows, multiplicity in index.execute("SELECT band,frames,catalog_rows,source_rows FROM counts WHERE category='type3'"):
                    subset = [r for r in inventory if type3_stratum(r[3]) == band]
                    self.assertEqual((n,rows,multiplicity), (len(subset), sum(r[1] for r in subset), sum(r[2] for r in subset)))
                plan = [r[3] for r in index.execute('EXPLAIN QUERY PLAN '+LOOKUP_SQL, ('type1','',0))]
                self.assertTrue(any('SEARCH frames USING PRIMARY KEY' in p for p in plan), plan)
                self.assertFalse(any('SCAN' in p for p in plan), plan)
                frame_id = index.execute(LOOKUP_SQL, ('type1','',0)).fetchone()[0]
                row_plan = [r[3] for r in source.execute('EXPLAIN QUERY PLAN '+_indexed_row_query('pair_unordered_idx')+
                    " WHERE p.unordered_pair_id=? AND p.source_status='available'", (frame_id,))]
                self.assertTrue(any('SEARCH p USING INDEX pair_unordered_idx' in p for p in row_plan), row_plan)
                self.assertFalse(any('SCAN p' in p for p in row_plan), row_plan)
                for cat, band, count, _, _ in index.execute('SELECT * FROM counts'):
                    positions = [r[0] for r in index.execute('SELECT position FROM frames WHERE category=? AND band=? ORDER BY position', (cat,band))]
                    self.assertEqual(positions, list(range(count)))
                print('POSITION PLAN:', plan)
                print('CATALOG RETRIEVAL PLAN:', row_plan)
            frames, metadata = sample_frames(compiled, path, seed=7, per_category=4)
            self.assertEqual((frames,metadata), sample_frames(compiled, path, seed=7, per_category=4))
            self.assertNotEqual(frames, sample_frames(compiled, path, seed=8, per_category=4)[0])
            for cat, values in frames.items():
                self.assertEqual(len(values), 4)
                self.assertEqual(len({f['frame_id'] for f in values}), 4)
                for frame in values:
                    self.assertTrue(all(r['benchmark_category'].replace('known_false_positive','known-false-positive') == cat for r in frame['rows']))
                    self.assertTrue(all(r['functionality_id'] != 7 for r in frame['rows']))
            self.assertEqual(sorted(min(min(r['similarity'].values()) for r in f['rows']) for f in frames['type3']), [.4,.6,.8,.95])
            print('FIXTURE CONSTRUCTION:', json.dumps(report, sort_keys=True))
            with self.assertRaisesRegex(ValueError, 'already exists'):
                build_index(compiled, path)
            with self.assertRaisesRegex(ValueError, 'insufficient indexed frames'):
                sample_frames(compiled, path, seed=7)
            with self.assertRaisesRegex(ValueError, 'identity'):
                open_index(replace(compiled, manifest_sha256='wrong'), path)

    def test_duplicates_reverse_rows_and_conservative_band(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stderr(io.StringIO()):
            root = Path(temporary)
            compiled = compile_fixture(root)
            # Modify fixture exports then recompile to exercise real immutable catalogs.
            import csv
            export = root / 'exports' / 'positive.csv'
            with export.open() as stream:
                records = list(csv.DictReader(stream))
            row = dict(records[16])  # strong Type-3
            row['similarity_line'] = '.6'
            records.extend([row, row])  # duplicate source rows retain multiplicity
            reverse = dict(row)
            for one,two in [('function_id_one','function_id_two'),('typeone','typetwo'),('nameone','nametwo'),
                            ('projectone','projecttwo'),('tokensone','tokenstwo'),('internalone','internaltwo')]:
                reverse[one], reverse[two] = reverse[two], reverse[one]
            records.append(reverse)
            test_catalog.write_export(export, records)
            compiled = compile_exports(bce_dir=root / 'BigCloneEval', data_root=root / 'other-data',
                exports={'positive': export, 'known_false_positive': root / 'exports' / 'false.csv'},
                compile_scope={'fixture':'duplicates'})
            path = root / 'index.sqlite'
            build_index(compiled, path)
            with closing(open_index(compiled,path)) as index, closing(_catalog_connection(compiled)) as source:
                frame_id = source.execute('SELECT unordered_pair_id FROM pair_rows WHERE functionality_id=117 LIMIT 1').fetchone()[0]
                self.assertEqual(index.execute('SELECT band,catalog_rows,source_rows FROM frames WHERE category=? AND frame_id=?',
                    ('type3',frame_id)).fetchone(), ('moderate',3,4))
                self.assertEqual(index.execute('SELECT COUNT(*) FROM contributors WHERE frame_id=?',(frame_id,)).fetchone()[0],3)

    def test_profile_generation_and_exclusive_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = io.StringIO()
            with redirect_stderr(output):
                compiled = compile_fixture(root, repetitions=100)
                path = root / 'index.sqlite'
                report = build_index(compiled,path)
                args = argparse.Namespace(dataset=compiled.dataset_id,cache_root=root/'data',
                    output=root/'profiles.jsonl',seed=0,selection=[],selection_index=path)
                generate(args)
            values = [json.loads(line) for line in args.output.read_text().splitlines()]
            self.assertEqual(len(values),501)
            self.assertEqual(len(values[0]['indexed_selection']['population_counts']),8)
            self.assertEqual(values[0]['indexed_selection']['index_sha256'],sha256_file(path))
            self.assertIn('index/materialize',output.getvalue())
            self.assertIn('100%',output.getvalue())
            self.assertIn('profiles/indexed',output.getvalue())
            _, manifest, _ = create_frozen_selection(compiled,data_root=root/'data',pair_set='type3',
                profile='small',preset_path=args.output)
            self.assertEqual(manifest['request']['sample']['indexed_selection'],values[0]['indexed_selection'])
            self.assertEqual(manifest['counts']['selected_frames'],20)
            digest = sha256_file(args.output)
            with self.assertRaisesRegex(ValueError,'already exists'):
                generate(args)
            self.assertEqual(digest,sha256_file(args.output))
            print('LARGER FIXTURE CONSTRUCTION:',json.dumps(report,sort_keys=True))
