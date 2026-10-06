"""Check reported moves against reviewed source identity and location."""
from tests.support.execution import require_success, require_tool
import hashlib
import json
from pathlib import Path
from tests.support.execution import artifact_directory, run_logged
import unittest

from benchmarking.tooling import find_srcdiff, find_srcmove

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / 'tests/fixtures/selection'


def normalize(text):
    return ' '.join(text.split())


def text_hash(text):
    return hashlib.sha256(normalize(text).encode()).hexdigest()


class HistoricalType3ContractTests(unittest.TestCase):
    def test_reported_moves_match_source_oracles(self):
        catalog = json.loads((SUITE / 'type3_history_contracts.json').read_text())
        self.assertEqual([c['id'] for c in catalog['cases']],
                         ['functor_competition', 'warp_in_place'])
        srcdiff, srcmove = find_srcdiff(ROOT), find_srcmove(ROOT)
        require_tool(srcdiff)
        require_tool(srcmove)
        with artifact_directory(case_id=self.id()) as directory:
            temp = Path(directory)
            for case in catalog['cases']:
                with self.subTest(case=case['id']):
                    pair = SUITE / case['source_pair']
                    # Protect the reviewed source snapshots, not a detector-derived XML golden.
                    for file, expected in case['source_sha256'].items():
                        self.assertEqual(hashlib.sha256((pair / file).read_bytes()).hexdigest(), expected)
                    xml = temp / 'srcdiff.xml'
                    run_logged([str(srcdiff), str(pair / 'before'), str(pair / 'after'),
                                    '-o', str(xml)], check=True, capture_output=True)
                    docs, annotations = [], []
                    for mode in ('ordinary', 'diagnostic', 'results_only'):
                        output, annotated = temp / (mode + '.json'), temp / (mode + '.xml')
                        command = [str(srcmove), str(xml), '--results', str(output)]
                        if mode != 'ordinary':
                            command.append('--diagnostics')
                        if mode == 'results_only':
                            command.append('--results-only')
                        else:
                            command.insert(2, str(annotated))
                        run_logged(command, check=True, capture_output=True)
                        docs.append(json.loads(output.read_text()))
                        if mode != 'results_only':
                            annotations.append(annotated.read_bytes())
                    self.assertEqual(annotations[0], annotations[1])
                    self.assertEqual(docs[1], docs[2])
                    self.assertEqual(docs[0], {k: v for k, v in docs[1].items() if k != 'diagnostics'})
                    diagnostics = docs[1]['diagnostics']
                    self.assertEqual(diagnostics['schema_version'], 4)
                    # Independently reviewed source occurrences also constrain
                    # fallback groups exposed when edited parents are rejected.
                    # These are surviving source occurrences, not moved code.
                    for region in case.get('stationary_source_regions', []):
                        source_path = region['source_file']
                        old_paths = set()
                        for source_side, side in [('before', 'delete'), ('after', 'insert')]:
                            lines = (pair / source_side / source_path).read_text().splitlines()
                            ranges = region[source_side + '_line_ranges']
                            for first, last in ranges:
                                self.assertEqual(normalize('\n'.join(lines[first - 1:last])),
                                                 region['normalized_text'])
                            function_path = "src:function[src:name='" + region['function_name'] + "']"
                            candidates = [c for c in diagnostics['candidates']
                                          if c['side'] == side
                                          and c['role'] == 'structural_child'
                                          and c['construct'] == region['construct']
                                          and function_path in c['xpath']
                                          and normalize(c['raw_text']) == region['normalized_text']]
                            self.assertEqual(len(candidates), len(ranges))
                            if source_side == 'before':
                                old_paths.update(c['xpath'] for c in candidates)
                        annotated = [(move['content_relationship'], path)
                                     for move in docs[0]['moves']
                                     for path in move['from_xpaths'] if path in old_paths]
                        self.assertEqual(annotated, [], region['source_oracle_reason'])
                    endpoints = {}
                    for endpoint in case['endpoints']:
                        for source_side, side in [('before', 'delete'), ('after', 'insert')]:
                            candidates = [c for c in diagnostics['candidates'] if c['side'] == side
                                          and c['construct'] == endpoint['construct']
                                          and text_hash(c['raw_text']) == endpoint[source_side + '_text_sha256']]
                            self.assertEqual(len(candidates), 1)
                            candidate = candidates[0]
                            # Resolve every observed endpoint back to the reviewed source revision.
                            occurrences = sum(normalize(p.read_text()).count(normalize(candidate['raw_text']))
                                              for p in (pair / source_side).rglob('*') if p.is_file())
                            self.assertEqual(occurrences, 1)
                            endpoints[endpoint['id'], source_side] = candidate
                    records = [r for r in diagnostics['correspondences'] if r['correspondence_kind'] == 'type3']
                    reviewed_ids = set()
                    for edge in case['edges']:
                        before = endpoints[edge['before'], 'before']
                        after = endpoints[edge['after'], 'after']
                        key = (before['candidate_id'], after['candidate_id'])
                        reviewed_ids.add(key)
                        matches = [r for r in records if (r['delete_candidate_id'], r['insert_candidate_id']) == key]
                        self.assertEqual(len(matches), 1)
                        record = matches[0]
                        oracle = edge['source_oracle']
                        selected = any(m['content_relationship'] == 'type3' and m['from_xpaths'] == [before['xpath']]
                                       and m['to_xpaths'] == [after['xpath']] for m in docs[0]['moves'])
                        self.assertEqual(selected, record['current_result'] == 'move')
                        if case['id'] == 'functor_competition':
                            continuing = edge['before'] == edge['after']
                            self.assertEqual(oracle['identity'], 'continuing_construct' if continuing else 'different_constructs')
                            self.assertEqual(oracle['is_move'], continuing)
                            self.assertEqual(oracle['location'], 'relocated' if continuing else 'not_applicable')
                            self.assertEqual(record['cardinality'], 'competing_edges')
                        else:
                            self.assertEqual(oracle['identity'], 'continuing_construct')
                            self.assertEqual(oracle['location'], 'stationary')
                            self.assertFalse(oracle['is_move'])
                            self.assertEqual(record['cardinality'], 'one_to_one')
                        # A recorded error must fail, rather than become required output.
                        with self.subTest(case=case['id'], before=edge['before'], after=edge['after']):
                            self.assertEqual(
                                selected, oracle['is_move'],
                                f"{case['id']}: {edge['before']} -> {edge['after']}: "
                                + ('srcMove should report this move' if oracle['is_move']
                                   else 'srcMove should not report this as a move')
                                + f"; source review: {oracle['reason']}")
                    # Protect the full 2x2 subgraph, including selection losers.
                    old_ids = {c['candidate_id'] for (name, side), c in endpoints.items() if side == 'before'}
                    new_ids = {c['candidate_id'] for (name, side), c in endpoints.items() if side == 'after'}
                    self.assertEqual(reviewed_ids, {(r['delete_candidate_id'], r['insert_candidate_id']) for r in records
                                                   if r['delete_candidate_id'] in old_ids and r['insert_candidate_id'] in new_ids})
