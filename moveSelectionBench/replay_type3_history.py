#!/usr/bin/env python3
"""Replay the frozen source-reviewed Phase 4.2 sample without relabeling it."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SRC = '{http://www.srcML.org/srcML/src}'
DIFF = '{http://www.srcML.org/srcDiff}'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text):
    return ''.join(text.split())


def revision_text(node, side, membership='common'):
    if node.tag in (DIFF + 'delete', DIFF + 'insert', DIFF + 'common'):
        membership = node.tag[len(DIFF):]
    text = (node.text or '') if membership in ('common', side) else ''
    for child in node:
        text += revision_text(child, side, membership)
        if membership in ('common', side):
            text += child.tail or ''
    return text


def resolve_candidates(candidates, tree, target, side, source_side):
    endpoints, resolution = [], {}
    for candidate in candidates:
        if candidate['side'] != side or candidate['construct'] != target['construct']:
            continue
        paths = candidate['filename'].split('|')
        filename = paths[0 if side == 'delete' else -1]
        if target.get(source_side + '_file', filename) != filename:
            continue
        expected_text = normalize(target[source_side + '_text'])
        method = 'raw_text'
        if normalize(candidate['raw_text']) != expected_text:
            # A candidate's raw text can include opposite-revision
            # comment text. Resolve its exact archive XPath and
            # verify the source text with revision-state overrides.
            nodes = tree.findall('.' + candidate['xpath'],
                                 {'src': SRC[1:-1], 'diff': DIFF[1:-1]})
            if len(nodes) != 1 or normalize(revision_text(nodes[0], side)) != expected_text:
                continue
            method = 'revision_filtered_xml'
        endpoints.append(candidate)
        resolution[str(candidate['candidate_id'])] = method
    return endpoints, resolution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repositories', type=Path, default=ROOT / 'reference-repositories')
    parser.add_argument('--srcdiff', required=True, type=Path)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--candidate', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--sample', type=Path,
                        default=ROOT / 'moveSelectionBench/type3_history_sample.json')
    args = parser.parse_args()
    manifest_path = args.sample
    manifest = json.loads(manifest_path.read_text())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    commands, cases, targets = [], [], []

    def run(command):
        command = list(map(str, command))
        commands.append(command)
        return subprocess.run(command, check=True, capture_output=True).stdout

    for case in manifest['cases']:
        dest = output / case['id']
        repository = args.repositories / case['repository']
        for side, commit in [('before', case['parent']), ('after', case['commit'])]:
            revision_files = case.get('revision_files', {}).get(side, case['files'])
            for name in revision_files:
                path = dest / side / name
                content = run(['git', '-C', repository, 'show', commit + ':' + name])
                expected = manifest['source_sha256'][str(path.relative_to(output))]
                if hashlib.sha256(content).hexdigest() != expected:
                    raise ValueError(f'Git source hash mismatch: {path}')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            actual = {str(path.relative_to(dest / side))
                      for path in (dest / side).rglob('*') if path.is_file()}
            if actual != set(revision_files):
                raise ValueError(f'Unexpected files in frozen revision root: {dest / side}')
        (dest / 'source.diff').write_bytes(run(['git', '-C', repository, 'diff',
            '--no-ext-diff', '--unified=12', case['parent'], case['commit'], '--', *case['files']]))
        run([args.srcdiff, dest / 'before', dest / 'after', '-o', dest / 'srcdiff.xml'])
        docs = {}
        for variant, executable in [('baseline', args.baseline), ('current', args.candidate)]:
            run([executable, dest / 'srcdiff.xml', dest / (variant + '.xml'),
                 '--results', dest / (variant + '.json'), '--diagnostics'])
            docs[variant] = json.loads((dest / (variant + '.json')).read_text())
        ordinary = lambda doc: {k: v for k, v in doc.items() if k != 'diagnostics'}
        diag = docs['current']['diagnostics']
        tree = ET.parse(dest / 'srcdiff.xml')
        cases.append(dict(id=case['id'], input_sha256=sha(dest / 'srcdiff.xml'),
            ordinary_json_equal=ordinary(docs['baseline']) == ordinary(docs['current']),
            annotated_xml_equal=(dest / 'baseline.xml').read_bytes() == (dest / 'current.xml').read_bytes(),
            verified_type3_edges=sum(r['correspondence_kind'] == 'type3' for r in diag['correspondences'])))
        for target in manifest['source_review']['targets']:
            if target['case'] != case['id']:
                continue
            endpoints, resolution = {}, {}
            for side, source_side in [('delete', 'before'), ('insert', 'after')]:
                endpoints[side], methods = resolve_candidates(
                    diag['candidates'], tree, target, side, source_side)
                resolution.update(methods)
            ids = {side: {c['candidate_id'] for c in cs} for side, cs in endpoints.items()}
            records = [r for r in diag['correspondences'] if r['delete_candidate_id'] in ids['delete']
                       and r['insert_candidate_id'] in ids['insert']]
            shared = [n for n in tree.iter(SRC + target['construct'])
                      if normalize(revision_text(n, 'delete')) == normalize(target['before_text'])
                      and normalize(revision_text(n, 'insert')) == normalize(target['after_text'])]
            targets.append(dict(id=target['id'], case=case['id'],
                expected_location=target['expected_location'], candidates=endpoints,
                endpoint_resolution=resolution,
                correspondences=records, shared_revision_filtered_construct_count=len(shared),
                shortlist=[r for r in diag['type3_pairs'] if r['delete_candidate_id'] in ids['delete']
                           and r['insert_candidate_id'] in ids['insert']]))
    report = dict(sample_sha256=sha(manifest_path),
        executable_sha256={name: sha(path) for name, path in
                           [('baseline', args.baseline), ('candidate', args.candidate), ('srcdiff', args.srcdiff)]},
        commands=commands, cases=cases, targets=targets)
    (output / 'replay.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'Replayed {len(cases)} frozen comparisons and {len(targets)} source-reviewed targets: {output}')


if __name__ == '__main__':
    main()
