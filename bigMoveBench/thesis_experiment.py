#!/usr/bin/env python3
"""Prepare, verify, or execute an explicitly designated immutable thesis cohort.

Preparation never runs detectors or reads evaluation outcomes. Standard profiles
and their historical sampling behavior are unaffected by this entry point.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import shutil
import sqlite3
import sys
import uuid

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarking.identity import canonical_json, content_identifier
from benchmarking.provenance import observe_executable, sha256_file, utc_now
from benchmarking.storage import write_json_atomic
from benchmarking.tooling import find_srcdiff, find_srcmove
from bigMoveBench.adapter import SEMANTIC_ORACLE_VERSION, _type3_frame_strength
from bigMoveBench.audit import git_context, resolve_dataset
from bigMoveBench.benchmark_cases import (BENCHMARK_CASES_SCHEMA_VERSION, SerialBenchmarkCaseRunner,
    load_benchmark_cases, publish_benchmark_cases)
from bigMoveBench.categories import CATEGORY_RULES_VERSION, benchmark_category
from bigMoveBench.evaluate import SCORING_ORACLE_VERSION
from bigMoveBench.label_corrections import LabelCorrections, REGISTRY_PATH
from bigMoveBench.normalized_execution import (EXECUTION_JOURNAL_SCHEMA_VERSION, RETRYABLE_FAILURES,
    SerialBenchmarkExecutionRunner)
from bigMoveBench.paths import DEFAULT_CACHE_ROOT
from bigMoveBench.selection import (SELECTION_SCHEMA_VERSION, TYPE3_STRATA, _artifact, load_selection)
from bigMoveBench.selection_index import ALGORITHM, CATEGORIES, identity, open_index, sample_allocations
from bigMoveBench.synthetic import STABLE_WRAPPER_VERSION

PREPARATION_VERSION = 1
DEFAULT_CONFIG = Path(__file__).with_name('thesis_experiment.json')
DEFAULT_AUDIT = REPO_ROOT / 'benchmark-results/bigMoveBench/chapter6-audit-20261005-verified/audit.json'
DEFAULT_RESULTS = REPO_ROOT / 'benchmark-results'
DEFAULT_VALIDATION = DEFAULT_RESULTS / 'bigMoveBench/thesis-preparation-validation-20261005/validation.json'
DIRECTION = 'fragment-sha256-ascending'


def runtime_identity():
    import _random
    extension_path = getattr(_random, '__file__', None)
    return {'implementation': platform.python_implementation(), 'python_version': platform.python_version(),
            'random_module_sha256': sha256_file(Path(random.__file__)),
            'random_extension_sha256': sha256_file(Path(extension_path)) if extension_path else None,
            'random_extension_origin': '_random extension' if extension_path else _random.__spec__.origin,
            'python_executable_sha256': sha256_file(Path(sys.executable)),
            'random_seed_version': 2}


def source_identity():
    # These are the Python construction/execution sources, not detector provenance.
    paths = sorted([*Path(__file__).parent.glob('*.py'), *(REPO_ROOT / 'benchmarking').glob('*.py')])
    return {p.relative_to(REPO_ROOT).as_posix(): sha256_file(p) for p in paths}


def validate_config(config):
    if (config.get('schema_version') != 1 or config.get('direction') != DIRECTION
            or config.get('designation') not in ('final-thesis-experiment', 'fixture-smoke')
            or type(config.get('seed')) is not int):
        raise ValueError('unsupported experiment configuration')
    keys = [(a['category'], a['band']) for a in config['allocations']]
    expected = [(c, b) for c in CATEGORIES for b in ([v[0] for v in TYPE3_STRATA] if c == 'type3' else [''])]
    if len(keys) != len(set(keys)) or set(keys) != set(expected):
        raise ValueError('configuration must allocate every category/band exactly once')
    for allocation in config['allocations']:
        if (allocation['mode'] not in ('census', 'sample') or type(allocation['count']) is not int
                or allocation['count'] <= 0):
            raise ValueError('invalid experiment quota')
    if type(config.get('expected_total')) is not int or config['expected_total'] != sum(a['count'] for a in config['allocations']):
        raise ValueError('expected total differs from explicit quotas')


def pair_key(frame):
    d = frame['direction']
    return tuple(sorted((d['original_fragment_sha256'], d['modified_fragment_sha256'])))


def frame_metrics(frames):
    pairs = set(); fragments = set(); functions = set(); inputs = set(); bands = Counter()
    for frame in frames:
        a, b = pair_key(frame)
        if (frame['direction']['policy'] != DIRECTION or frame['direction']['original_fragment_sha256'] != a
                or frame['direction']['modified_fragment_sha256'] != b):
            raise ValueError('noncanonical selected direction')
        pairs.add((a, b)); fragments.update((a, b)); functions.update(frame['functionality_ids'])
        inputs.add(frame['generated_input_id'])
        if frame['rows'][0]['benchmark_category'] == 'type3':
            bands[_type3_frame_strength(frame['rows'])[1]] += 1
    return {'selected_frames': len(frames), 'distinct_content_pairs': len(pairs),
            'directional_cases': len(frames), 'distinct_case_ids': len(inputs),
            'distinct_fragment_contents': len(fragments), 'represented_functionality_ids': sorted(functions),
            'represented_functionality_count': len(functions), 'type3_band_counts': dict(bands)}


def conflict_evidence(compiled, index_path):
    with closing(open_index(compiled, index_path)) as index:
        evidence = [json.loads(r[0]) for r in index.execute('SELECT evidence FROM exclusions ORDER BY frame_id')]
    return [{**e, 'disposition': 'excluded_from_scored_selections',
             'catalog_row_count': len(e['rows']),
             'source_row_multiplicity': sum(r['source_row_multiplicity'] for r in e['rows'])} for e in evidence]


def publish_selection(compiled, cache_root, category, frames, allocation_metadata, binding, config, conflicts):
    allocations = [a for a in allocation_metadata if a['category'] == category]
    request = {'selector_version': 'thesis-indexed-selector-v1', 'category_rules_version': CATEGORY_RULES_VERSION,
        'compiled_dataset_id': compiled.dataset_id, 'compiled_manifest_sha256': compiled.manifest_sha256,
        'pair_set': category, 'mode': allocations[0]['mode'], 'dedupe': 'exact-unordered-fragment-pair',
        'direction': DIRECTION, 'final_thesis_experiment': config['designation'] == 'final-thesis-experiment',
        'experiment_design_id': content_identifier('bmb-experiment-design', config),
        'experiment_seed': config['seed'], 'sample': {
            'algorithm': ALGORITHM, 'seed': config['seed'], 'allocations': allocations,
            'seed_derivation': 'UTF-8 canonical_json({algorithm,seed,category,band}); Random(bytes), seed version 2',
            'population_position_order': 'unordered_pair_id ascending within category/band',
            'serialization_order': 'configuration band order, then frame_id ascending in each band',
            'replacement': False, 'shortage_policy': 'fail; no substitution or redistribution',
            'census_rng': 'not used; dense positions 0..population-1', 'runtime': runtime_identity(),
            'index': binding},
        'eligibility': {'source_status': 'available', 'content_label_conflicts': 'excluded',
                        'minimum_tokens': None, 'minimum_judges': None, 'minimum_confidence': None}}
    selection_id = content_identifier('bcb-selection', request)
    root = cache_root / 'bigclonebench/selections'
    final = root / selection_id
    if final.exists():
        existing = load_selection(final, expected_dataset_id=compiled.dataset_id, verification='full')
        if existing['request'] != request:
            raise ValueError('existing selection does not match explicit request')
        return final, existing
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f'.staging-{uuid.uuid4().hex}'
    staging.mkdir()
    try:
        selected_rows = sum(f['catalog_row_count'] for f in frames)
        selected_sources = sum(f['source_row_multiplicity'] for f in frames)
        exclusions = []
        excluded_rows = excluded_sources = excluded_frames = 0
        for conflict in conflicts:
            relevant = [r for r in conflict['rows'] if benchmark_category(r).replace('known_false_positive', 'known-false-positive') == category]
            if relevant:
                row_count = len(relevant); source_count = sum(r['source_row_multiplicity'] for r in relevant)
                exclusions.append({'frame_id': conflict['unordered_pair_id'], 'reason': conflict['reason'],
                                   'catalog_row_count': row_count, 'source_row_multiplicity': source_count})
                excluded_frames += 1; excluded_rows += row_count; excluded_sources += source_count
        for a in allocations:
            exclusions.append({'reason': 'indexed_sample_complement', 'category': category, 'band': a['band'],
                'frames': a['population_frames'] - a['count'],
                'representation': 'dense population positions minus request.sample.allocations.selected_positions_in_draw_order'})
        for filename, values in [('frames.jsonl', frames), ('exclusions.jsonl', exclusions), ('label-conflicts.jsonl', conflicts)]:
            with (staging / filename).open('wb') as stream:
                for value in values:
                    stream.write(canonical_json(value) + b'\n')
        counts = {'eligible_frames': sum(a['population_frames'] for a in allocations),
            'eligible_catalog_rows': sum(a['population_catalog_rows'] for a in allocations),
            'eligible_source_rows': sum(a['population_source_rows'] for a in allocations),
            'selected_frames': len(frames), 'selected_catalog_rows': selected_rows, 'selected_source_rows': selected_sources,
            'sample_excluded_frames': sum(a['population_frames'] - a['count'] for a in allocations),
            'content_label_conflict_excluded_frames': excluded_frames,
            'content_label_conflict_excluded_catalog_rows': excluded_rows,
            'content_label_conflict_excluded_source_rows': excluded_sources,
            'reverse_direction_excluded_catalog_rows': sum(len(f['reverse_direction_exclusions']) for f in frames),
            'reverse_direction_excluded_source_rows': sum(r['source_row_multiplicity'] for f in frames for r in f['reverse_direction_exclusions'])}
        manifest = {'schema_version': SELECTION_SCHEMA_VERSION, 'selection_id': selection_id,
            'created_at': utc_now(), 'request': request,
            'final_thesis_experiment': request['final_thesis_experiment'],
            'compiled_dataset': {'dataset_id': compiled.dataset_id, 'manifest_sha256': compiled.manifest_sha256,
                                 'catalog_sha256': compiled.manifest['artifacts']['catalog']['sha256']},
            'counts': counts, 'strata': allocations if category == 'type3' else None,
            'label_conflicts': {'frames': len(conflicts), 'catalog_rows': sum(c['catalog_row_count'] for c in conflicts),
                               'source_rows': sum(c['source_row_multiplicity'] for c in conflicts)},
            'artifacts': {name: _artifact(staging / filename) for name, filename in
                          [('frames', 'frames.jsonl'), ('exclusions', 'exclusions.jsonl'), ('label_conflicts', 'label-conflicts.jsonl')]}}
        (staging / 'manifest.json').write_bytes(canonical_json(manifest) + b'\n')
        for path in staging.iterdir():
            path.chmod(0o444)
        try:
            os.rename(staging, final)
        except OSError:
            if not final.is_dir():
                raise
            existing = load_selection(final, expected_dataset_id=compiled.dataset_id, verification='full')
            if existing['request'] != request or existing['artifacts'] != manifest['artifacts']:
                raise ValueError('concurrent selection publication differs')
        return final, load_selection(final, expected_dataset_id=compiled.dataset_id, verification='full')
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def development_overlap(frames, paths):
    final_pairs = {pair_key(f) for f in frames}
    result = []
    for path in paths:
        with path.open() as stream:
            header = json.loads(next(stream))
            if header.get('kind') != 'manifest':
                raise ValueError(f'invalid development profile {path}')
            entries = [json.loads(line) for line in stream]
        for profile, quota in header['profiles'].items():
            selected = [e for e in entries if e.get('kind') == 'frame' and
                e.get('band_rank', e.get('rank', 0)) <=
                (header['type3_band_profiles'][profile] if e['pair_set'] == 'type3' else quota)]
            reference = {pair_key(e['frame']) for e in selected}
            shared = final_pairs & reference
            by_category = {}
            for category in CATEGORIES:
                category_pairs = {pair_key(f) for f in frames if
                    f['rows'][0]['benchmark_category'].replace('known_false_positive', 'known-false-positive') == category}
                by_category[category] = len(category_pairs & reference)
            # Hash pair tuples to the same canonical unordered IDs already present in frames.
            pair_ids = {pair_key(f): f['frame_id'] for f in frames}
            result.append({'profile_path': str(path.resolve()), 'profile_file_sha256': sha256_file(path),
                'profile': profile, 'recorded_header': header, 'profile_frames': len(selected),
                'distinct_profile_content_pairs': len(reference), 'shared_content_pairs': len(shared),
                'shared_by_final_category': by_category,
                'shared_unordered_pair_ids': sorted(pair_ids[p] for p in shared),
                'action': 'reported; retained in final experiment'})
    return result


def verify_case_collection(cache_root, members, frames_by_category, registry):
    all_case_ids = set(); all_pairs = set(); member_counts = {}
    for member in members:
        category = member['category']
        verified = load_benchmark_cases(cache_root, member['benchmark_cases_id'], verification='full')
        if verified.manifest_sha256 != member['benchmark_cases_manifest_sha256']:
            raise ValueError('prepared benchmark-cases manifest changed')
        expected = {f['generated_input_id']: f for f in frames_by_category[category]}
        with closing(sqlite3.connect((verified.directory / 'benchmark_cases.sqlite').as_uri() + '?mode=ro&immutable=1', uri=True)) as connection:
            actual = list(connection.execute('SELECT case_id,original_fragment_sha256,modified_fragment_sha256 FROM cases ORDER BY ordinal'))
            for case_id, a, b in actual:
                if case_id not in expected or pair_key(expected[case_id]) != (a, b):
                    raise ValueError('prepared case differs from selected canonical pair')
                if case_id in all_case_ids or (a, b) in all_pairs:
                    raise ValueError('content pair/case occurs more than once across experiment members')
                all_case_ids.add(case_id); all_pairs.add((a, b))
        if len(actual) != len(expected):
            raise ValueError('benchmark-cases count differs from selection')
        # Check compatibility with the actual scratch/metadata and correction APIs.
        # This materializes inputs but executes no detector and inspects no outcomes.
        with SerialBenchmarkCaseRunner(verified) as runner:
            n = 0
            for case in runner.cases():
                registry.match(case.metadata)
                if case.metadata['synthetic_wrapper_version'] != STABLE_WRAPPER_VERSION:
                    raise ValueError('wrapper version mismatch')
                n += 1
                runner.clear_scratch()
        if n != len(expected):
            raise ValueError('serial input contract count mismatch')
        member_counts[category] = n
    return {'directional_case_count': len(all_case_ids), 'distinct_case_ids': len(all_case_ids),
            'distinct_content_pairs': len(all_pairs), 'member_case_counts': member_counts,
            'validation': 'full SQLite/object hashes and inventory; all serial input metadata and frozen correction matches; no detector execution'}


def prepare(config, compiled, index_path, cache_root, results_root, *, audit_binding, development_paths,
            correction_path=REGISTRY_PATH, hash_sources=True, validation=None):
    validate_config(config)
    if config['designation'] == 'final-thesis-experiment':
        if (validation is None or validation.get('status') != 'passed'
                or validation.get('source_sha256') != source_identity()
                or validation.get('runtime') != runtime_identity()):
            raise ValueError('final preparation requires passing fixture/smoke validation of these sources/runtime')
    print('experiment: validate quotas and hydrate selected contributors', file=sys.stderr, flush=True)
    frames_by_category, allocations = sample_allocations(compiled, index_path, seed=config['seed'], allocations=config['allocations'])
    frames = [f for category in CATEGORIES for f in frames_by_category[category]]
    metrics = frame_metrics(frames)
    if any(metrics[k] != config['expected_total'] for k in ('selected_frames', 'distinct_content_pairs', 'distinct_case_ids')):
        raise ValueError('unexpected total or duplicate pair/case across selected categories')
    registry = LabelCorrections(correction_path)
    print('experiment: bind source artifacts (hashes only; no evaluation outcomes)', file=sys.stderr, flush=True)
    # Only once per preparation: no catalog selection scan. Reproduction records
    # Python runtime and exact draw positions; selected fragments are verified later.
    index_sha = sha256_file(index_path)
    catalog_sha = sha256_file(compiled.directory / 'catalog.sqlite') if hash_sources else None
    if catalog_sha is not None and catalog_sha != compiled.manifest['artifacts']['catalog']['sha256']:
        raise ValueError('catalog checksum differs from recorded identity')
    binding = {'identity': identity(compiled), 'sha256': index_sha}
    conflicts = conflict_evidence(compiled, index_path)
    if len(conflicts) != compiled.manifest['counts']['positive_negative_label_conflicts']:
        raise ValueError('companion conflict count differs from compiled manifest')
    members = []
    for category in CATEGORIES:
        print(f'experiment: publish {category} ({len(frames_by_category[category])} pairs)', file=sys.stderr, flush=True)
        directory, selection = publish_selection(compiled, cache_root, category, frames_by_category[category],
                                                  allocations, binding, config, conflicts)
        cases, _ = publish_benchmark_cases(data_root=cache_root, selection=directory)
        members.append({'category': category, 'selection_id': selection['selection_id'],
            'selection_manifest_sha256': sha256_file(directory / 'manifest.json'),
            'benchmark_cases_id': cases.benchmark_cases_id, 'benchmark_cases_manifest_sha256': cases.manifest_sha256,
            'metrics': frame_metrics(frames_by_category[category]), 'selection_counts': selection['counts']})
    print('experiment: verify all prepared input contracts', file=sys.stderr, flush=True)
    input_validation = verify_case_collection(cache_root, members, frames_by_category, registry)
    if input_validation['directional_case_count'] != config['expected_total']:
        raise ValueError('prepared case total differs from plan')
    overlap = development_overlap(frames, development_paths)
    code = source_identity()
    versions = {'preparation_version': PREPARATION_VERSION, 'category_rules_version': CATEGORY_RULES_VERSION,
        'selection_schema_version': SELECTION_SCHEMA_VERSION, 'benchmark_cases_schema_version': BENCHMARK_CASES_SCHEMA_VERSION,
        'wrapper_version': STABLE_WRAPPER_VERSION, 'semantic_oracle_version': SEMANTIC_ORACLE_VERSION,
        'scoring_oracle_version': SCORING_ORACLE_VERSION, 'execution_journal_schema_version': EXECUTION_JOURNAL_SCHEMA_VERSION}
    experiment_identity = {'configuration': config, 'compiled_dataset': identity(compiled), 'index_sha256': index_sha,
        'index_relative_path': index_path.relative_to(cache_root).as_posix(),
        'index_file_metadata': {'size_bytes': index_path.stat().st_size, 'mtime_ns': index_path.stat().st_mtime_ns},
        'sampling_runtime': runtime_identity(), 'members': members, 'correction_registry_sha256': registry.identity['sha256'],
        'construction_and_execution_source_sha256': code, 'versions': versions, 'audit_binding': audit_binding,
        'preparation_validation': validation,
        'development_overlap': overlap, 'metrics': metrics, 'input_validation': input_validation,
        'measurement_policy': {'classification_disagreements': 'measured; no correctness pass gate in this experiment',
            'type2b': 'No dedicated blind-only matching stage assumed. Original Type-2b expectations remain; mismatches are measured.',
            'type3_weak': 'Raw syntactic_type=3, conservative BOTH<0.5; weakly Type-3/Type-4 reference stratum, not verified semantic Type-4.',
            'reviewed_labels': 'Frozen registry; supplied and reviewed outcomes retained separately',
            'pooled_rates': 'No pooled positive/negative or population-wide accuracy claim; report categories and Type-3 bands separately'}}
    experiment_id = content_identifier('bmb-thesis-experiment', experiment_identity)
    root = results_root / 'bigMoveBench/thesis-preparations'
    final = root / experiment_id
    if final.exists():
        verify_experiment(final, cache_root)
        return final
    root.mkdir(parents=True, exist_ok=True)
    staging = root / f'.staging-{uuid.uuid4().hex}'
    staging.mkdir()
    try:
        (staging / 'configuration.json').write_bytes(canonical_json(config) + b'\n')
        (staging / 'reviewed-label-corrections.json').write_bytes(correction_path.read_bytes())
        if sha256_file(staging / 'reviewed-label-corrections.json') != registry.identity['sha256']:
            raise ValueError('correction registry changed during preparation')
        (staging / 'development-overlap.json').write_bytes(canonical_json(overlap) + b'\n')
        (staging / 'validation.json').write_bytes(canonical_json(validation) + b'\n')
        limitations = ['Recorded artifact compiler revision is unknown; current checkout is not attributed to original artifacts.',
            'Development overlap scope is explicitly retained frozen profile files, not execution outcomes or every historical selection.',
            'Shared fragments/functionality IDs mean distinct pairs are not necessarily statistically independent.',
            'No final experiment evaluation has run; construction/hash/validation time is not detector performance.']
        if not hash_sources:
            limitations.append('Full catalog SHA-256 omitted for this fixture; identity metadata and selected fragments verified.')
        manifest = {'schema_version': 1, 'experiment_id': experiment_id, 'identity': experiment_identity,
            'final_thesis_experiment': config['designation'] == 'final-thesis-experiment', 'created_at': utc_now(),
            'current_checkout': git_context(), 'runtime_detail': sys.version,
            'catalog_sha256_observed': catalog_sha, 'limitations': limitations,
            'artifacts': {name: _artifact(staging / name) for name in
                          ('configuration.json', 'reviewed-label-corrections.json', 'development-overlap.json', 'validation.json')}}
        prepare_command = './bin/srcml-dev-shell python3 srcMove/bigMoveBench/thesis_experiment.py prepare'
        execute_command = f'./bin/srcml-dev-shell python3 srcMove/bigMoveBench/thesis_experiment.py execute {experiment_id}'
        manifest['commands'] = {'prepare': prepare_command, 'verify':
            f'./bin/srcml-dev-shell python3 srcMove/bigMoveBench/thesis_experiment.py verify {experiment_id}',
            'execute': execute_command}
        report = ['# Thesis experiment preparation', '', f'Experiment: `{experiment_id}`', '',
                  f"Designation: {config['designation']}; seed: {config['seed']}; canonical direction: {DIRECTION}.", '',
                  f"Actual cases: **{metrics['directional_cases']:,}**; distinct content pairs/case IDs: "
                  f"**{metrics['distinct_content_pairs']:,}/{metrics['distinct_case_ids']:,}**; "
                  f"fragment contents: **{metrics['distinct_fragment_contents']:,}**; functionality IDs: "
                  f"**{metrics['represented_functionality_count']}**.", '',
                  f"Dataset: `{compiled.dataset_id}`; recorded manifest/catalog digests and observed companion digest are in manifest.json.", '',
                  '| Category | Cases | Selection ID | Benchmark-cases ID |', '|---|---:|---|---|']
        for member in members:
            report.append(f"| {member['category']} | {member['metrics']['directional_cases']} | {member['selection_id']} | {member['benchmark_cases_id']} |")
        report += ['', 'Type-3 bands: ' + json.dumps(metrics['type3_band_counts'], sort_keys=True), '',
                   'Represented functionality IDs: ' + json.dumps(metrics['represented_functionality_ids']), '',
                   'Sampling: independently seeded Python random.sample of dense positions without replacement; '
                   'seed bytes and actual positions are retained in selection requests. Census uses every position. '
                   'All quotas are checked before hydration; no replacement or redistribution. Runtime and source hashes are frozen.', '',
                   f"Correction registry SHA-256: `{registry.identity['sha256']}`. Supplied-label and reviewed-label outcomes "
                   'will be reported separately. Type-2b disagreements remain measured outcomes.', '',
                   'Sample complements are represented by indexed positions rather than millions of expanded exclusions. '
                   'All conflict rows and contributor provenance are preserved. No overlapping development pairs were removed.', '']
        for ref in overlap:
            report.append(f"Development `{ref['profile_path']}` / {ref['profile']}: **{ref['shared_content_pairs']}** "
                          f"shared pairs out of {ref['distinct_profile_content_pairs']}; exact IDs and per-category counts in development-overlap.json.")
        report += ['', 'Validation: complete selection artifact hashes, benchmark-case SQLite/object hashes and logical inventory; '
                   'all serial input metadata and correction matches verified. Fixture tests and smoke validation are separate '
                   'from final evidence; see the frozen validation.json snapshot for commands and results.', '',
                   f'Artifacts: `{final}` (manifest, configuration, corrections, development overlap, report). '
                   f'Selections: `{cache_root}/bigclonebench/selections/<selection-id>/`; '
                   f'prepared cases: `{cache_root}/benchmark-cases/<benchmark-cases-id>/`.', '',
                   'Commands from the workspace root:', '', '```bash', prepare_command,
                   manifest['commands']['verify'], execute_command, '```', '', *limitations]
        (staging / 'preparation.md').write_text('\n'.join(report) + '\n')
        manifest['artifacts']['preparation.md'] = _artifact(staging / 'preparation.md')
        (staging / 'manifest.json').write_bytes(canonical_json(manifest) + b'\n')
        for path in staging.iterdir():
            path.chmod(0o444)
        try:
            os.rename(staging, final)
        except OSError:
            if not final.is_dir():
                raise
            verify_experiment(final, cache_root)
        return final
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def resolve_experiment(value, results_root):
    path = Path(value)
    return (path.resolve() if path.is_absolute() or path.exists() else
            results_root.resolve() / 'bigMoveBench/thesis-preparations' / value)


def verify_experiment(directory, cache_root, *, require_current_code=True):
    manifest = json.loads((directory / 'manifest.json').read_text())
    bound = manifest['identity']
    if (manifest.get('schema_version') != 1 or directory.name != manifest['experiment_id']
            or content_identifier('bmb-thesis-experiment', bound) != manifest['experiment_id']):
        raise ValueError('invalid immutable experiment identity')
    validate_config(bound['configuration'])
    index_path = cache_root / bound['index_relative_path']
    if not index_path.resolve().is_relative_to(cache_root.resolve()):
        raise ValueError('index reference escapes cache root')
    compiled, recorded = resolve_dataset(index_path, cache_root)
    if recorded != bound['compiled_dataset'] or {
            'size_bytes': index_path.stat().st_size, 'mtime_ns': index_path.stat().st_mtime_ns} != bound['index_file_metadata']:
        raise ValueError('compiled dataset/index identity or index metadata changed')
    if manifest['final_thesis_experiment'] != (bound['configuration']['designation'] == 'final-thesis-experiment'):
        raise ValueError('final designation differs from bound configuration')
    if require_current_code and (source_identity() != bound['construction_and_execution_source_sha256']
                                or runtime_identity() != bound['sampling_runtime']):
        raise ValueError('construction/execution Python sources or runtime changed since preparation')
    if bound['versions']['scoring_oracle_version'] != SCORING_ORACLE_VERSION:
        raise ValueError('scoring oracle changed since preparation')
    for name, artifact in manifest['artifacts'].items():
        if Path(name).name != name or artifact['path'] != name or sha256_file(directory / name) != artifact['sha256']:
            raise ValueError(f'experiment artifact changed: {name}')
    registry = LabelCorrections(directory / 'reviewed-label-corrections.json')
    if registry.identity['sha256'] != bound['correction_registry_sha256']:
        raise ValueError('frozen correction registry differs from experiment identity')
    if json.loads((directory / 'configuration.json').read_text()) != bound['configuration']:
        raise ValueError('configuration snapshot differs from identity')
    if json.loads((directory / 'development-overlap.json').read_text()) != bound['development_overlap']:
        raise ValueError('development overlap snapshot differs from identity')
    if json.loads((directory / 'validation.json').read_text()) != bound['preparation_validation']:
        raise ValueError('validation snapshot differs from identity')
    frames_by_category = {}
    for member in bound['members']:
        category = member['category']
        path = cache_root / 'bigclonebench/selections' / member['selection_id']
        selection = load_selection(path, expected_dataset_id=bound['compiled_dataset']['dataset_id'], verification='full')
        if sha256_file(path / 'manifest.json') != member['selection_manifest_sha256']:
            raise ValueError('selection manifest differs from experiment identity')
        if selection['request']['sample']['index']['identity'] != bound['compiled_dataset']:
            raise ValueError('selection recorded index identity differs from experiment')
        with (path / 'frames.jsonl').open() as stream:
            frames_by_category[category] = [json.loads(line) for line in stream]
        if frame_metrics(frames_by_category[category]) != member['metrics']:
            raise ValueError('selection metrics differ from experiment identity')
    observed = verify_case_collection(cache_root, bound['members'], frames_by_category, registry)
    if observed != bound['input_validation'] or frame_metrics([f for cat in CATEGORIES for f in frames_by_category[cat]]) != bound['metrics']:
        raise ValueError('experiment input contracts/coverage differ from identity')
    return manifest


def execution_status(summaries):
    # Every detector/scoring category disagreement is retained as a measurement.
    # Semantic ineligibility also remains a reported denominator, not a substitution.
    return 'completed_with_tool_or_oracle_failures' if any(
        s['counts'][outcome] for s in summaries for outcome in RETRYABLE_FAILURES) else 'completed'


def execute(directory, cache_root, results_root, *, srcdiff=None, srcmove=None, resume=None):
    manifest = verify_experiment(directory, cache_root)
    srcdiff = find_srcdiff(REPO_ROOT, srcdiff); srcmove = find_srcmove(REPO_ROOT, srcmove)
    if srcdiff is None or srcmove is None:
        raise ValueError('execution requires runnable srcdiff and srcMove binaries')
    observations = {'srcdiff': observe_executable(srcdiff), 'srcmove': observe_executable(srcmove)}
    registry = LabelCorrections(directory / 'reviewed-label-corrections.json')
    root = (resume.resolve() if resume else results_root / 'bigMoveBench/thesis-runs' /
            f"{utc_now().replace(':', '').replace('+', '-')}-{uuid.uuid4()}")
    configuration = {'experiment_id': manifest['experiment_id'], 'experiment_manifest_sha256': sha256_file(directory / 'manifest.json'),
        'tool_sha256': {key: value['artifact']['sha256'] for key, value in observations.items()},
        'purpose': manifest['identity']['configuration']['designation']}
    if resume:
        if json.loads((root / 'run-configuration.json').read_text()) != configuration:
            raise ValueError('resume experiment/tool identity mismatch')
    else:
        root.mkdir(parents=True, exist_ok=False)
        (root / 'run-configuration.json').write_bytes(canonical_json(configuration) + b'\n')
    summaries = []
    for member in manifest['identity']['members']:
        cases = load_benchmark_cases(cache_root, member['benchmark_cases_id'], verification='full')
        _, summary = SerialBenchmarkExecutionRunner(cases, run_dir=root / member['category'], srcdiff=srcdiff, srcmove=srcmove,
            srcdiff_observation=observations['srcdiff'], srcmove_observation=observations['srcmove'], label_corrections=registry).run()
        summaries.append(summary)
    expected = manifest['identity']['configuration']['expected_total']
    if sum(s['counts']['selected'] for s in summaries) != expected:
        raise ValueError('execution selected count differs from prepared experiment')
    aggregate = {'schema_version': 1, **configuration, 'status': execution_status(summaries), 'selected': expected,
        'completed_at': utc_now(), 'member_summaries': [{'pair_set': m['category'], 'summary': f"{m['category']}/summary.json",
                                                     'counts': s['counts'], 'reviewed_counts': s['reviewed_counts']}
                                                    for m, s in zip(manifest['identity']['members'], summaries)],
        'interpretation': 'Stratum measurements, no classification pass gate; supplied and reviewed counts kept separate. '
                          'See member category_metrics, Type-3 bands, cases.csv and journals for denominators/outcomes.'}
    write_json_atomic(root / 'summary.json', aggregate)
    return root, aggregate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    preparation = sub.add_parser('prepare')
    preparation.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    preparation.add_argument('--index', type=Path, default=DEFAULT_CACHE_ROOT / 'selection-index-v1.sqlite')
    preparation.add_argument('--audit', type=Path, default=DEFAULT_AUDIT)
    preparation.add_argument('--validation-record', type=Path, default=DEFAULT_VALIDATION)
    preparation.add_argument('--development-profile', type=Path, action='append')
    for command in (preparation, sub.add_parser('verify'), sub.add_parser('execute')):
        command.add_argument('--cache-root', type=Path, default=DEFAULT_CACHE_ROOT)
        command.add_argument('--results-root', type=Path, default=DEFAULT_RESULTS)
        if command is not preparation:
            command.add_argument('experiment', help='Experiment ID or immutable preparation directory')
    execution = sub.choices['execute']
    execution.add_argument('--srcdiff', type=Path)
    execution.add_argument('--srcmove', type=Path)
    execution.add_argument('--resume-run', type=Path)
    args = parser.parse_args()
    try:
        cache_root = args.cache_root.resolve(); results_root = args.results_root.resolve()
        if args.command == 'prepare':
            audit = json.loads(args.audit.read_text())
            compiled, recorded = resolve_dataset(args.index, cache_root)
            if (audit['provenance']['recorded_artifact_identity'] != recorded or audit['population']['discrepancies']
                    or audit['population']['unavailable_catalog_rows'] or audit['population']['unavailable_source_rows']):
                raise ValueError('verified audit does not match the fully available experiment dataset/index')
            with closing(open_index(compiled, args.index)) as index:
                counts = [{'category': c, 'band': b, 'frames': n, 'catalog_rows': r, 'source_rows': s}
                          for c, b, n, r, s in index.execute('SELECT * FROM counts ORDER BY category,band')]
            if counts != audit['population']['eligible_by_category_and_band']:
                raise ValueError('index population counts differ from verified audit')
            config = json.loads(args.config.read_text())
            profiles = args.development_profile or [Path(__file__).with_name('frozen_profiles.jsonl'),
                                                   *sorted(cache_root.glob('frozen-profiles*.jsonl'))]
            directory = prepare(config, compiled, args.index.resolve(), cache_root, results_root,
                audit_binding={'audit_json_sha256': sha256_file(args.audit),
                               'audit_md_sha256': sha256_file(args.audit.with_suffix('.md'))}, development_paths=profiles,
                validation=json.loads(args.validation_record.read_text()))
            print(f'experiment_id={directory.name}'); print(f'directory={directory}')
            print(f'execute=./bin/srcml-dev-shell python3 srcMove/bigMoveBench/thesis_experiment.py execute {directory.name}')
        else:
            directory = resolve_experiment(args.experiment, results_root)
            if args.command == 'verify':
                manifest = verify_experiment(directory, cache_root)
                print(f"verified={manifest['experiment_id']} cases={manifest['identity']['metrics']['directional_cases']}")
            else:
                root, summary = execute(directory, cache_root, results_root, srcdiff=args.srcdiff, srcmove=args.srcmove, resume=args.resume_run)
                print(f'run={root} status={summary["status"]} selected={summary["selected"]}')
                return 0 if summary['status'] == 'completed' else 1
        return 0
    except (OSError, ValueError, KeyError, sqlite3.Error, json.JSONDecodeError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
