from __future__ import annotations

from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarking.provenance import sha256_file
from bigMoveBench import thesis_workflow as workflow


class ThesisWorkflowTests(unittest.TestCase):
    def experiment(self, root, name, original='a', modified='b'):
        selection = root / 'cache/bigclonebench/selections' / name
        selection.mkdir(parents=True)
        frames = selection / 'frames.jsonl'
        frames.write_text(json.dumps({'direction': {
            'original_fragment_sha256': original,
            'modified_fragment_sha256': modified}}) + '\n')
        (selection / 'manifest.json').write_text(json.dumps({
            'artifacts': {'frames': {'sha256': sha256_file(frames)}}}))
        directory = root / name
        directory.mkdir()
        manifest = {'experiment_id': name, 'identity': {
            'configuration': {'seed': 1}, 'compiled_dataset': {'dataset_id': 'same'},
            'members': [{'category': 'type1', 'selection_id': name,
                         'selection_manifest_sha256': sha256_file(selection / 'manifest.json')}]}}
        (directory / 'manifest.json').write_text(json.dumps(manifest))
        return directory, manifest

    def test_same_pairs_publish_latest_and_preserve_baseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old, _ = self.experiment(root, 'old')
            new, manifest = self.experiment(root, 'new')
            before = (old / 'manifest.json').read_bytes()
            with patch.object(workflow.thesis, 'verify_experiment', return_value=manifest):
                workflow.publish_latest(new, root / 'results', root / 'cache', old)
            latest = workflow.read_json(root / 'results/bigMoveBench/latest-thesis-preparation.json')
            self.assertEqual(latest['experiment_id'], 'new')
            self.assertEqual(latest['previous_selection']['experiment_id'], 'old')
            self.assertEqual(before, (old / 'manifest.json').read_bytes())

    def test_changed_pair_or_direction_cannot_enable_run(self):
        for original, modified in [('a', 'c'), ('b', 'a')]:
            with self.subTest(original=original, modified=modified), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                old, _ = self.experiment(root, 'old')
                new, manifest = self.experiment(root, 'new', original, modified)
                with patch.object(workflow.thesis, 'verify_experiment', return_value=manifest):
                    with self.assertRaisesRegex(ValueError, 'selected pairs'):
                        workflow.publish_latest(new, root / 'results', root / 'cache', old)
                self.assertFalse((root / 'results/bigMoveBench/latest-thesis-preparation.json').exists())

    def test_changed_frames_are_rejected_even_if_pair_still_parses(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old, _ = self.experiment(root, 'old')
            frames = root / 'cache/bigclonebench/selections/old/frames.jsonl'
            frames.write_text(frames.read_text() + ' ')
            with self.assertRaisesRegex(ValueError, 'selected frames changed'):
                workflow.selected_endpoints(old, root / 'cache')

    def test_failed_refresh_disables_previous_convenience_pointer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pointer = root / 'bigMoveBench/latest-thesis-preparation.json'
            pointer.parent.mkdir()
            pointer.write_text(json.dumps({'schema_version': 1, 'experiment_id': 'old'}))
            with patch('sys.argv', ['workflow', 'prepare', '--results-root', str(root)]), \
                 patch.object(workflow, 'previous_experiment', return_value=None), \
                 patch.object(workflow, 'validate_current_code', side_effect=ValueError('test failed')), \
                 redirect_stderr(io.StringIO()):
                self.assertEqual(workflow.main(), 2)
            self.assertNotIn('experiment_id', workflow.read_json(pointer))

    def test_validation_failure_never_publishes_a_passing_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(workflow, 'run_logged', side_effect=ValueError('test failed')):
                with self.assertRaisesRegex(ValueError, 'test failed'):
                    workflow.validate_current_code(root)
            self.assertFalse(list(root.rglob('validation.json')))

    def test_run_uses_latest_preparation_without_resuming_old_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, manifest = self.experiment(root, 'new')
            registry = workflow.thesis.LabelCorrections().identity['sha256']
            manifest['identity']['correction_registry_sha256'] = registry
            pointer = root / 'bigMoveBench/latest-thesis-preparation.json'
            pointer.parent.mkdir()
            pointer.write_text(json.dumps({'schema_version': 1, 'experiment_id': 'new',
                                          'manifest_sha256': sha256_file(directory / 'manifest.json')}))
            with patch('sys.argv', ['workflow', 'run', '--results-root', str(root)]), \
                 patch.object(workflow.thesis, 'resolve_experiment', return_value=directory), \
                 patch.object(workflow.thesis, 'verify_experiment', return_value=manifest), \
                 patch.object(workflow.thesis, 'execute', return_value=(root / 'fresh-run',
                       {'status': 'completed', 'selected': 5598})) as execute:
                self.assertEqual(workflow.main(), 0)
            self.assertEqual(execute.call_args.args[0], directory)
            self.assertEqual(execute.call_args.kwargs, {})

    def test_run_rejects_new_corrections_before_executing_any_cases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, manifest = self.experiment(root, 'new')
            manifest['identity']['correction_registry_sha256'] = 'stale-registry'
            pointer = root / 'bigMoveBench/latest-thesis-preparation.json'
            pointer.parent.mkdir()
            pointer.write_text(json.dumps({'schema_version': 1, 'experiment_id': 'new',
                                          'manifest_sha256': sha256_file(directory / 'manifest.json')}))
            with patch('sys.argv', ['workflow', 'run', '--results-root', str(root)]), \
                 patch.object(workflow.thesis, 'resolve_experiment', return_value=directory), \
                 patch.object(workflow.thesis, 'verify_experiment', return_value=manifest), \
                 patch.object(workflow.thesis, 'execute') as execute, redirect_stderr(io.StringIO()):
                self.assertEqual(workflow.main(), 2)
            execute.assert_not_called()
