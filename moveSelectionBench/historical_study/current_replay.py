#!/usr/bin/env python3
"""Replay sealed historical comparisons in fresh states without editing old evidence.

Three one-pair history bootstraps establish production manifests; they are not
part of the scored cohort. Every scored comparison comes from the sealed review.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from moveSelectionBench.historical_study import study
from srcmove_history.configuration import render_history_configuration
from srcmove_history.inputs import observe_executable


def validate_state_name(name: str) -> str:
    if not re.fullmatch(r"\.srcmove-ch7-pass2-[a-z0-9][a-z0-9-]*", name):
        raise ValueError("state name must be a local .srcmove-ch7-pass2- name")
    return name


def sealed_cases() -> dict[str, list[dict]]:
    study.verify_seal()
    selection = study.read(study.HERE / 'selection.json')
    result = {}
    for name in selection['repositories']:
        review = study.read(study.HERE / 'reviews' / (name + '.json'))
        cases = review['ordinary'] + review.get('targets', [])
        ids = [case['id'] for case in cases]
        pairs = [(case['parent'], case['commit']) for case in cases]
        if len(ids) != len(set(ids)) or len(pairs) != len(set(pairs)):
            raise ValueError(f"duplicate sealed case ID or comparison: {name}")
        if any(Path(case_id).name != case_id or case_id in ('.', '..') for case_id in ids):
            raise ValueError("unsafe sealed case ID")
        result[name] = cases
    if sum(map(len, result.values())) != 106:
        raise ValueError("expected the sealed 106-comparison study")
    return result


def fresh_paths(output: Path, state_name: str, repositories: list[str]) -> list[Path]:
    validate_state_name(state_name)
    if output.exists() or output.is_symlink():
        raise ValueError(f"output already exists; preserve it and choose fresh output: {output}")
    states = [ROOT / 'reference-repositories' / name / state_name for name in repositories]
    for state in states:
        if state.exists() or state.is_symlink():
            raise ValueError(f"state already exists; preserve it and choose fresh states: {state}")
    # Guard both old checked-in labels and ignored original artifacts.
    for protected in (study.HERE, ROOT / 'benchmark-results' / 'historical-type12-20260927'):
        if output == protected or protected in output.parents:
            raise ValueError("output cannot be inside historical study evidence")
    return states


def identities(srcmove: Path, srcdiff: Path, protocol: Path) -> dict:
    return {
        'protocol_sha256': study.digest(protocol),
        'srcmove_sha256': observe_executable(srcmove).sha256,
        'srcdiff_sha256': observe_executable(srcdiff).sha256,
    }


def verify_identities(expected: dict, srcmove: Path, srcdiff: Path, protocol: Path) -> None:
    observed = identities(srcmove, srcdiff, protocol)
    for key, value in observed.items():
        if expected.get(key) != value:
            raise ValueError(f"replay input drift: {key}")


def classification_summary(report: dict) -> dict:
    """Keep exact endpoint recovery independent of content classification."""
    counts: Counter[str] = Counter({name: 0 for name in (
        'admitted_targets', 'source_label_not_admitted', 'exact_endpoint_recovered',
        'exact_endpoint_and_content_recovered')})
    events = []
    for case in report['cases']:
        for event in case['events']:
            if not event['count_in_strict_recall']:
                counts['source_label_not_admitted'] += 1
                continue
            counts['admitted_targets'] += 1
            expected = {'type2': 'type2c'}.get(event['expected_type'], event['expected_type'])
            actual = event['selected_types']
            recovered = event['outcome'] == 'detected'
            classified = recovered and expected in actual
            counts['exact_endpoint_recovered'] += int(recovered)
            counts['exact_endpoint_and_content_recovered'] += int(classified)
            events.append({
                'repository': case['repository'], 'case': case['id'], 'target': event['id'],
                'frozen_expected_type': event['expected_type'], 'expected_current_content_relationship': expected,
                'actual_content_relationships': actual, 'exact_endpoint_outcome': event['outcome'],
                'exact_endpoint_recovered': recovered, 'expected_content_recovered': classified,
                'atomic_indices': event['selected_indices'],
            })
    return {
        'schema_version': 1, 'unit': 'admitted frozen source target',
        'scoring': 'unchanged exact revision-filtered one-to-one atomic endpoints',
        'classification_label_mapping': {'type2': 'type2c'},
        'limitation': 'Finite AI-reviewed target inventory; no general historical recall or precision.',
        'counts': dict(sorted(counts.items())), 'events': events,
    }


def execute(args) -> None:
    cases_by_repo = sealed_cases()
    output = args.output.expanduser().absolute()
    protocol = args.protocol.expanduser().resolve(strict=True)
    if not protocol.is_file():
        raise ValueError("protocol must be a saved file")
    fresh_paths(output, args.state_name, list(cases_by_repo))
    srcmove, srcdiff = observe_executable(args.srcmove), observe_executable(args.srcdiff)
    expected = identities(srcmove.resolved_path, srcdiff.resolved_path, protocol)
    if args.protocol_sha256 != expected['protocol_sha256']:
        raise ValueError("protocol hash differs from explicitly frozen hash")
    selection = study.read(study.HERE / 'selection.json')
    patch = study.git(ROOT, 'diff', 'HEAD')
    provenance = {
        'schema_version': 1, **expected,
        'protocol_path': str(protocol), 'state_name': args.state_name,
        'seal_sha256': study.digest(study.HERE / 'seal.json'),
        'runner_sha256': study.digest(__file__), 'legacy_helper_sha256': study.digest(study.__file__),
        'python': sys.version, 'source_revision': study.git(ROOT, 'rev-parse', 'HEAD').decode().strip(),
        'source_patch_sha256': hashlib.sha256(patch).hexdigest(),
        'history_implementation_hashes': {str(p.relative_to(ROOT)): study.digest(p)
                                         for p in sorted((ROOT / 'srcmove_history').glob('*.py'))},
        'configuration': study.study_configuration().analysis.record(),
        'scored_comparison_count': 106, 'bootstrap_execution_count': len(cases_by_repo),
        'bootstrap_note': 'One anchor pair per repository establishes production compare inputs; excluded from scoring.',
        'diagnostics': 'Not collected here; reserve for finite predeclared review sample.',
        'selection': {name: [{'id': c['id'], 'parent': c['parent'], 'commit': c['commit']}
                             for c in cases] for name, cases in cases_by_repo.items()},
    }
    output.mkdir(parents=True, exist_ok=False)
    study.write(output / 'provenance.json', provenance)
    (output / 'protocol.frozen').write_bytes(protocol.read_bytes())
    (output / 'source.patch').write_bytes(patch)
    for name, executable in (('srcmove', srcmove.resolved_path), ('srcdiff', srcdiff.resolved_path)):
        receipt = Path(str(executable) + '.build-receipt.json')
        if receipt.is_file():
            (output / (name + '.build-receipt.json')).write_bytes(receipt.read_bytes())
    provenance_hash = study.digest(output / 'provenance.json')
    for name, cases in cases_by_repo.items():
        verify_identities(expected, srcmove.resolved_path, srcdiff.resolved_path, protocol)
        repo = ROOT / 'reference-repositories' / name
        state = repo / args.state_name
        cli = [sys.executable, ROOT / 'bin' / 'srcmove-history', '-C', repo, '--state-dir', state.name]
        study.command(cli + ['init'], output / name / 'init')
        (state / 'config.toml').write_text(render_history_configuration(study.study_configuration()))
        study.command(cli + ['run', '--pairs', '1', '--jobs', '1', '--format', 'json',
                             '--start', selection['repositories'][name]['anchor'],
                             '--srcmove', srcmove.resolved_path, '--srcdiff', srcdiff.resolved_path],
                      output / name / 'bootstrap')
        frozen = study.verify_history_state(state, repo, selection['repositories'][name], srcdiff, srcmove)
        manifest_path = output / name / 'history-manifest.json'
        study.write(manifest_path, frozen.record())
        for case in cases:
            verify_identities(expected, srcmove.resolved_path, srcdiff.resolved_path, protocol)
            dest = output / name / case['id']
            process = study.command(cli + ['compare', case['parent'], case['commit'], '--save', 'all', '--format', 'json'],
                                    dest / 'compare', accepted=None)
            try:
                document = json.loads(process.stdout) if process.stdout else {}
                comparison = document.get('comparison', {})
            except (ValueError, AttributeError):
                document, comparison = {}, {}
            status = comparison.get('status', 'orchestration_failed')
            if process.returncode != 0 and status in ('completed', 'no_analyzable_change'):
                status = 'orchestration_failed'
            if comparison and (comparison.get('old_commit') != case['parent'] or comparison.get('new_commit') != case['commit']):
                raise ValueError('comparison returned a different commit pair')
            saved = (state / 'comparisons' / f"{case['parent']}-to-{case['commit']}").resolve()
            for filename in comparison.get('saved_paths', []):
                path = Path(filename)
                if path.name not in ('srcdiff.xml', 'srcmove.xml', 'results.json'):
                    continue
                if path.resolve().parent != saved:
                    raise ValueError('comparison artifact outside expected pair directory')
                (dest / path.name).write_bytes(path.read_bytes())
            if status == 'completed' and not all((dest / f).is_file() for f in ('srcdiff.xml', 'srcmove.xml', 'results.json')):
                status = 'artifact_missing'
            execution = {
                'returncode': process.returncode, 'status': status, 'comparison': document,
                'parent': case['parent'], 'commit': case['commit'], 'provenance_sha256': provenance_hash,
                'history_manifest_sha256': study.digest(manifest_path), 'auxiliary': {},
                'artifact_hashes': {p.name: study.digest(p) for p in dest.iterdir() if p.is_file()},
            }
            study.write(dest / 'execution.json', execution)
            study.verify_execution(dest, execution, provenance_hash, case)
            print(name, case['id'], status, flush=True)
    verify_identities(expected, srcmove.resolved_path, srcdiff.resolved_path, protocol)
    score(output)


def score(output: Path) -> None:
    # Old helpers write only beneath this explicit new output path.
    provenance = study.read(output / 'provenance.json')
    if provenance.get('schema_version') != 1 or not provenance.get('protocol_sha256'):
        raise ValueError('not a current replay provenance record')
    if study.digest(output / 'protocol.frozen') != provenance['protocol_sha256']:
        raise ValueError('frozen protocol bytes changed')
    study.score(argparse.Namespace(output=output))
    summary = classification_summary(study.read(output / 'endpoint-report.json'))
    summary['endpoint_report_sha256'] = study.digest(output / 'endpoint-report.json')
    summary['provenance_sha256'] = study.digest(output / 'provenance.json')
    study.write(output / 'current-classification.json', summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    run = sub.add_parser('run')
    for name in ('output', 'srcmove', 'srcdiff', 'protocol'):
        run.add_argument('--' + name, type=Path, required=True)
    run.add_argument('--protocol-sha256', required=True)
    run.add_argument('--state-name', required=True)
    scorer = sub.add_parser('score')
    scorer.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    execute(args) if args.action == 'run' else score(args.output.resolve())


if __name__ == '__main__':
    main()
