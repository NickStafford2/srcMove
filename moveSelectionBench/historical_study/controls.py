#!/usr/bin/env python3
"""Execute the frozen source-defined diagnostic controls, preserving failures.

Run in Docker with the production srcDiff/srcMove executable paths. Source labels
live in controls.json; scoring never derives expected moves from detector output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET

from study import ROOT, HERE, digest, git, read, write, xpath_endpoint, source_text


def run_command(argv, prefix, timeout=120):
    started = time.monotonic()
    argv = list(map(str, argv))
    try:
        result = subprocess.run(argv, capture_output=True, timeout=timeout)
        receipt = dict(argv=argv, returncode=result.returncode, timed_out=False)
        stdout, stderr = result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        receipt = dict(argv=argv, returncode=None, timed_out=True)
        stdout, stderr = exc.stdout or b'', exc.stderr or b''
    receipt['elapsed_seconds'] = time.monotonic() - started
    prefix.with_suffix('.stdout').write_bytes(stdout)
    prefix.with_suffix('.stderr').write_bytes(stderr)
    write(prefix.with_suffix('.command.json'), receipt)
    return receipt


def expected_endpoint(value):
    return value['path'], source_text(value['text'])


def score(case, dest):
    tree = ET.parse(dest/'srcdiff.xml')
    doc = read(dest/'results.json')
    outputs = []
    for index, move in enumerate(doc['moves']):
        outputs.append(dict(index=index, type=move['match_kind'],
            old=[xpath_endpoint(tree, x, 'delete') for x in move['from_xpaths']],
            new=[xpath_endpoint(tree, x, 'insert') for x in move['to_xpaths']]))
    scored = dict(expected=[], forbidden=[], outputs=outputs)
    for category in ('expected', 'forbidden'):
        for oracle in case[category]:
            old, new = expected_endpoint(oracle['old']), expected_endpoint(oracle['new'])
            indices = []
            for output in outputs:
                if category == 'expected':
                    matched = output['old'] == [old] and output['new'] == [new]
                else:
                    matched = old in output['old'] and new in output['new']
                if matched:
                    indices.append(output['index'])
            candidates = {}
            for side, expected in [('delete', old), ('insert', new)]:
                candidates[side] = [c['candidate_id'] for c in doc.get('diagnostics', {}).get('candidates', [])
                    if c['side'] == side and xpath_endpoint(tree, c['xpath'], side) == expected]
            scored[category].append(dict(id=oracle['id'], scope=oracle['scope'],
                exact_selected_indices=indices,
                returned_types=[outputs[i]['type'] for i in indices],
                exact_candidates=candidates,
                outcome=('detected' if indices else 'missed') if category == 'expected'
                        else ('forbidden_pair_reported' if indices else 'forbidden_pair_not_reported')))
    scored['unadjudicated_output_indices'] = [o['index'] for o in outputs
        if not any(o['index'] in e['exact_selected_indices']
                   for kind in ('expected', 'forbidden') for e in scored[kind])]
    return scored


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--srcmove', type=Path, required=True)
    parser.add_argument('--srcdiff', type=Path, required=True)
    parser.add_argument('--output', type=Path,
                        default=ROOT/'benchmark-results/historical-type12-controls')
    args = parser.parse_args()
    manifest = HERE/'controls.json'
    oracle = read(manifest)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    provenance = dict(schema_version=1, oracle_sha256=digest(manifest),
        runner_sha256=digest(__file__), srcmove_sha256=digest(args.srcmove),
        srcdiff_sha256=digest(args.srcdiff), source_revision=git(ROOT, 'rev-parse', 'HEAD').decode().strip(),
        argv_source='Source-defined controls; no historical or population accuracy inference.')
    receipt_path = output/'provenance.json'
    if receipt_path.exists() and read(receipt_path) != provenance:
        raise ValueError('Existing run provenance differs; use a new output directory.')
    if not receipt_path.exists():
        write(receipt_path, provenance)
        (output/'frozen-oracle.json').write_bytes(manifest.read_bytes())
        (output/'source.patch').write_bytes(git(ROOT, 'diff', 'HEAD'))
        build_receipt = Path(str(args.srcmove)+'.build-receipt.json')
        if build_receipt.exists():
            (output/'srcmove.build-receipt.json').write_bytes(build_receipt.read_bytes())
    # Freeze every source input before invoking either detector executable.
    for case in oracle['cases']:
        for side in ('before', 'after'):
            for name, text in case[side].items():
                path = output/case['id']/side/name
                data = text.encode('utf-8')
                assert hashlib.sha256(data).hexdigest() == case['source_sha256'][side][name]
                if path.exists() and path.read_bytes() != data:
                    raise ValueError('Existing source input differs from frozen oracle.')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
    report = dict(schema_version=1, provenance=provenance, cases=[],
        limitations=['Controlled development diagnostics, not historical accuracy.',
                    'Strict source-text endpoints only; no descendant coverage credit for whole targets.',
                    'Other outputs remain unadjudicated; passing forbidden pairs is not global precision.',
                    'No Type2 positive controls in this bounded first batch.'])
    for case in oracle['cases']:
        dest = output/case['id']
        result_path = dest/'evaluation.json'
        if result_path.exists():
            report['cases'].append(read(result_path))
            continue
        result = dict(id=case['id'], source_sha256=case['source_sha256'])
        try:
            first = run_command([args.srcdiff.resolve(), '--archive', '--position',
                dest/'before', dest/'after', '-o', dest/'srcdiff.xml'], dest/'srcdiff-run')
            result['srcdiff'] = first
            if first['returncode'] != 0:
                result['status'] = 'srcdiff_failure'
            else:
                second = run_command([args.srcmove.resolve(), dest/'srcdiff.xml', dest/'srcmove.xml',
                    '--results', dest/'results.json', '--diagnostics'], dest/'srcmove-run')
                result['srcmove'] = second
                if second['returncode'] != 0:
                    result['status'] = 'srcmove_failure'
                else:
                    result['status'] = 'scored'
                    result.update(score(case, dest))
        except Exception as exc:
            result['status'] = 'runner_or_scoring_failure'
            result['error'] = str(exc)
        result['artifact_sha256'] = {p.name:digest(p) for p in dest.iterdir()
            if p.is_file() and p.suffix in ('.xml', '.json')}
        write(result_path, result)
        report['cases'].append(result)
        print(case['id'], result['status'], flush=True)
    write(output/'report.json', report)
    print(output/'report.json')


if __name__ == '__main__':
    main()
