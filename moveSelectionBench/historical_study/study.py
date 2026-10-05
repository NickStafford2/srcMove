#!/usr/bin/env python3
"""Frozen source-review study layered on the production history analyzer."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from srcmove_history.configuration import HistoryConfiguration, render_history_configuration, load_history_configuration
from srcmove_history.database import AnalysisDatabase, analysis_database_exists
from srcmove_history.results import normalize_compactable_results
from srcmove_history.inputs import AnalysisConfiguration, observe_executable, verify_resume_inputs
from moveSelectionBench.replay_type3_history import revision_text

NS = {'src': 'http://www.srcML.org/srcML/src', 'diff': 'http://www.srcML.org/srcDiff'}
SRC = '{' + NS['src'] + '}'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def source_endpoint(repo, revision, endpoint):
    """Require exact frozen source bytes before using a reviewed endpoint."""
    content = git(repo, 'show', f"{revision}:{endpoint['path']}")
    lines = content.splitlines(keepends=True)
    start, end = endpoint['start_line'], endpoint['end_line']
    if not 1 <= start <= end <= len(lines):
        raise ValueError('invalid source range')
    selected = b''.join(lines[start-1:end])
    if hashlib.sha256(selected).hexdigest() != endpoint['text_sha256']:
        raise ValueError(f"source hash mismatch: {revision}:{endpoint['path']}:{start}-{end}")
    return selected.decode('utf-8')


def endpoint_is_unique(repo, revision, endpoint, text):
    # Equal text at another occurrence must not manufacture target success.
    content = git(repo, 'show', f"{revision}:{endpoint['path']}").decode('utf-8')
    return bool(text.strip()) and content.count(text.strip()) == 1


def source_text(text):
    """XML's mandated end-of-line normalization, without erasing literal spaces."""
    return text.replace('\r\n', '\n').replace('\r', '\n').strip()


def second_verdicts(name):
    review = read(HERE/'reviews'/f'{name}-second.json')
    return {e['event_id']:e.get('verdict',e.get('decision')) for e in review['events']}


def validate_review(repo, review, selection):
    expected = [(p['parent'], p['commit']) for p in selection['ordinary']]
    actual = [(p['parent'], p['commit']) for p in review['ordinary']]
    if actual != expected or not review.get('detector_blind'):
        raise ValueError('review does not match frozen window or is not source-first')
    if len(review.get('targeted_search', [])) > 20 or len(review.get('targets', [])) > 6:
        raise ValueError('targeted review exceeds frozen cap')
    seen = set()
    for case in review['ordinary'] + review.get('targets', []):
        if git(repo, 'rev-parse', case['commit'] + '^1').decode().strip() != case['parent']:
            raise ValueError('case is not an adjacent first-parent comparison')
        for event in case.get('events', []):
            if event['id'] in seen:
                raise ValueError('duplicate event identity')
            seen.add(event['id'])
            for side, revision in [('old', case['parent']), ('new', case['commit'])]:
                source_endpoint(repo, revision, event[side])


def seal(args):
    selection = read(HERE / 'selection.json')
    files = {'selection.json': digest(HERE / 'selection.json')}
    for name, selected in selection['repositories'].items():
        path = HERE / 'reviews' / f'{name}.json'
        validate_review(ROOT / 'reference-repositories' / name, read(path), selected)
        files[f'reviews/{name}.json'] = digest(path)
        second = HERE/'reviews'/f'{name}-second.json'
        second_review = read(second)
        recorded = next(second_review[k] for k in ('primary_review_sha256','primary_manifest_sha256','reviewed_primary_sha256') if k in second_review)
        if recorded != digest(path) or not second_review.get('detector_blind'):
            raise ValueError(f'second source review stale or not blind: {name}')
        verdicts = second_verdicts(name)
        for case in read(path)['ordinary']+read(path).get('targets',[]):
            for event in case.get('events',[]):
                if event['id'] not in verdicts: raise ValueError('missing second review')
        files[f'reviews/{name}-second.json'] = digest(second)
    target = HERE / 'seal.json'
    value = {'schema_version': 1, 'files': files,
             'meaning': 'Source labels sealed before first detector execution; AI review, not human ground truth.'}
    if target.exists() and read(target) != value:
        raise ValueError('seal already exists with different inputs; create a new study')
    write(target, value)
    print('Sealed selection and source reviews.')


def verify_seal():
    for name, expected in read(HERE / 'seal.json')['files'].items():
        if digest(HERE / name) != expected:
            raise ValueError(f'sealed file changed: {name}')


def command(argv, output, *, timeout=None, accepted=(0, 1)):
    """Retain every process failure before deciding whether to stop orchestration."""
    argv = list(map(str, argv))
    started = time.monotonic()
    timed_out = False
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        timed_out = True
        p = subprocess.CompletedProcess(argv, -1, error.stdout or b'', error.stderr or b'')
    except OSError as error:
        p = subprocess.CompletedProcess(argv, -2, b'', str(error).encode())
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix('.stdout').write_bytes(p.stdout)
    output.with_suffix('.stderr').write_bytes(p.stderr)
    write(output.with_suffix('.command.json'), {
        'argv': argv, 'returncode': p.returncode, 'timed_out': timed_out,
        'elapsed_seconds': time.monotonic()-started})
    if accepted is not None and p.returncode not in accepted:
        raise RuntimeError(f'command failed ({p.returncode}): {argv}; see {output}')
    return p


def study_configuration():
    return HistoryConfiguration(analysis=AnalysisConfiguration(
        excluded_suffixes=('.java', '.aj', '.cs', '.py', '.pyi', '.pyw', '.pyz'),
        use_position=True, srcdiff_timeout_seconds=180, srcmove_timeout_seconds=120), jobs=2)


def verify_history_state(state, repo, selected, srcdiff, srcmove):
    """Validate actual production inputs, including paths the CLI reuses on resume."""
    configuration = load_history_configuration(state).analysis
    if configuration != study_configuration().analysis:
        raise ValueError('history configuration differs from study configuration')
    with AnalysisDatabase.open(state, read_only=True) as database:
        frozen = database.initial_manifest()
    if frozen.repository != repo.resolve() or frozen.commits[-1] != selected['anchor']:
        raise ValueError('history repository or anchor differs from frozen study')
    verify_resume_inputs(frozen, repository_identity=frozen.repository_identity,
                         configuration=configuration, srcdiff=srcdiff, srcmove=srcmove)
    # compare uses the database paths, not the command-line paths used above.
    verify_resume_inputs(frozen, repository_identity=frozen.repository_identity,
                         configuration=configuration,
                         srcdiff=observe_executable(frozen.srcdiff.resolved_path),
                         srcmove=observe_executable(frozen.srcmove.resolved_path))
    return frozen


def verify_execution(dest, execution, provenance_sha256, case):
    if execution.get('provenance_sha256') != provenance_sha256:
        raise ValueError('execution is not associated with this run provenance')
    if execution.get('parent') != case['parent'] or execution.get('commit') != case['commit']:
        raise ValueError('execution commit pair differs from frozen case')
    for filename, expected in execution.get('artifact_hashes', {}).items():
        if Path(filename).name != filename or digest(dest/filename) != expected:
            raise ValueError(f'execution artifact mismatch: {filename}')
    if execution.get('status') == 'completed':
        required = {'srcdiff.xml', 'srcmove.xml', 'results.json'}
        if not required.issubset(execution.get('artifact_hashes', {})):
            raise ValueError('completed execution lacks required artifact hashes')


def auxiliary_runs(dest, srcmove, expected_sha256):
    """Observe diagnostics and verify results-only equivalence on the same input."""
    if digest(srcmove) != expected_sha256:
        raise ValueError('srcMove bytes changed before auxiliary execution')
    result = {}
    ordinary = read(dest/'results.json')
    for variant, options in [('results-only', []), ('diagnostics', ['--diagnostics'])]:
        result_path = dest/(variant+'.json')
        p = command([srcmove, dest/'srcdiff.xml', '--results-only', '--results', result_path,
                     *options], dest/(variant+'-run'), timeout=120, accepted=None)
        observation = {'returncode': p.returncode, 'equivalent': None}
        if p.returncode == 0 and result_path.exists():
            try:
                document = read(result_path)
                normalize_compactable_results(document)
                observation['equivalent'] = {k:v for k,v in document.items()
                                              if k != 'diagnostics'} == ordinary
                observation['valid'] = True
            except (ValueError, KeyError, TypeError) as error:
                observation.update(valid=False, error=str(error))
        else:
            observation['valid'] = False
        if digest(srcmove) != expected_sha256:
            raise ValueError('srcMove bytes changed during auxiliary execution')
        result[variant] = observation
    return result


def execute(args):
    verify_seal()
    selection = read(HERE/'selection.json')
    if args.repository and args.repository not in selection['repositories']:
        raise ValueError('unknown study repository')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    srcmove, srcdiff = observe_executable(args.srcmove), observe_executable(args.srcdiff)
    source_patch = git(ROOT, 'diff', 'HEAD')
    implementation_hashes = {str(p.relative_to(ROOT)): digest(p)
                             for p in sorted((ROOT/'srcmove_history').glob('*.py'))}
    implementation_hashes['moveSelectionBench/replay_type3_history.py'] = digest(
        ROOT/'moveSelectionBench/replay_type3_history.py')
    provenance = {'seal_sha256': digest(HERE/'seal.json'),
                  'srcmove_sha256': srcmove.sha256, 'srcdiff_sha256': srcdiff.sha256,
                  'source_revision': git(ROOT, 'rev-parse', 'HEAD').decode().strip(),
                  'source_patch_sha256': hashlib.sha256(source_patch).hexdigest(),
                  'runner_sha256': digest(__file__), 'python': sys.version,
                  'history_implementation_hashes': implementation_hashes,
                  'configuration': study_configuration().analysis.record()}
    prov_path = output/'provenance.json'
    if prov_path.exists():
        prior = read(prov_path)
        # Documentation commits can advance HEAD without changing executable inputs.
        for key in ('seal_sha256', 'srcmove_sha256', 'srcdiff_sha256', 'runner_sha256',
                    'history_implementation_hashes', 'configuration', 'python'):
            if prior.get(key) != provenance[key]:
                raise ValueError(f'run provenance drift: {key}')
    else:
        write(prov_path, provenance)
        receipt = Path(str(args.srcmove)+'.build-receipt.json')
        if receipt.exists(): (output/'srcmove.build-receipt.json').write_bytes(receipt.read_bytes())
        (output/'source.patch').write_bytes(source_patch)
    provenance_sha256 = digest(prov_path)
    for name, selected in selection['repositories'].items():
        if args.repository and name != args.repository: continue
        repo = ROOT/'reference-repositories'/name
        review = read(HERE/'reviews'/f'{name}.json')
        state = repo/('.srcmove-'+selection['study_id'])
        cli = [sys.executable, ROOT/'bin/srcmove-history', '-C', repo, '--state-dir', state.name]
        if not (state/'config.toml').exists():
            command(cli+['init'], output/name/'init')
            (state/'config.toml').write_text(render_history_configuration(study_configuration()))
        if load_history_configuration(state).analysis != study_configuration().analysis:
            raise ValueError('existing history configuration differs from frozen study')
        run = cli+['run', '--pairs', '30', '--jobs', '2', '--format', 'json']
        if analysis_database_exists(state):
            verify_history_state(state, repo, selected, srcdiff, srcmove)
        else:
            run += ['--start', selected['anchor'], '--srcmove', srcmove.resolved_path,
                    '--srcdiff', srcdiff.resolved_path]
        command(run, output/name/'history-run')
        frozen = verify_history_state(state, repo, selected, srcdiff, srcmove)
        state_receipt = output/name/'history-manifest.json'
        write(state_receipt, frozen.record())
        for case in review['ordinary']+review.get('targets', []):
            dest = output/name/case['id']
            if (dest/'execution.json').exists():
                verify_execution(dest, read(dest/'execution.json'), provenance_sha256, case)
                continue
            # An interrupted attempt is preserved rather than mixed with a new one.
            if dest.exists() and any(dest.iterdir()):
                raise ValueError(f'incomplete attempt already exists: {dest}; use a new output directory')
            p = command(cli+['compare', case['parent'], case['commit'], '--save', 'all',
                             '--format', 'json'], dest/'compare', accepted=None)
            try:
                document = json.loads(p.stdout) if p.stdout else {}
                comparison = document.get('comparison', {})
            except (ValueError, AttributeError):
                document, comparison = {}, {}
            status = comparison.get('status', 'orchestration_failed')
            if p.returncode != 0 and status in ('completed', 'no_analyzable_change'):
                status = 'orchestration_failed'
            if comparison and (comparison.get('old_commit') != case['parent'] or
                               comparison.get('new_commit') != case['commit']):
                raise ValueError('comparison returned a different commit pair')
            saved = (state/'comparisons'/f"{case['parent']}-to-{case['commit']}").resolve()
            # Only artifacts explicitly admitted by THIS invocation may be copied.
            for filename in comparison.get('saved_paths', []):
                path = Path(filename)
                if path.name not in ('srcdiff.xml', 'srcmove.xml', 'results.json'):
                    continue
                if path.resolve().parent != saved:
                    raise ValueError('comparison artifact outside expected pair directory')
                (dest/path.name).write_bytes(path.read_bytes())
            auxiliary = {}
            if status == 'completed':
                if not all((dest/f).exists() for f in ('srcdiff.xml', 'srcmove.xml', 'results.json')):
                    status = 'artifact_missing'
                else:
                    auxiliary = auxiliary_runs(dest, srcmove.resolved_path, srcmove.sha256)
            execution = {'returncode': p.returncode, 'status': status, 'comparison': document,
                         'parent': case['parent'], 'commit': case['commit'],
                         'provenance_sha256': provenance_sha256,
                         'history_manifest_sha256': digest(state_receipt),
                         'auxiliary': auxiliary,
                         'artifact_hashes': {f.name:digest(f) for f in dest.iterdir() if f.is_file()}}
            write(dest/'execution.json', execution)
            print(name, case['id'], status, flush=True)


def xpath_endpoint(tree, xpath, side):
    nodes=tree.findall('.'+xpath,NS)
    if len(nodes)!=1: return None
    # Archive XPaths identify the revision filename on their outer unit.
    match=re.search(r"\[@filename=(['\"])(.*?)\1\]",xpath)
    if not match: return None
    paths=match.group(2).split('|')
    path=paths[0 if side=='delete' else -1]
    return path,source_text(revision_text(nodes[0],side))


def match_event(tree, moves, old, new):
    """Whole endpoint identity, never descendant overlap or normalized similarity."""
    found=[]
    for i,m in enumerate(moves):
        if len(m['from_xpaths'])!=1 or len(m['to_xpaths'])!=1: continue
        if (xpath_endpoint(tree,m['from_xpaths'][0],'delete')==old and
            xpath_endpoint(tree,m['to_xpaths'][0],'insert')==new): found.append(i)
    return found


def score(args):
    verify_seal()
    output=args.output.resolve()
    provenance_path=output/'provenance.json'
    provenance=read(provenance_path)
    if provenance.get('seal_sha256') != digest(HERE/'seal.json'):
        raise ValueError('run provenance belongs to another source seal')
    provenance_sha256=digest(provenance_path)
    report={'schema_version':1,'seal_sha256':digest(HERE/'seal.json'),'cases':[],
            'limitation':'Automatic exact-source endpoint scoring. All unmatched outputs require source adjudication; no precision inferred.'}
    for name in read(HERE/'selection.json')['repositories']:
        review=read(HERE/'reviews'/f'{name}.json')
        verdicts=second_verdicts(name)
        repo=ROOT/'reference-repositories'/name
        for cohort in ('ordinary','targets'):
            for c in review.get(cohort,[]):
                dest=output/name/c['id']; execution=dest/'execution.json'
                row={'repository':name,'id':c['id'],'cohort':cohort,'events':[], 'outputs':[]}
                for e in c.get('events',[]):
                    admitted = (verdicts[e['id']] in ('confirm', 'confirmed') and
                                e.get('count_in_strict_recall', True))
                    row['events'].append({'id':e['id'],'expected_type':e['type'],
                         'source_verdict':verdicts[e['id']],
                         'count_in_strict_recall':admitted,
                         'scope':e.get('scope',e.get('granularity')),
                         'selected_indices':[], 'selected_types':[],
                         'outcome':'not_executed' if admitted else 'source_label_not_admitted'})
                if not execution.exists():
                    row['status']='not_executed';report['cases'].append(row);continue
                row['execution']=read(execution)
                try:
                    verify_execution(dest, row['execution'], provenance_sha256, c)
                    manifest=output/name/'history-manifest.json'
                    if digest(manifest) != row['execution'].get('history_manifest_sha256'):
                        raise ValueError('history manifest receipt changed')
                except (ValueError, OSError) as error:
                    row['status']='artifact_integrity_failure';row['error']=str(error)
                else:
                    row['status']=row['execution'].get('status', 'execution_failure')
                if row['status'] != 'completed':
                    for event_row in row['events']:
                        if event_row['count_in_strict_recall']:
                            event_row['outcome']=row['status']
                    report['cases'].append(row);continue
                results=dest/'results.json';xml=dest/'srcdiff.xml'
                moves,_=normalize_compactable_results(read(results))
                tree=ET.parse(xml);row['status']='scored'
                auxiliary=row['execution'].get('auxiliary', {})
                row['results_only_equivalent']=auxiliary.get('results-only', {}).get('equivalent')
                row['diagnostics_equivalent']=auxiliary.get('diagnostics', {}).get('equivalent')
                for e,event_row in zip(c.get('events',[]),row['events']):
                    if not event_row['count_in_strict_recall']: continue
                    old_raw=source_endpoint(repo,c['parent'],e['old'])
                    new_raw=source_endpoint(repo,c['commit'],e['new'])
                    old=(e['old']['path'],source_text(old_raw))
                    new=(e['new']['path'],source_text(new_raw))
                    unique = (endpoint_is_unique(repo,c['parent'],e['old'],old_raw) and
                              endpoint_is_unique(repo,c['commit'],e['new'],new_raw))
                    matches=match_event(tree,moves,old,new) if unique else []
                    event_row.update(selected_indices=matches,
                        selected_types=[moves[i]['content_relationship'] for i in matches],
                        outcome='detected' if matches else 'needs_miss_review' if unique else 'needs_occurrence_resolution')
                for i,m in enumerate(moves):
                    row['outputs'].append({'index':i,'type':m['content_relationship'],
                        'from_xpaths':m['from_xpaths'],'to_xpaths':m['to_xpaths'],
                        'old':[xpath_endpoint(tree,x,'delete') for x in m['from_xpaths']],
                        'new':[xpath_endpoint(tree,x,'insert') for x in m['to_xpaths']],
                        'matching_frozen_events':[e['id'] for e in row['events'] if i in e['selected_indices']],
                        'adjudication':'pending'})
                report['cases'].append(row)
    write(output/'endpoint-report.json',report)
    print('Wrote endpoint-report.json; unresolved outputs are not false positives by default.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='action',required=True)
    sub.add_parser('seal')
    run=sub.add_parser('run');run.add_argument('--srcmove',type=Path,required=True)
    run.add_argument('--srcdiff',type=Path,required=True);run.add_argument('--repository')
    for parser in (run,sub.add_parser('score')):
        parser.add_argument('--output',type=Path,default=ROOT/'benchmark-results/historical-type12-20260927')
    args=p.parse_args()
    {'seal':seal,'run':execute,'score':score}[args.action](args)


if __name__=='__main__': main()
