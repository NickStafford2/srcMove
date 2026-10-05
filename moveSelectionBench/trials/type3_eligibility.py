#!/usr/bin/env python3
"""Prepare/replay an isolated Type-3 eligibility experiment; never patch production."""
import argparse
import collections
import difflib
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'src/move_registry/content_group_builder.cpp'
MARKER = '    prefer_stronger_descendant_bundles(proposals, registry);'
# Applied only to a Git-exported source tree. Counts precede location pruning.
INSERT = '''    // EXPERIMENT ONLY: retain the verified graph and original partner degrees.
    std::vector<std::size_t> trial_degrees(registry.total_record_count(), 0);
    for (const type3_edge &edge : type3_edges) {
      ++trial_degrees[edge.del_id];
      ++trial_degrees[edge.ins_id];
    }
    for (match_proposal &proposal : proposals) {
      if (proposal.group.match != content_relationship::type3) continue;
      const auto del_id = proposal.group.del_ids.front();
      const auto ins_id = proposal.group.ins_ids.front();
      const auto decision = classify_correspondence(
          registry, del_id, ins_id, content_relationship::type3);
      bool accepted = move_eligible(decision.classification);
#ifdef SRCMOVE_TRIAL_REJECT_COMPETING
      accepted = accepted && trial_degrees[del_id] == 1 && trial_degrees[ins_id] == 1;
#endif
      proposal.disabled = proposal.disabled || !accepted;
    }
'''


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def prepare(out, inventory):
    out.mkdir(parents=True, exist_ok=False)
    commit = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    archive = subprocess.check_output(['git', '-C', str(ROOT), 'archive', commit])
    export = out / 'source'
    export.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(export, filter='data')
    path = export / SOURCE
    old = path.read_text()
    if old.count(MARKER) != 1:
        raise ValueError('Expected one pre-hierarchy insertion point')
    new = old.replace(MARKER, INSERT + MARKER)
    path.write_text(new)
    (out / 'trial.patch').write_text(''.join(difflib.unified_diff(
        old.splitlines(True), new.splitlines(True), fromfile='a/' + SOURCE, tofile='b/' + SOURCE)))
    shutil.copy2(ROOT / 'build/srcMove', out / 'baseline-srcMove')
    shutil.copy2(ROOT / 'build/srcMove.build-receipt.json', out / 'baseline.build-receipt.json')
    inputs = []
    for case in json.loads(inventory.read_text())['cases']:
        path = ROOT / case['input']
        if sha(path) != case['input_sha256']:
            raise ValueError(f'Input changed since inventory: {path}')
        inputs.append({k: case[k] for k in ['suite', 'name', 'input', 'input_sha256']})
    write(out / 'plan.json', dict(base_commit=commit, frozen_at=time.time(),
        policies={'baseline': 'unchanged production', 'location': 'relocated Type-3 edges only',
                  'uncontested': 'relocated and both original verified degrees equal one; sensitivity bound, not identity proof'},
        stage='disable proposals before existing hierarchy and greedy selection',
        limits='Retained, previously inspected sample; not new held-out validation. No thresholds, Type-2 reservation, carrying or repeated-group changes.',
        source_archive_sha256=hashlib.sha256(archive).hexdigest(),
        patched_file_sha256=sha(export / SOURCE), patch_sha256=sha(out / 'trial.patch'),
        baseline_sha256=sha(out / 'baseline-srcMove'), inputs=inputs))
    print(f'Prepared {len(inputs)} frozen inputs in {out}')


def stable_diagnostics(diag):
    result = dict(diag)
    result['correspondences'] = [{k: v for k, v in r.items() if k != 'current_result'}
                                 for r in diag['correspondences']]
    result['type3_pairs'] = [dict(r, outcome='verified_edge')
                            if r['outcome'] in ('selected', 'selection_rejected') else r
                            for r in diag['type3_pairs']]
    return result


def compare(out):
    plan = json.loads((out / 'plan.json').read_text())
    bins = {'baseline': out / 'baseline-srcMove', 'location': out / 'location/srcMove',
            'uncontested': out / 'uncontested/srcMove'}
    if sha(bins['baseline']) != plan['baseline_sha256']:
        raise ValueError('Baseline executable changed after preparation')
    if sha(out / 'trial.patch') != plan['patch_sha256']:
        raise ValueError('Trial patch changed after preparation')
    if sha(out / 'source' / SOURCE) != plan['patched_file_sha256']:
        raise ValueError('Trial source changed after preparation')
    report = dict(base_commit=plan['base_commit'], binary_sha256={k: sha(p) for k, p in bins.items()}, cases=[])
    for case in plan['inputs']:
        path = ROOT / case['input']
        if sha(path) != case['input_sha256']:
            raise ValueError(f'Frozen input changed: {path}')
        dest = out / 'comparison' / case['suite'] / case['name']
        dest.mkdir(parents=True, exist_ok=True)
        docs = {}
        for variant, binary in bins.items():
            extra = ['--min-granularity', 'fragment'] if case['suite'] == 'source' else []
            command = list(map(str, [binary, path, dest / (variant + '.xml'), '--results',
                                    dest / (variant + '.json'), '--diagnostics', *extra]))
            start = time.monotonic()
            subprocess.run(command, check=True, capture_output=True)
            doc = json.loads((dest / (variant + '.json')).read_text())
            docs[variant] = doc
            # Check actual non-diagnostic and results-only executions, not just stripped JSON.
            for mode, flags in [('ordinary', []), ('results_only', ['--diagnostics', '--results-only'])]:
                target = dest / (variant + '-' + mode + '.json')
                cmd = [str(binary), str(path)]
                if mode == 'ordinary': cmd.append(str(dest / (variant + '-ordinary.xml')))
                subprocess.run(cmd + ['--results', str(target), *flags, *extra], check=True, capture_output=True)
                observed = json.loads(target.read_text())
                expected = doc if mode == 'results_only' else {k: v for k, v in doc.items() if k != 'diagnostics'}
                if observed != expected: raise AssertionError((case['name'], variant, mode))
            if (dest / (variant + '.xml')).read_bytes() != (dest / (variant + '-ordinary.xml')).read_bytes():
                raise AssertionError('Diagnostic annotations changed')
            (dest / (variant + '.seconds')).write_text(str(time.monotonic() - start))
        key = lambda m: (m['content_relationship'], tuple(m['from_xpaths']), tuple(m['to_xpaths']))
        old = {key(m): m for m in docs['baseline']['moves']}
        row = dict(case, variants={})
        for variant in ['location', 'uncontested']:
            doc = docs[variant]
            if stable_diagnostics(doc['diagnostics']) != stable_diagnostics(docs['baseline']['diagnostics']):
                raise AssertionError(('matching/location diagnostics changed', case['name'], variant))
            new = {key(m): m for m in doc['moves']}
            row['variants'][variant] = dict(removed=[old[k] for k in sorted(old.keys() - new.keys())],
                added=[new[k] for k in sorted(new.keys() - old.keys())],
                baseline_content_relationships=docs['baseline']['content_relationships'], content_relationships=doc['content_relationships'])
        report['cases'].append(row)
        if any(v['removed'] or v['added'] for v in row['variants'].values()):
            print(case['suite'], case['name'], {k: (len(v['removed']), len(v['added'])) for k, v in row['variants'].items()}, flush=True)
    report['case_counts'] = dict(collections.Counter(c['suite'] for c in report['cases']))
    write(out / 'comparison.json', report)
    print(f'Compared {len(report["cases"])} cases; all three modes equivalent; matching/location evidence unchanged')


def controls(out):
    """A rejected location must not manufacture degree-one identity, on either side."""
    src = 'http://www.srcML.org/srcML/src'
    diff = 'http://www.srcML.org/srcDiff'
    ET.register_namespace('', src)
    ET.register_namespace('diff', diff)
    results = []
    for scenario in ['competing_insertions', 'competing_deletions']:
        original = ET.parse(ROOT / 'moveSelectionBench/type3_cases' / (scenario + '.xml')).getroot()
        archive = ET.Element('{' + src + '}unit')
        same = ET.SubElement(archive, '{' + src + '}unit', filename='same.cpp', language='C++')
        other = ET.SubElement(archive, '{' + src + '}unit', filename='other.cpp', language='C++')
        for index, payload in enumerate(list(original)):
            exclusive_index = 2 if scenario == 'competing_insertions' else 1
            (other if index == exclusive_index else same).append(payload)
        dest = out / 'controls' / scenario
        dest.mkdir(parents=True, exist_ok=True)
        xml = dest / 'input.xml'
        ET.ElementTree(archive).write(xml, encoding='utf-8', xml_declaration=True)
        for variant, binary in [('baseline', out / 'baseline-srcMove'),
                                ('location', out / 'location/srcMove'),
                                ('uncontested', out / 'uncontested/srcMove')]:
            output = dest / (variant + '.json')
            subprocess.run(list(map(str, [binary, xml, '--results-only', '--diagnostics',
                                         '--results', output])), check=True, capture_output=True)
            data = json.loads(output.read_text())['diagnostics']
            candidates = {c['candidate_id']: c for c in data['candidates']}
            records = [r for r in data['correspondences'] if r['correspondence_kind'] == 'type3'
                       and candidates[r['delete_candidate_id']]['construct'] == 'if_stmt']
            assert len(records) == 2
            assert sorted(r['shadow_change'] for r in records) == ['ambiguous', 'relocated']
            assert all(r['cardinality'] == 'competing_edges' for r in records)
            assert all(max(r['delete_verified_partner_count'], r['insert_verified_partner_count']) == 2
                       for r in records)
            selected = sum(r['current_result'] == 'move' for r in records)
            assert selected == (0 if variant == 'uncontested' else 1)
            results.append(dict(scenario=scenario, variant=variant, selected=selected,
                                original_degree_preserved=True, input_sha256=sha(xml)))
    write(out / 'controls.json', results)
    print('Both endpoint-direction degree controls pass for all variants')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'compare', 'controls'])
    parser.add_argument('--output', type=Path, default=ROOT / 'build/type3-eligibility-trial')
    parser.add_argument('--inventory', type=Path, default=ROOT / 'build/type3-historical-contracts/comparison.json')
    args = parser.parse_args()
    if args.action == 'prepare': prepare(args.output.resolve(), args.inventory)
    elif args.action == 'compare': compare(args.output.resolve())
    else: controls(args.output.resolve())
