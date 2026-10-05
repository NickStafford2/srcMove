#!/usr/bin/env python3
"""Read-only Chapter 6 population/selection audit; writes only new reports.

Run from the workspace root using bin/srcml-dev-shell. No selection publication,
compilation, detector execution, or artifact mutation is performed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
import time

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bigMoveBench.catalog import load_compiled_dataset
from bigMoveBench.categories import CATEGORY_RULES_VERSION
from bigMoveBench.paths import DEFAULT_CACHE_ROOT
from bigMoveBench.selection import TYPE3_STRATA, _catalog_connection, load_selection
from bigMoveBench.selection_index import CATEGORIES, open_index
from benchmarking.provenance import sha256_file


def readonly(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    return connection


def resolve_dataset(index_path, cache_root):
    """Resolve exactly the recorded ID, then reuse the canonical identity checks."""
    with closing(readonly(index_path)) as connection:
        recorded = json.loads(connection.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()[0])
    dataset_id = recorded['dataset_id']
    if Path(dataset_id).name != dataset_id or not dataset_id.startswith('bcb-dataset-'):
        raise ValueError('invalid recorded dataset ID')
    directory = cache_root.resolve() / 'bigclonebench' / 'compiled' / dataset_id
    compiled = load_compiled_dataset(directory, verification='identity')
    with closing(open_index(compiled, index_path)):
        pass
    return compiled, recorded


class Queries:
    """Bound SQL work in time and label observations as audit overhead only."""
    def __init__(self, seconds):
        self.seconds = seconds
        self.observations = []
        self.omitted = []

    def run(self, connection, name, sql, parameters=(), *, optional=False):
        print(f'audit: {name}', file=sys.stderr, flush=True)
        started = time.monotonic()
        connection.set_progress_handler(lambda: int(time.monotonic() - started > self.seconds), 10000)
        try:
            return list(connection.execute(sql, parameters))
        except sqlite3.OperationalError as error:
            if optional and str(error) == 'interrupted':
                self.omitted.append(f'{name}: exceeded {self.seconds:g}s query budget; no partial count reported')
                return None
            raise
        finally:
            connection.set_progress_handler(None, 0)
            self.observations.append({'check': name, 'audit_wall_seconds': time.monotonic() - started})


def overlap_accounting(category_counts, edges):
    """Each edge links two category memberships for the same unordered pair."""
    memberships = defaultdict(set)
    for frame_id, left, right in edges:
        memberships[frame_id].update((left, right))
    excess = sum(len(categories) - 1 for categories in memberships.values())
    total = sum(category_counts.values())
    return {'category_memberships': total, 'distinct_eligible_content_pairs': total - excess,
            'pairs_in_multiple_categories': len(memberships), 'excess_memberships': excess,
            'category_counts_sum_to_distinct_total': excess == 0,
            'overlap_patterns': dict(Counter(','.join(sorted(v)) for v in memberships.values()))}


def population(source, index, queries):
    index.row_factory = sqlite3.Row
    status = [dict(r) for r in queries.run(source, 'catalog/source status accounting',
        'SELECT source_status, COUNT(*) catalog_rows, SUM(source_row_multiplicity) source_rows '
        'FROM pair_rows GROUP BY source_status')]
    counts = [dict(r) for r in index.execute('SELECT * FROM counts ORDER BY category,band')]
    observed = [dict(r) for r in queries.run(index, 'verify companion frame counts',
        'SELECT category,band,COUNT(*) frames,SUM(catalog_rows) catalog_rows,SUM(source_rows) source_rows '
        'FROM frames GROUP BY category,band ORDER BY category,band')]
    # Zero-count bands do not appear in GROUP BY.
    positive_counts = [r for r in counts if r['frames']]
    discrepancies = []
    if positive_counts != observed:
        discrepancies.append('Companion stored counts differ from actual frames aggregates.')
    totals = {cat: sum(r['frames'] for r in observed if r['category'] == cat) for cat in CATEGORIES}
    # Avoid grouping the multimillion Type-3 population into a large temporary table.
    # UNIQUE(category,frame_id) supplies probes into every other category.
    edges = []
    for n, left in enumerate(CATEGORIES):
        for right in CATEGORIES[n + 1:]:
            outer, inner = sorted((left, right), key=lambda cat: totals[cat])
            rows = queries.run(index, f'category overlap {left}/{right}',
                'SELECT a.frame_id FROM frames a WHERE a.category=? AND EXISTS '
                '(SELECT 1 FROM frames b WHERE b.category=? AND b.frame_id=a.frame_id)', (outer, inner))
            edges.extend((r[0], left, right) for r in rows)
    accounting = overlap_accounting(totals, edges)
    before = queries.run(source, 'distinct materialized content pairs before conflicts',
        'SELECT COUNT(*) FROM (SELECT unordered_pair_id FROM pair_rows INDEXED BY pair_unordered_idx '
        'WHERE unordered_pair_id IS NOT NULL GROUP BY unordered_pair_id)')[0][0]
    conflict_rows = conflict_sources = exclusions = 0
    for row in index.execute('SELECT evidence FROM exclusions'):
        evidence = json.loads(row[0])
        exclusions += 1
        conflict_rows += len(evidence['rows'])
        conflict_sources += sum(r['source_row_multiplicity'] for r in evidence['rows'])
    available = next((r for r in status if r['source_status'] == 'available'), {'catalog_rows': 0, 'source_rows': 0})
    if before - exclusions != accounting['distinct_eligible_content_pairs']:
        discrepancies.append('Before-conflict distinct pairs minus exclusions differs from distinct eligible total.')
    for field in ('catalog_rows', 'source_rows'):
        excluded = conflict_rows if field == 'catalog_rows' else conflict_sources
        if sum(r[field] for r in observed) + excluded != available[field]:
            discrepancies.append(f'Eligible + conflict {field} do not equal available {field}.')
    failures = []
    for row in queries.run(source, 'extraction failures by reason',
        "SELECT extraction_status,extraction_error,COUNT(*) materializations,COUNT(DISTINCT function_id) functions "
        "FROM function_materializations WHERE extraction_status!='success' GROUP BY extraction_status,extraction_error"):
        item = dict(row)
        # UNION removes a pair affected on both ends; multiplicity is added once.
        affected = queries.run(source, 'pairs affected by extraction reason',
            'SELECT COUNT(*) catalog_rows,COALESCE(SUM(source_row_multiplicity),0) source_rows FROM pair_rows '
            'WHERE pair_id IN (SELECT p.pair_id FROM function_materializations m JOIN pair_rows p '
            'ON p.function_id_one=m.function_id AND p.functionality_id=m.functionality_id '
            'WHERE m.extraction_status=? AND m.extraction_error IS ? UNION '
            'SELECT p.pair_id FROM function_materializations m JOIN pair_rows p '
            'ON p.function_id_two=m.function_id AND p.functionality_id=m.functionality_id '
            'WHERE m.extraction_status=? AND m.extraction_error IS ?)',
            (item['extraction_status'], item['extraction_error']) * 2)[0]
        item.update(dict(affected)); failures.append(item)
    return {'imported_source_rows': sum(r['source_rows'] for r in status),
            'catalog_rows': sum(r['catalog_rows'] for r in status), 'by_source_status': status,
            'unavailable_catalog_rows': sum(r['catalog_rows'] for r in status if r['source_status'] == 'unavailable'),
            'unavailable_source_rows': sum(r['source_rows'] for r in status if r['source_status'] == 'unavailable'),
            'extraction_failure_reasons': failures,
            'failure_units': 'Materializations are (functionality_id,function_id), not distinct fragment contents; '
                             'functions are distinct per reason. Affected catalog/source pairs count each pair once per reason; reasons may overlap.',
            'distinct_content_pairs_before_conflicts': before,
            'content_pairs_excluded_for_label_conflicts': exclusions,
            'conflict_catalog_rows': conflict_rows, 'conflict_source_rows': conflict_sources,
            'eligible_by_category_and_band': counts, 'category_accounting': accounting,
            'discrepancies': discrepancies}


def eligible_coverage(source, index_path, queries):
    source.execute('ATTACH DATABASE ? AS companion', (Path(index_path).resolve().as_uri() + '?mode=ro&immutable=1',))
    # Probe existing function-side indexes instead of scanning all contributors.
    clauses = []
    for side, idx in (('one', 'pair_function_one_idx'), ('two', 'pair_function_two_idx')):
        clauses.append(f"EXISTS (SELECT 1 FROM pair_rows p INDEXED BY {idx} "
            f"WHERE p.function_id_{side}=m.function_id AND p.functionality_id=m.functionality_id "
            "AND p.source_status='available' AND NOT EXISTS "
            "(SELECT 1 FROM companion.exclusions e WHERE e.frame_id=p.unordered_pair_id))")
    rows = queries.run(source, 'eligible fragment/functionality coverage via materialization probes',
        "SELECT DISTINCT m.fragment_sha256,m.functionality_id FROM function_materializations m "
        "WHERE m.extraction_status='success' AND (" + ' OR '.join(clauses) + ')', optional=True)
    if rows is None:
        return {'status': 'omitted_query_budget'}
    functionalities = sorted({r[1] for r in rows})
    return {'status': 'observed', 'distinct_fragment_contents': len({r[0] for r in rows}),
            'represented_functionality_ids': functionalities, 'represented_functionality_count': len(functionalities)}


def git_context():
    def git(*args):
        return subprocess.check_output(['git', '-C', str(REPO_ROOT), *args], text=True).strip()
    paths = ['bigMoveBench', 'benchmarking']
    return {'revision': git('rev-parse', 'HEAD'), 'relevant_paths': paths,
            'relevant_code_has_uncommitted_changes': bool(git('status', '--porcelain', '--', *paths)),
            'relevant_status': git('status', '--porcelain', '--', *paths).splitlines(),
            'interpretation': 'Current checkout only; no evidence this revision created the catalog, index, or frozen profiles.'}


def sampling_report(compiled, counts):
    dataset = compiled.dataset_id
    return {
        'population': 'Available catalog rows, excluding positive/negative unordered content conflicts; '
                      'deduplicated by exact unordered fragment content within each derived category. '
                      'No minimum token/judge/confidence filter. Category overlap is audited separately.',
        'type3_ranges': [{'band': n, 'lower_inclusive': lo, 'upper_exclusive': hi} for n, lo, hi in TYPE3_STRATA],
        'type3_strength': 'Minimum across contributing category rows of min(similarity_line, similarity_token).',
        'indexed': 'generate_frozen_profiles.py --selection-index uses selection_index.sample_frames: '
                   'without replacement within each category/band, random.Random seeded with canonical JSON bytes '
                   '{algorithm,seed,category,band}; random.sample of dense positions ordered by unordered_pair_id. '
                   'Default 100 per category, Type-3 exactly 25 per band. Any shortage rejects before retrieval; '
                   'no redistribution. Python API per_category must be positive and divisible by four; '
                   'per_category=80 would select all 80 Type-2b and 80 in every other category (20 per Type-3 band). '
                   'The generator CLI does not expose per_category.',
        'direct': 'selection.py --mode sample uses deterministic SHA-256 rank of canonical {seed,frame_id}, '
                  'selecting the lowest ranks without replacement within each pair set. Non-Type-3 shortages '
                  'return min(requested,eligible). Type-3 allocates at least one per required band, then equal '
                  'waterfill in declared band order; small strata surrender quota; caps total at eligible population; '
                  'empty required bands or total target below four fail. --mode census selects all eligible frames. '
                  '--dedupe none instead samples unique imported catalog assertions, retaining source multiplicity, '
                  'and uses catalog-row direction.',
        'current_profiles': 'generate_frozen_profiles.py without --selection-index uses direct full-frame ranking '
                            '(or verified --selection reuse). Requires exactly 100 in every category; therefore '
                            'cannot publish a profile from the current 80-pair Type-2b population. '
                            'suite.py --profile small/medium consumes frozen rank prefixes (20/100; Type-3 5/25 '
                            'per band), does not resample, and rejects incomplete profiles or incompatible legacy '
                            'category membership. suite.py --profile full uses direct census.',
        'all_type2b_while_sampling_others': {
            'verified_eligible_pairs': sum(r['frames'] for r in counts if r['category'] == 'type2b'),
            'procedure': 'Use separate direct selections: Type-2b census, other categories sample with declared sizes/seeds. '
                         'A Type-2b direct sample request of 100 also returns all 80. No current profile-generator CLI '
                         'supports a mixed 80/100 profile. Commands below are guidance only; audit does not execute them.',
            'commands': [f'python3 srcMove/bigMoveBench/selection.py {dataset} --pair-set type2b --mode census',
                         f'python3 srcMove/bigMoveBench/selection.py {dataset} --pair-set <type1|type2c|type3|known-false-positive> --mode sample --sample-size 100 --seed <declared-seed>']},
        'direction': 'Default: fragment-sha256-ascending, one directional generated case per selected unordered '
                     'content pair; reverse catalog rows remain provenance, not extra cases.',
        'independence': 'Without replacement applies within a category selection; pairs may share fragments or functionalities. '
                        'Equal category/band allocations are not population-proportional; pooled rates require a declared interpretation.'}


def selection_metrics(directory, compiled):
    manifest = load_selection(directory, expected_dataset_id=compiled.dataset_id, verification='full')
    categories = Counter(); pairs = set(); fragments = set(); functionalities = set(); directions = set()
    with (directory / manifest['artifacts']['frames']['path']).open() as stream:
        for line in stream:
            frame = json.loads(line)
            direction = frame['direction']
            a, b = direction['original_fragment_sha256'], direction['modified_fragment_sha256']
            # Even --dedupe none can contain multiple row frames for the same content pair.
            pairs.add(tuple(sorted((a, b))))
            fragments.update((a, b)); directions.add((a, b))
            functionalities.update(frame['functionality_ids'])
            categories[manifest['request']['pair_set']] += 1
    return {'selection_id': manifest['selection_id'], 'request': manifest['request'],
            'category_counts': dict(categories), 'distinct_content_pairs': len(pairs),
            'directional_case_count': sum(categories.values()), 'distinct_directional_inputs': len(directions),
            'distinct_fragment_contents': len(fragments), 'represented_functionality_ids': sorted(functionalities)}


def selection_inventory(cache_root, compiled, final_paths):
    inventory = []; designated = list(final_paths)
    root = cache_root / 'bigclonebench' / 'selections'
    for path in sorted(root.glob('*/manifest.json')):
        value = json.loads(path.read_text())
        request = value.get('request', {})
        inventory.append({'path': str(path), 'selection_id': value.get('selection_id'),
                          'dataset_id': request.get('compiled_dataset_id'), 'pair_set': request.get('pair_set'),
                          'mode': request.get('mode'), 'seed': (request.get('sample') or {}).get('seed'),
                          'direction': request.get('direction'), 'counts': value.get('counts'),
                          'category_rules_version': request.get('category_rules_version')})
        if value.get('final_thesis_experiment') is True:
            designated.append(path.parent)
    return {'status': 'explicitly_designated' if designated else 'no_final_selection_designated_in_inspected_scope',
            'designation_rule': 'Explicit --final-selection user designation or manifest final_thesis_experiment=true; '
                                'recency, filename, profile size, and ordinary execution do not designate finality.',
            'scope': 'All cache/bigclonebench/selections/*/manifest.json plus supplied explicit paths. '
                     'Repository methodology instructs choosing/freezing a design; no final assignment is inferred. '
                     'Private thesis notes and external communications are outside this audit scope.',
            'existing_selection_inventory': inventory,
            'final_selections': [selection_metrics(Path(p).resolve(), compiled) for p in dict.fromkeys(designated)]}


def frozen_report():
    path = Path(__file__).with_name('frozen_profiles.jsonl')
    with path.open() as stream:
        header = json.loads(next(stream))
    return {'path': str(path), 'sha256': sha256_file(path), 'recorded_manifest': header,
            'interpretation': 'Historical artifact metadata, not proof of generating checkout. Missing category-rule '
                              'version retains legacy raw types. Recorded Type-3 generation label is not evidence '
                              'of uniform full-population sampling.',
            'historical_code_inspected': 'git show d87d12b:bigMoveBench/generate_frozen_profiles.py',
            'historical_procedure': 'In inspected historical code, _probe_type3_frames reads first 2000 available '
                                    'raw syntactic_type=3 rows per similarity band ordered by pair_id; retains at '
                                    'most 100 unique nonconflicting candidates per band globally, retrieves full '
                                    'contributors, reassigns by conservative strength, takes first 25 per band, '
                                    'then SHA-256 seed ranks for frozen prefixes. _pivot is defined but unused; '
                                    'seed does not randomize the candidate population. Shortage below 25 in any '
                                    'band fails. This retired code explains why the stored “seeded primary-key '
                                    'probes” label alone must not support a full-population random-sample claim. '
                                    'It is not asserted to have created the checked-in artifact.'}


def markdown(report):
    p = report['population']; a = p['category_accounting']; provenance = report['provenance']
    lines = ['# BigMoveBench Chapter 6 audit', '', f"Audit date: {provenance['audit_date_utc']}", '',
             f"Dataset: `{provenance['recorded_artifact_identity']['dataset_id']}`", '',
             f"Recorded catalog SHA-256: `{provenance['recorded_artifact_identity']['catalog_sha256']}`", '',
             f"Recorded manifest SHA-256: `{provenance['recorded_artifact_identity']['manifest_sha256']}`", '',
             f"Index version: {provenance['recorded_artifact_identity']['index_version']}; category rules: "
             f"{provenance['recorded_artifact_identity']['category_rules_version']}.", '',
             f"Current checkout: `{provenance['current_checkout']['revision']}`; relevant uncommitted changes: "
             f"{provenance['current_checkout']['relevant_code_has_uncommitted_changes']}. "
             'This does not identify the artifact-producing revision.', '',
             f"Command: `{provenance['audit_command']}`", '',
             '## Population', '',
             f"Imported source rows: **{p['imported_source_rows']:,}**; catalog rows: **{p['catalog_rows']:,}**.", '',
             '| Source status | Catalog rows | Source rows (multiplicity) |', '|---|---:|---:|']
    for r in p['by_source_status']:
        lines.append(f"| {r['source_status']} | {r['catalog_rows']:,} | {r['source_rows']:,} |")
    lines += ['', f"Unavailable: {p['unavailable_catalog_rows']:,} catalog rows / {p['unavailable_source_rows']:,} source rows.", '',
              f"Extraction failure reasons: {json.dumps(p['extraction_failure_reasons'])}. {p['failure_units']}", '',
              f"Distinct materialized unordered pairs before conflicts: **{p['distinct_content_pairs_before_conflicts']:,}**. "
              f"Conflict exclusions: **{p['content_pairs_excluded_for_label_conflicts']:,}** content pairs "
              f"({p['conflict_catalog_rows']:,} catalog / {p['conflict_source_rows']:,} source rows). "
              'Unavailable rows have no complete content-pair identity.', '',
              '| Eligible category / Type-3 range | Content pairs | Catalog rows | Source rows |', '|---|---:|---:|---:|']
    for r in p['eligible_by_category_and_band']:
        lines.append(f"| {r['category']} {r['band']} | {r['frames']:,} | {r['catalog_rows']:,} | {r['source_rows']:,} |")
    lines += ['', f"Distinct eligible total: **{a['distinct_eligible_content_pairs']:,}**; category membership sum: "
              f"**{a['category_memberships']:,}**; pairs in multiple categories: **{a['pairs_in_multiple_categories']:,}**. "
              f"Counts sum to distinct total: **{a['category_counts_sum_to_distinct_total']}**.", '',
              f"Eligible coverage: `{json.dumps(p['eligible_coverage'], sort_keys=True)}`", '',
              f"Accounting discrepancies: {json.dumps(p['discrepancies'])}", '', '## Selection procedures', '']
    for key in ('population', 'type3_strength', 'indexed', 'direct', 'current_profiles', 'direction', 'independence'):
        lines += [report['sampling'][key], '']
    lines += ['Type-3 ranges: ' + json.dumps(report['sampling']['type3_ranges']), '',
              report['sampling']['all_type2b_while_sampling_others']['procedure'], '',
              'Type-2b eligible count: ' + str(report['sampling']['all_type2b_while_sampling_others']['verified_eligible_pairs']), '',
              'Guidance commands (not executed):', '', '```sh',
              *report['sampling']['all_type2b_while_sampling_others']['commands'], '```', '',
              '## Frozen artifact and final experiment', '', report['frozen_profile']['interpretation'], '',
              report['frozen_profile']['historical_procedure'], '',
              f"Inspected historical code: `{report['frozen_profile']['historical_code_inspected']}`.", '',
              f"Final designation: **{report['selections']['status']}**. {report['selections']['scope']}", '',
              f"Inspected {len(report['selections']['existing_selection_inventory'])} existing selection manifests; "
              'identities, seeds, category counts, and direction policies are in JSON. '
              'Final selection coverage is reported only for an explicit designation.', '',
              'Before defining the final experiment: designate immutable selections; declare category and band sizes, '
              'seed, Type-2b census, direction, coverage, and pooled-rate interpretation; freeze dataset/category/oracle '
              'identities. The existing 100-per-category profile path cannot cover the 80-pair Type-2b census.', '',
              '## Audit limits and timings', '', *report['verification']['omitted_checks'], '',
              'Query timings in JSON are audit/storage overhead observations only; no detector performance was measured.']
    if report['selections']['final_selections']:
        lines += ['', 'Explicit final selection metrics:', '', '```json',
                  json.dumps(report['selections']['final_selections'], indent=2), '```']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, default=DEFAULT_CACHE_ROOT / 'selection-index-v1.sqlite')
    parser.add_argument('--cache-root', type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument('--output-dir', type=Path, required=True, help='New benchmark-results directory; refuses overwrite')
    parser.add_argument('--query-budget-seconds', type=float, default=120)
    parser.add_argument('--final-selection', type=Path, action='append', default=[], help='Explicit user final designation; never inferred')
    args = parser.parse_args()
    if args.query_budget_seconds <= 0:
        parser.error('query budget must be positive')
    output = args.output_dir.resolve()
    if output.exists():
        parser.error('output directory already exists; choose a new directory')
    compiled, identity = resolve_dataset(args.index, args.cache_root)
    queries = Queries(args.query_budget_seconds)
    report = {'schema_version': 1, 'provenance': {
        'recorded_artifact_identity': identity, 'compiled_directory': str(compiled.directory),
        'compiled_created_at': compiled.manifest.get('created_at'),
        'recorded_compiler_metadata': compiled.manifest['compiler'],
        'current_category_rules_version': CATEGORY_RULES_VERSION, 'current_checkout': git_context(),
        'audit_command': shlex.join(['python3', *sys.argv]),
        'audit_date_utc': datetime.now(timezone.utc).isoformat(),
        'artifact_producing_revision': 'Not recorded in inspected dataset/index metadata; not inferred.'}}
    report['provenance']['current_audit_and_selection_source_sha256'] = {
        str(path.relative_to(REPO_ROOT)): sha256_file(path)
        for path in (Path(__file__), *[Path(__file__).with_name(name) for name in
                     ('catalog.py', 'categories.py', 'selection.py', 'selection_index.py',
                      'generate_frozen_profiles.py', 'frozen_profiles.py', 'suite.py')])}
    with closing(open_index(compiled, args.index)) as index, closing(_catalog_connection(compiled)) as source:
        report['population'] = population(source, index, queries)
        report['population']['eligible_coverage'] = eligible_coverage(source, args.index, queries)
    report['recorded_manifest_counts'] = compiled.manifest['counts']
    observed = report['population']
    for key, actual in [('catalog_pair_rows', observed['catalog_rows']),
                        ('unique_unordered_pairs', observed['distinct_content_pairs_before_conflicts']),
                        ('positive_negative_label_conflicts', observed['content_pairs_excluded_for_label_conflicts'])]:
        if compiled.manifest['counts'].get(key) != actual:
            observed['discrepancies'].append(f'Manifest {key} differs: recorded {compiled.manifest["counts"].get(key)}, observed {actual}.')
    report['sampling'] = sampling_report(compiled, observed['eligible_by_category_and_band'])
    report['frozen_profile'] = frozen_report()
    report['selections'] = selection_inventory(args.cache_root, compiled, args.final_selection)
    report['verification'] = {'sqlite': 'mode=ro; immutable=1 for audit connections; canonical dataset identity loader also uses mode=ro',
        'artifact_validation': 'Canonical identity verification (manifest hash/identity, catalog metadata/size/mtime, index identity). '
                               'Recorded catalog digest is not recomputed.',
        'omitted_checks': ['Full 7GB catalog SHA-256, full fragment-CAS hashing, and full contributor/category-rule '
                           'rederivation omitted; reuse validated versioned companion, verify its frame aggregates, '
                           'catalog totals, pair identities, category overlap and conservation equations.',
                           'Nondesignated selection frame files and execution databases are not scanned; no final experiment inferred.'] + queries.omitted}
    report['audit_overhead_observations'] = queries.observations
    output.mkdir(parents=True, exist_ok=False)
    (output / 'audit.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    (output / 'audit.md').write_text(markdown(report))
    print(output / 'audit.json'); print(output / 'audit.md')
    return 1 if observed['discrepancies'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
