#!/usr/bin/env python3
"""Replay eight source-verified, previously exposed whole-Type2 targets.

Use Docker production srcMove. The source oracle was frozen before this replay;
this script checks retained input provenance against Git before invoking srcMove.
Other selected outputs are not automatically adjudicated as correct.
"""
import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from study import ROOT, HERE, digest, git, read, write, source_endpoint
from controls import run_command
from attribution import SRC, _projection, resolve_endpoint
from srcmove_history.results import normalize_compactable_results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--srcmove', type=Path, required=True)
    parser.add_argument('--output', type=Path,
                        default=ROOT/'benchmark-results/historical-type12-retained')
    args = parser.parse_args()
    manifest = HERE/'retained_type2.json'
    oracle = read(manifest)
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Refusing to overwrite retained evidence; use a new output directory.')
    output.mkdir(parents=True, exist_ok=True)
    provenance = dict(schema_version=1, oracle_sha256=digest(manifest),
        runner_sha256=digest(__file__), srcmove_sha256=digest(args.srcmove),
        attribution_sha256=digest(HERE/'attribution.py'),
        source_revision=git(ROOT,'rev-parse','HEAD').decode().strip(),
        cohort='previously_exposed_retained_development')
    # Validate every source and XML input before the first current detector run.
    prepared = []
    for case in oracle['cases']:
        repo = ROOT/'reference-repositories'/case['repository']
        source_xml = ROOT/case['input_srcdiff']
        if digest(source_xml) != case['input_srcdiff_sha256']:
            raise ValueError('Retained XML hash mismatch.')
        tree = ET.parse(source_xml)
        sources = {}
        dest = output/case['id']
        dest.mkdir()
        for file in case['source_files']:
            side = file['side']; revision = case['parent'] if side=='old' else case['commit']
            raw = git(repo,'show',revision+':'+file['path'])
            import hashlib
            assert hashlib.sha256(raw).hexdigest() == file['sha256']
            snapshot = source_xml.parent/('before' if side=='old' else 'after')/file['path']
            assert snapshot.read_bytes() == raw
            units = [u for u in tree.iter('{'+SRC+'}unit') if u.get('filename') and
                u.get('filename').split('|')[0 if side=='old' else -1] == file['path']]
            assert len(units) == 1
            projected,_ = _projection(units[0], 'delete' if side=='old' else 'insert')
            text = raw.decode('utf-8')
            assert projected == text.replace('\r\n','\n').replace('\r','\n')
            sources[(side,file['path'])] = text
            target = dest/side/file['path'];target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(raw)
        for event in case['events']:
            old = source_endpoint(repo,case['parent'],event['old'])
            new = source_endpoint(repo,case['commit'],event['new'])
            assert old == event['old']['text'] and new == event['new']['text']
            mapped = re.sub(r'\b[A-Za-z_]\w*\b',
                lambda m:event['identifier_mapping'].get(m.group(),m.group()),old)
            assert mapped == new
        (dest/'srcdiff.xml').write_bytes(source_xml.read_bytes())
        prepared.append((case,dest,tree,sources))
    write(output/'provenance.json',provenance)
    (output/'frozen-oracle.json').write_bytes(manifest.read_bytes())
    (output/'source.patch').write_bytes(git(ROOT,'diff','HEAD'))
    receipt = Path(str(args.srcmove)+'.build-receipt.json')
    if receipt.exists(): (output/'srcmove.build-receipt.json').write_bytes(receipt.read_bytes())
    report = dict(schema_version=1,provenance=provenance,cases=[],
        limitations=oracle['limitations'])
    for case,dest,tree,sources in prepared:
        row = dict(id=case['id'],parent=case['parent'],commit=case['commit'],commands=[],events=[])
        for variant,extra in [('ordinary',[dest/'srcmove.xml']),
                              ('results-only',['--results-only']),
                              ('diagnostics',['--results-only','--diagnostics'])]:
            assert digest(args.srcmove) == provenance['srcmove_sha256']
            argv = [args.srcmove.resolve(),dest/'srcdiff.xml',*extra,'--results',dest/(variant+'.json')]
            row['commands'].append(dict(variant=variant,**run_command(argv,dest/(variant+'-run'))))
        if any(c['returncode'] != 0 for c in row['commands']):
            row['status']='execution_failure'
        else:
            docs={variant:read(dest/(variant+'.json')) for variant in ('ordinary','results-only','diagnostics')}
            for d in docs.values(): normalize_compactable_results(d)
            row['results_only_equivalent']=docs['ordinary']==docs['results-only']
            row['diagnostics_equivalent']=docs['ordinary']=={k:v for k,v in docs['diagnostics'].items() if k!='diagnostics'}
            row['status']='scored' if row['results_only_equivalent'] and row['diagnostics_equivalent'] else 'equivalence_failure'
            diagnostics=docs['diagnostics'];moves=docs['ordinary']['moves']
            candidates=diagnostics['diagnostics']['candidates']
            for event in case['events']:
                endpoints={side:resolve_endpoint(event[side],sources[(side,event[side]['path'])],
                    tree,diagnostics,'delete' if side=='old' else 'insert') for side in ('old','new')}
                paths={side:{c['xpath'] for c in candidates if c['side']==('delete' if side=='old' else 'insert')
                    and c['candidate_id'] in endpoints[side]['candidate_ids']} for side in ('old','new')}
                indices=[i for i,m in enumerate(moves) if len(m['from_xpaths'])==len(m['to_xpaths'])==1
                    and m['from_xpaths'][0] in paths['old'] and m['to_xpaths'][0] in paths['new']]
                kinds=[moves[i]['match_kind'] for i in indices]
                row['events'].append(dict(id=event['id'],scope='whole_construct',expected_type='type2',
                    exact_selected_indices=indices,selected_types=kinds,
                    outcome='detected' if indices else 'unresolved' if any(e['status']=='unresolved' for e in endpoints.values()) else 'missed',
                    strict_type2_detected=bool(indices) and all(k=='type2' for k in kinds),endpoints=endpoints))
            row['selected_output_count']=len(moves)
            row['unadjudicated_output_indices']=[i for i in range(len(moves))
                if not any(i in e['exact_selected_indices'] for e in row['events'])]
        row['artifact_sha256']={p.name:digest(p) for p in dest.iterdir() if p.is_file()}
        write(dest/'evaluation.json',row);report['cases'].append(row)
        print(case['id'],row['status'],[(e['id'],e['outcome'],e['selected_types']) for e in row['events']],flush=True)
    write(output/'report.json',report)
    print(output/'report.json')


if __name__=='__main__': main()
