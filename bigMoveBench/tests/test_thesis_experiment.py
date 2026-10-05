from __future__ import annotations

from contextlib import closing, redirect_stderr
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bigMoveBench.thesis_experiment import (DEFAULT_CONFIG, development_overlap, execute, execution_status,
    frame_metrics, prepare, validate_config, verify_experiment)
from bigMoveBench.selection_index import build_index, sample_allocations
from bigMoveBench.tests.test_selection_index import compile_fixture
from bigMoveBench.tests.test_normalized_execution import FakeToolAttempts, TOOL_OBSERVATION
from bigMoveBench.contracts import SemanticResult, SemanticStatus


def fixture_config():
    config = json.loads(DEFAULT_CONFIG.read_text())
    config['designation'] = 'fixture-smoke'
    for a in config['allocations']:
        a['count'] = 4 if a['mode'] == 'census' else 3 if a['category'] == 'known-false-positive' else 2
    config['expected_total'] = sum(a['count'] for a in config['allocations'])
    return config


class ThesisExperimentTests(unittest.TestCase):
    def fixture(self, root):
        compiled = compile_fixture(root, repetitions=4)
        cache = root / 'data'
        index = cache / 'selection-index-v1.sqlite'
        build_index(compiled, index)
        return compiled, cache, index

    def test_agreed_design_exact_counts_and_band_allocations(self):
        config = json.loads(DEFAULT_CONFIG.read_text())
        validate_config(config)
        self.assertEqual(config['seed'], 20261005)
        self.assertEqual(config['expected_total'], 5598)
        self.assertEqual([a['count'] for a in config['allocations']], [951,80,567,500,500,500,500,2000])
        bad = copy.deepcopy(config); bad['allocations'].append(bad['allocations'][0])
        with self.assertRaisesRegex(ValueError, 'every category'):
            validate_config(bad)
        bad = copy.deepcopy(config); bad['expected_total'] = 5600
        with self.assertRaisesRegex(ValueError, 'expected total'):
            validate_config(bad)

    def test_mixed_census_sample_determinism_no_replacement_and_fail_fast(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stderr(io.StringIO()):
            compiled, cache, index = self.fixture(Path(temporary))
            config = fixture_config()
            first, metadata = sample_allocations(compiled, index, seed=config['seed'], allocations=config['allocations'])
            self.assertEqual((first, metadata), sample_allocations(compiled, index, seed=config['seed'], allocations=config['allocations']))
            other, _ = sample_allocations(compiled, index, seed=19, allocations=config['allocations'])
            self.assertEqual(first['type1'], other['type1'])
            self.assertEqual(first['type2b'], other['type2b'])
            self.assertNotEqual(first['type3'], other['type3'])
            self.assertEqual([len(first[c]) for c in ('type1','type2b','type2c','type3','known-false-positive')], [4,4,4,8,3])
            all_frames = [f for frames in first.values() for f in frames]
            self.assertEqual(frame_metrics(all_frames)['distinct_content_pairs'], 23)
            self.assertEqual(frame_metrics(all_frames)['type3_band_counts'], {'very_strong':2,'strong':2,'moderate':2,'weak':2})
            for a in metadata:
                self.assertEqual(len(set(a['selected_positions_in_draw_order'])), a['count'])
                self.assertEqual(a['population_frames'], 4)
            bad = copy.deepcopy(config['allocations']); bad[3]['count'] = 5
            with patch('bigMoveBench.selection_index._row_groups_for_identifiers', side_effect=AssertionError('must not hydrate')):
                with self.assertRaisesRegex(ValueError, 'insufficient indexed'):
                    sample_allocations(compiled, index, seed=1, allocations=bad)
                bad = copy.deepcopy(config['allocations']); bad[0]['count'] = 3
                with self.assertRaisesRegex(ValueError, 'unexpected census'):
                    sample_allocations(compiled, index, seed=1, allocations=bad)

    def test_immutable_publication_overlap_corrections_contract_and_execution(self):
        with tempfile.TemporaryDirectory() as temporary, redirect_stderr(io.StringIO()):
            root = Path(temporary)
            compiled, cache, index = self.fixture(root)
            config = fixture_config()
            frames, _ = sample_allocations(compiled, index, seed=config['seed'], allocations=config['allocations'])
            # A retained development profile contains one matching pair and one
            # duplicate contributor frame: overlap is exact content, not row count.
            profile = root / 'development.jsonl'
            reference = frames['type1'][0]
            profile.write_text(json.dumps({'kind':'manifest','profiles':{'small':2,'medium':2},
                'type3_band_profiles':{'small':1,'medium':1}}) + '\n' + '\n'.join(
                json.dumps({'kind':'frame','pair_set':'type1','rank':i,'frame':reference}) for i in (1,2)))
            directory = prepare(config, compiled, index, cache, root / 'results',
                audit_binding={'fixture':True}, development_paths=[profile], hash_sources=False)
            manifest = verify_experiment(directory, cache)
            self.assertFalse(manifest['final_thesis_experiment'])
            self.assertEqual(manifest['identity']['metrics']['directional_cases'], 23)
            self.assertEqual(manifest['identity']['input_validation']['distinct_case_ids'], 23)
            self.assertEqual(manifest['identity']['development_overlap'][0]['shared_content_pairs'], 1)
            self.assertEqual(manifest['identity']['development_overlap'][0]['profile_frames'], 2)
            self.assertEqual(manifest['identity']['development_overlap'][0]['distinct_profile_content_pairs'], 1)
            before = (directory / 'manifest.json').read_bytes()
            self.assertEqual(directory, prepare(config, compiled, index, cache, root / 'results',
                audit_binding={'fixture':True}, development_paths=[profile], hash_sources=False))
            self.assertEqual(before, (directory / 'manifest.json').read_bytes())
            # Serial journal, CSV/summary schemas and frozen registry are exercised
            # with fake admitted tools; classification disagreements must not gate.
            tools = FakeToolAttempts()
            def score(metadata, *args, **kwargs):
                outcome = 'wrong_classification' if metadata['benchmark_category'] == 'type2b' else 'oracle_pass'
                return outcome, [], {'from':'exact','to':'exact'}, {'move_count':1}
            with patch('bigMoveBench.thesis_experiment.observe_executable', return_value=TOOL_OBSERVATION), \
                 patch('bigMoveBench.thesis_experiment.find_srcdiff', return_value=Path('/fake/srcdiff')), \
                 patch('bigMoveBench.thesis_experiment.find_srcmove', return_value=Path('/fake/srcMove')), \
                 patch('bigMoveBench.normalized_execution.execute_attempt', side_effect=tools), \
                 patch('bigMoveBench.normalized_execution.validate_srcdiff_semantics',
                       return_value=SemanticResult(SemanticStatus.ELIGIBLE, {'reason':'fixture'})), \
                 patch('bigMoveBench.normalized_execution._score_completed_case', side_effect=score):
                run, summary = execute(directory, cache, root / 'results')
            self.assertEqual(summary['status'], 'completed')
            self.assertEqual(summary['selected'], 23)
            type2b = json.loads((run / 'type2b/summary.json').read_text())
            self.assertEqual(type2b['counts']['wrong_classification'], 4)
            self.assertEqual(type2b['reviewed_counts']['wrong_classification'], 4)
            self.assertEqual(type2b['label_corrections']['registry']['sha256'], manifest['identity']['correction_registry_sha256'])
            self.assertIn('reviewed_outcome', (run / 'type2b/cases.csv').read_text().splitlines()[0])
            frozen = directory / 'reviewed-label-corrections.json'
            frozen.chmod(0o644); frozen.write_bytes(frozen.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'artifact changed'):
                verify_experiment(directory, cache)

    def test_disagreements_are_measurements_tool_failures_are_reported(self):
        self.assertEqual(execution_status([{'counts': {'upstream_failure':0,'srcmove_tool_failure':0,
            'oracle_failure':0,'wrong_classification':80,'srcmove_miss':2,'srcdiff_semantic_ineligible':1}}]), 'completed')
        self.assertEqual(execution_status([{'counts': {'upstream_failure':1,'srcmove_tool_failure':0,
            'oracle_failure':0}}]), 'completed_with_tool_or_oracle_failures')
