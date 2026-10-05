#!/usr/bin/env python3
"""Publish compact counts only after every Type-1/2 output has an adjudication."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path

from study import ROOT, HERE, read, write, digest, verify_seal, verify_execution, second_verdicts


def current_content_relationship(kind):
    return kind


def unique_records(records, key, description):
    indexed = {}
    for record in records:
        value = record[key]
        if value in indexed:
            raise ValueError(f'duplicate {description}: {value}')
        indexed[value] = record
    return indexed


def selected_indices(label, moves):
    indices = label.get('selected_indices', [])
    if not isinstance(indices, list) or any(type(i) is not int or not 0 <= i < len(moves) for i in indices):
        raise ValueError('invalid selected output indices')
    if len(set(indices)) != len(indices):
        raise ValueError('duplicate selected output indices')
    return indices


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'benchmark-results/historical-type12-20260927')
    p.add_argument('--publish',type=Path,default=HERE/'results.json')
    args=p.parse_args();output=args.output.resolve();verify_seal()
    provenance=read(output/'provenance.json');provenance_sha=digest(output/'provenance.json')
    if provenance['seal_sha256']!=digest(HERE/'seal.json'):raise ValueError('wrong run seal')
    result={'schema_version':1,'study_id':read(HERE/'selection.json')['study_id'],
            'provenance':provenance,'provenance_sha256':provenance_sha,
            'summarizer_sha256':digest(Path(__file__)),
            'limitations':['AI source review and second AI corroboration, not independent human annotation.',
                'Purposive targeted cases; ordinary windows contain prior-exposed cases and incomplete source reviews.',
                'Recall counts only confirmed frozen targets; no claim of exhaustive historical recall.',
                'Whole constructs and smaller independent moves, and ordinary/targeted cohorts, are separate.',
                'Repeated groups are not expanded into pair precision.'],
            'artifact_index':[],'adjudication_sha256':{},'source_label_counts':Counter()}
    inventory_path = HERE/'source_inventory_audit.json'
    if inventory_path.exists():
        result['source_inventory_audit'] = {'path': inventory_path.name,
                                           'sha256': digest(inventory_path),
                                           'note': 'Separate source-inventory completeness audit; not a recall denominator.'}
    execution=defaultdict(Counter);precision=defaultdict(Counter);recall=defaultdict(Counter)
    stages=Counter();aux=Counter();type3=Counter()
    for name in read(HERE/'selection.json')['repositories']:
        review=read(HERE/'reviews'/f'{name}.json');verdicts=second_verdicts(name)
        ledger_path=HERE/'adjudication'/f'{name}.json'
        ledger=read(ledger_path);result['adjudication_sha256'][name]=digest(ledger_path)
        if ledger.get('repository') != name:
            raise ValueError('adjudication repository mismatch')
        associations = ledger.get('inputs', ledger)
        for key, path in [('source_review_sha256', HERE/'reviews'/f'{name}.json'),
                          ('second_review_sha256', HERE/'reviews'/f'{name}-second.json')]:
            if associations.get(key) != digest(path):
                raise ValueError(f'adjudication source association mismatch: {name} {key}')
        if associations.get('run_provenance_sha256', provenance_sha) != provenance_sha:
            raise ValueError('adjudication provenance mismatch')
        if associations.get('seal_sha256', digest(HERE/'seal.json')) != digest(HERE/'seal.json'):
            raise ValueError('adjudication seal mismatch')
        cases=unique_records(ledger['cases'], 'id', 'adjudication case')
        frozen_cases=unique_records(review['ordinary']+review['targets'], 'id', 'frozen case')
        if set(cases) != set(frozen_cases):
            raise ValueError(f'adjudication case coverage mismatch: {name}')
        for cohort in ('ordinary','targets'):
            for frozen in review[cohort]:
                case_id=frozen['id'];dest=output/name/case_id
                receipt=read(dest/'execution.json');verify_execution(dest,receipt,provenance_sha,frozen)
                if digest(output/name/'history-manifest.json')!=receipt['history_manifest_sha256']:
                    raise ValueError('changed production manifest')
                execution[(name,cohort)][receipt['status']]+=1
                result['artifact_index'].append({'repository':name,'id':case_id,
                    'execution_sha256':digest(dest/'execution.json'),'status':receipt['status'],
                    'results_sha256':receipt['artifact_hashes'].get('results.json')})
                moves=read(dest/'results.json')['moves'] if receipt['status']=='completed' else []
                for mode,obs in receipt.get('auxiliary',{}).items():
                    aux[mode+(':equivalent' if obs.get('equivalent') is True else ':failed_or_different')]+=1
                adjudicated=cases[case_id]
                if adjudicated.get('cohort') != cohort:
                    raise ValueError('adjudication cohort mismatch')
                for key in ('parent', 'commit'):
                    if adjudicated.get(key) != frozen[key]:
                        raise ValueError('adjudication commit pair mismatch')
                hashes=adjudicated.get('artifact_sha256',{})
                required={'execution.json'}
                if receipt['status']=='completed':
                    required.update(('results.json','srcdiff.xml'))
                    if 'diagnostics.json' in receipt['artifact_hashes']:
                        required.add('diagnostics.json')
                if not required.issubset(hashes):
                    raise ValueError('adjudication lacks required artifact hashes')
                for filename,value in hashes.items():
                    if Path(filename).name != filename:
                        raise ValueError('invalid adjudication artifact filename')
                    if digest(dest/filename)!=value:raise ValueError('stale adjudication artifact')
                outputs=unique_records(adjudicated['outputs'], 'index', 'output index')
                if any(type(i) is not int for i in outputs):
                    raise ValueError('output index must be an integer')
                expected={i for i,m in enumerate(moves) if m['content_relationship'] in ('type1','type2c')}
                if set(outputs)!=expected:raise ValueError(f'output adjudication incomplete/duplicated: {case_id}')
                if len(outputs)!=len(adjudicated['outputs']):raise ValueError('duplicate output index')
                for i,m in enumerate(moves):
                    if m['content_relationship']=='type3':type3[(name,cohort)]+=1;continue
                    if m['content_relationship'] not in ('type1','type2c'):
                        raise ValueError('unexpected selected content relationship')
                    label=outputs[i]
                    if current_content_relationship(label['type'])!=current_content_relationship(m['content_relationship']):raise ValueError('output type drift')
                    if label['verdict'] not in ('valid_independent','valid_carried','false_correspondence',
                                                'false_location','unresolved_group','unresolved'):
                        raise ValueError('unknown output verdict')
                    if not label.get('scope') or not label.get('rationale'):
                        raise ValueError('output requires scope and rationale')
                    if not m['from_xpaths'] or not m['to_xpaths']:
                        raise ValueError('selected output lacks endpoints')
                    unit='one_to_one' if len(m['from_xpaths'])==len(m['to_xpaths'])==1 else 'repeated_group'
                    precision[(cohort,m['content_relationship'],unit,label['scope'])][label['verdict']]+=1
                labels=unique_records(adjudicated['events'], 'id', 'event adjudication')
                expected_events={e['id'] for e in frozen.get('events', [])
                                 if verdicts[e['id']] in ('confirm','confirmed') and e.get('count_in_strict_recall',True)}
                if set(labels) != expected_events:
                    raise ValueError(f'confirmed event coverage mismatch: {case_id}')
                used_detections=set()
                for event in frozen.get('events',[]):
                    confirmed=verdicts[event['id']] in ('confirm','confirmed') and event.get('count_in_strict_recall',True)
                    result['source_label_counts']['confirmed' if confirmed else 'unresolved']+=1
                    if not confirmed:continue
                    label=labels[event['id']]
                    outcome=label['outcome'];key=(cohort,event['type'],event['scope'])
                    if outcome not in ('detected','ancestor_covered','descendant_only','missed','unresolved'):
                        raise ValueError('unknown event outcome')
                    if label.get('type',event['type']) != event['type'] or label.get('scope',event['scope']) != event['scope']:
                        raise ValueError('event type or scope drift')
                    indices=selected_indices(label,moves)
                    if outcome!='detected' and indices:
                        raise ValueError('non-detection has exact selected indices')
                    recall[key][outcome]+=1
                    stages[label['limiting_stage']]+=1
                    if outcome=='detected':
                        if not indices:
                            raise ValueError('detected target needs actual selected output indices')
                        if label['limiting_stage']!='selected':
                            raise ValueError('detection limiting stage must be selected')
                        for i in indices:
                            if i not in outputs or outputs[i]['verdict']!='valid_independent' or outputs[i]['scope']!=event['scope']:
                                raise ValueError('exact target detection requires independently valid output of same scope')
                            if len(moves[i]['from_xpaths'])!=1 or len(moves[i]['to_xpaths'])!=1:
                                raise ValueError('group cannot establish exact one-to-one target detection')
                            if i in used_detections:
                                raise ValueError('one exact output counted as multiple source targets')
                            used_detections.add(i)
                        correct=any(current_content_relationship(moves[i]['content_relationship'])==current_content_relationship(event['type']) for i in indices)
                        recall[key]['strict_correct_type']+=int(correct)
    result['source_label_counts']=dict(result['source_label_counts'])
    result['execution']=[dict(repository=k[0],cohort=k[1],counts=dict(v)) for k,v in execution.items()]
    result['recall']=[dict(cohort=k[0],type=k[1],scope=k[2],counts=dict(v),
                          targets=sum(n for label,n in v.items() if label!='strict_correct_type')) for k,v in recall.items()]
    result['output_validity']=[]
    for key,counts in precision.items():
        row=dict(cohort=key[0],type=key[1],unit=key[2],scope=key[3],counts=dict(counts))
        if key[2]=='one_to_one':
            tp=counts['valid_independent']+counts['valid_carried']
            fp=counts['false_correspondence']+counts['false_location']
            u=sum(counts.values())-tp-fp
            row.update(tp=tp,fp=fp,unresolved=u,adjudicated_precision=tp/(tp+fp) if tp+fp else None,
                       precision_bounds=[tp/(tp+fp+u),(tp+u)/(tp+fp+u)] if tp+fp+u else None)
        result['output_validity'].append(row)
    result['limiting_stages']=dict(stages);result['mode_equivalence']=dict(aux)
    result['type3_observations']=[dict(repository=k[0],cohort=k[1],groups=n) for k,n in type3.items()]
    write(args.publish,result);print(args.publish)


if __name__=='__main__':main()
