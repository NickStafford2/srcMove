#!/usr/bin/env python3
"""Validate and prepare a thesis rerun, or execute the latest preparation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import uuid

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarking.provenance import sha256_file, utc_now
from benchmarking.storage import write_json_atomic
from bigMoveBench import thesis_experiment as thesis


def read_json(path):
    return json.loads(Path(path).read_text())


def run_logged(command, log_path):
    with log_path.open('w') as log:
        process = subprocess.Popen(command, cwd=REPO_ROOT, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            log.write(line)
            print(line, end='', flush=True)
        if process.wait():
            raise ValueError(f'validation failed; see {log_path}')


def validate_current_code(results_root):
    sources = thesis.source_identity()
    runtime = thesis.runtime_identity()
    directory = results_root / 'bigMoveBench/thesis-validations' / uuid.uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    command = ['make', 'test-bigmovebench', 'test-classification']
    run_logged(command, directory / 'tests.log')
    smoke = directory / 'smoke'
    run_logged([sys.executable, str(REPO_ROOT / 'tests/tooling/bigmovebench/run_thesis_smoke.py'),
                '--output-dir', str(smoke)], directory / 'smoke.log')
    record = read_json(smoke / 'smoke-validation.json')
    if record['status'] != 'completed':
        raise ValueError('fixture smoke did not complete successfully')
    if sources != thesis.source_identity() or runtime != thesis.runtime_identity():
        raise ValueError('benchmark sources/runtime changed during validation')
    path = directory / 'validation.json'
    write_json_atomic(path, {
        'schema_version': 1, 'status': 'passed', 'date_utc': utc_now(),
        'source_sha256': sources, 'runtime': runtime,
        'tests': {'command': command, 'log_sha256': sha256_file(directory / 'tests.log')},
        'smoke': {'record': record, 'log_sha256': sha256_file(directory / 'smoke.log')},
        'interpretation': 'Correctness tests and synthetic fixtures; no thesis-population outcomes.'})
    return path


def selected_endpoints(directory, cache_root):
    """Compare directional pairs and Type-3 bands, not schema-dependent case IDs."""
    manifest = read_json(directory / 'manifest.json')
    endpoints = {}
    for member in manifest['identity']['members']:
        selection = cache_root / 'bigclonebench/selections' / member['selection_id']
        frames_path = selection / 'frames.jsonl'
        selection_manifest = read_json(selection / 'manifest.json')
        if sha256_file(selection / 'manifest.json') != member['selection_manifest_sha256']:
            raise ValueError('baseline selection manifest changed')
        if sha256_file(frames_path) != selection_manifest['artifacts']['frames']['sha256']:
            raise ValueError('baseline selected frames changed')
        pairs = set()
        with frames_path.open() as stream:
            for line in stream:
                frame = json.loads(line)
                direction = frame['direction']
                band = (thesis._type3_frame_strength(frame['rows'])[1]
                        if member['category'] == 'type3' else '')
                pair = (direction['original_fragment_sha256'],
                        direction['modified_fragment_sha256'], band)
                if pair in pairs:
                    raise ValueError('duplicate selected pair')
                pairs.add(pair)
        endpoints[member['category']] = pairs
    return endpoints


def previous_experiment(results_root, config, explicit=None):
    if explicit:
        return thesis.resolve_experiment(explicit, results_root)
    # Use the first completed run of this design as the comparison baseline.
    # Source hashes and schema versions may change; its selection must not.
    for path in sorted((results_root / 'bigMoveBench/thesis-runs').glob('*/summary.json')):
        summary = read_json(path)
        if summary.get('status') != 'completed':
            continue
        directory = thesis.resolve_experiment(summary['experiment_id'], results_root)
        manifest_path = directory / 'manifest.json'
        manifest = read_json(manifest_path)
        if sha256_file(manifest_path) != summary['experiment_manifest_sha256']:
            raise ValueError('previous experiment manifest changed')
        if manifest['identity']['configuration'] == config:
            return directory
    return None


def publish_latest(directory, results_root, cache_root, baseline):
    manifest = thesis.verify_experiment(directory, cache_root)
    comparison = None
    if baseline:
        old = read_json(baseline / 'manifest.json')
        if (old['identity']['configuration'] != manifest['identity']['configuration']
                or old['identity']['compiled_dataset'] != manifest['identity']['compiled_dataset']):
            raise ValueError('previous experiment uses a different design or dataset')
        if selected_endpoints(baseline, cache_root) != selected_endpoints(directory, cache_root):
            raise ValueError('selected pairs, directions, or similarity bands changed; run not enabled')
        comparison = {'experiment_id': old['experiment_id'],
                      'manifest_sha256': sha256_file(baseline / 'manifest.json'),
                      'status': 'same pairs, directions, and similarity bands'}
    pointer = results_root / 'bigMoveBench/latest-thesis-preparation.json'
    write_json_atomic(pointer, {'schema_version': 1, 'experiment_id': directory.name,
                               'manifest_sha256': sha256_file(directory / 'manifest.json'),
                               'previous_selection': comparison})
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run'))
    parser.add_argument('--cache-root', type=Path, default=thesis.DEFAULT_CACHE_ROOT)
    parser.add_argument('--results-root', type=Path, default=thesis.DEFAULT_RESULTS)
    parser.add_argument('--previous-experiment')
    args = parser.parse_args()
    cache = args.cache_root.resolve()
    results = args.results_root.resolve()
    pointer = results / 'bigMoveBench/latest-thesis-preparation.json'
    try:
        if args.command == 'prepare':
            baseline = previous_experiment(results, read_json(thesis.DEFAULT_CONFIG),
                                           args.previous_experiment)
            # Invalidate an earlier convenience pointer before attempting refresh.
            # Immutable preparations and result directories are never replaced.
            write_json_atomic(pointer, {'schema_version': 1, 'status': 'preparing'})
            validation = validate_current_code(results)
            command = [sys.executable, str(REPO_ROOT / 'bigMoveBench/thesis_experiment.py'),
                       'prepare', '--cache-root', str(cache), '--results-root', str(results),
                       '--index', str(cache / 'selection-index-v1.sqlite'),
                       '--validation-record', str(validation)]
            completed = subprocess.run(command, cwd=REPO_ROOT, stdout=subprocess.PIPE,
                                       text=True, check=True)
            print(completed.stdout, end='')
            directory = Path(next(line.split('=', 1)[1] for line in completed.stdout.splitlines()
                                  if line.startswith('directory=')))
            manifest = publish_latest(directory, results, cache, baseline)
            print(f"prepared={directory.name} cases={manifest['identity']['metrics']['directional_cases']}")
            if baseline:
                print('Verified the same selected pairs, directions, and similarity bands as the previous run.')
            print('Next: make bigmovebench-thesis-run')
        else:
            if not pointer.exists():
                raise ValueError('run make bigmovebench-thesis-prepare first')
            latest = read_json(pointer)
            if latest.get('schema_version') != 1 or 'experiment_id' not in latest:
                raise ValueError('preparation is incomplete; run make bigmovebench-thesis-prepare')
            directory = thesis.resolve_experiment(latest['experiment_id'], results)
            if sha256_file(directory / 'manifest.json') != latest['manifest_sha256']:
                raise ValueError('latest preparation manifest changed')
            manifest = thesis.verify_experiment(directory, cache)
            if manifest['identity']['correction_registry_sha256'] != thesis.LabelCorrections().identity['sha256']:
                raise ValueError('label corrections changed; run make bigmovebench-thesis-prepare')
            root, summary = thesis.execute(directory, cache, results)
            print(f"run={root} status={summary['status']} selected={summary['selected']}")
            return 0 if summary['status'] == 'completed' else 1
        return 0
    except (OSError, ValueError, KeyError, StopIteration, subprocess.CalledProcessError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
