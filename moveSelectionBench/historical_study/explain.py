#!/usr/bin/env python3
"""Resolve reviewed source positions and expose why frozen targets were missed."""
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

from study import HERE, ROOT, read, write, git, digest, verify_seal, verify_execution
from attribution import attribute_event


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'benchmark-results/historical-type12-20260927')
    args=p.parse_args();output=args.output.resolve();verify_seal()
    report=read(output/'endpoint-report.json')
    provenance=digest(output/'provenance.json')
    report['position_attribution']={'module_sha256':digest(HERE/'attribution.py'),
                                   'runner_sha256':digest(__file__)}
    reviews={name:read(HERE/'reviews'/f'{name}.json')
             for name in read(HERE/'selection.json')['repositories']}
    for row in report['cases']:
        if row['status']!='scored': continue
        name=row['repository'];review=reviews[name]
        case=next(c for c in review['ordinary']+review['targets'] if c['id']==row['id'])
        dest=output/name/row['id']
        verify_execution(dest,read(dest/'execution.json'),provenance,case)
        if not row.get('diagnostics_equivalent'):
            row['attribution_error']='diagnostic equivalence unavailable or failed';continue
        tree=ET.parse(dest/'srcdiff.xml');diagnostics=read(dest/'diagnostics.json')
        candidates=diagnostics['diagnostics']['candidates']
        for frozen,event in zip(case.get('events',[]),row['events']):
            if not event['count_in_strict_recall']: continue
            old=git(ROOT/'reference-repositories'/name,'show',case['parent']+':'+frozen['old']['path']).decode('utf-8')
            new=git(ROOT/'reference-repositories'/name,'show',case['commit']+':'+frozen['new']['path']).decode('utf-8')
            evidence=attribute_event(frozen,old,new,tree,diagnostics)
            event['attribution']=evidence
            before={c['xpath'] for c in candidates if c['side']=='delete' and c['candidate_id'] in evidence['old']['candidate_ids']}
            after={c['xpath'] for c in candidates if c['side']=='insert' and c['candidate_id'] in evidence['new']['candidate_ids']}
            matches=[m for m in row['outputs'] if len(m['from_xpaths'])==len(m['to_xpaths'])==1
                     and m['from_xpaths'][0] in before and m['to_xpaths'][0] in after]
            if matches:
                event['outcome']='detected_by_source_position'
                event['selected_indices']=[m['index'] for m in matches]
                event['selected_types']=[m['type'] for m in matches]
                for m in matches:
                    if event['id'] not in m['matching_frozen_events']:m['matching_frozen_events'].append(event['id'])
            elif evidence['limiting_stage']!='unresolved':
                event['outcome']='missed'
    write(output/'explained-report.json',report)
    print(output/'explained-report.json')


if __name__=='__main__': main()
