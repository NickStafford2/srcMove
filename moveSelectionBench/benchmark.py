#!/usr/bin/env python3
"""Compare builds using exactly the accepted correctness behavior suite."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from benchmarking.provenance import observe_file, utc_now
from benchmarking.storage import write_json_atomic
from benchmarking.tooling import find_srcmove
from performance.benchmark import parse_named_path, validate_name


def summarize(reports, baseline):
    """Compare per-method/fixture outcomes; these are not population accuracy."""
    if baseline not in reports:
        raise ValueError(f'baseline variant is not defined: {baseline}')
    inventory = reports[baseline]['inventory']
    if any(report['inventory'] != inventory for report in reports.values()):
        raise ValueError('variant inventories differ; comparison is invalid')
    indexed = {}
    for variant, report in reports.items():
        statuses = {item['id']: item['status'] for item in report['outcomes']}
        if len(statuses) != len(report['outcomes']):
            raise ValueError(f'duplicate outcomes for {variant}')
        indexed[variant] = {case: statuses.get(case, 'not_executed') for case in inventory}
    counts = {variant: dict(Counter(statuses.values())) for variant, statuses in indexed.items()}
    # unittest records class/module teardown errors outside method IDs. Keep
    # those errors as well as the unexecuted IDs from setup failures.
    for variant, report in reports.items():
        extra = Counter(item['status'] for item in report['outcomes'] if item['id'] not in inventory)
        for status, count in extra.items():
            counts[variant][status] = counts[variant].get(status, 0) + count
    transitions = {
        variant: dict(sorted(Counter(indexed[baseline][case] + '_to_' + indexed[variant][case] for case in inventory).items()))
        for variant in reports if variant != baseline
    }
    return {'baseline': baseline, 'tests': len(inventory), 'variants': counts,
            'transitions_from_baseline': transitions,
            'hard_failures': sum(count.get('error', 0) + count.get('skip', 0) + count.get('not_executed', 0) for count in counts.values()),
            'semantic_failures': sum(count.get('failure', 0) for count in counts.values()),
            'interpretation': 'Accepted assertions are shared with correctness. Method totals include subtests and are not unique scenarios or population accuracy.'}


def run_benchmark(*, variants, output_root, baseline, run_id, test_patterns=(), srcdiff=None, timeout_seconds=600):
    validate_name(run_id, 'run id')
    if baseline not in variants:
        raise ValueError(f'baseline variant is not defined: {baseline}')
    for name, executable in variants.items():
        validate_name(name, 'variant')
        if not executable.is_file():
            raise ValueError(f'variant executable not found: {name}={executable}')
    run_dir = output_root.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = {'started_at': utc_now(), 'baseline': baseline,
                'variants': {name: observe_file(path) for name, path in variants.items()},
                'selectors': list(test_patterns), 'suite': 'behavior', 'status': 'running'}
    write_json_atomic(run_dir / 'manifest.json', manifest)
    reports = {}
    for name, executable in variants.items():
        variant_dir = run_dir / name
        variant_dir.mkdir()
        report_path = variant_dir / 'report.json'
        command = [sys.executable, str(REPO_ROOT / 'tests/run.py'), '--suite', 'behavior',
                   '--srcmove', str(executable.resolve()), '--report', str(report_path),
                   '--artifacts', str(variant_dir / 'artifacts')]
        if srcdiff is not None:
            command += ['--srcdiff', str(srcdiff.resolve())]
        for pattern in test_patterns:
            command += ['--test', pattern]
        write_json_atomic(variant_dir / 'command.json', command)
        try:
            completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, timeout=timeout_seconds)
            (variant_dir / 'stdout.log').write_bytes(completed.stdout)
            (variant_dir / 'stderr.log').write_bytes(completed.stderr)
        except subprocess.TimeoutExpired as error:
            (variant_dir / 'stdout.log').write_bytes(error.stdout or b'')
            (variant_dir / 'stderr.log').write_bytes(error.stderr or b'')
            manifest.update(status='invalid_run', error=f'{name}: comparison timed out')
            write_json_atomic(run_dir / 'manifest.json', manifest)
            raise RuntimeError(f'{name}: comparison timed out; artifacts: {variant_dir}') from error
        if completed.returncode not in (0, 1) or not report_path.is_file():
            manifest.update(status='invalid_run', error=f'{name}: runner did not complete (exit {completed.returncode})')
            write_json_atomic(run_dir / 'manifest.json', manifest)
            raise RuntimeError(f'{name}: runner did not complete; artifacts: {variant_dir}')
        reports[name] = json.loads(report_path.read_text())
    summary = summarize(reports, baseline)
    write_json_atomic(run_dir / 'summary.json', summary)
    manifest.update(completed_at=utc_now(), status='completed_with_errors' if summary['hard_failures'] else 'completed')
    write_json_atomic(run_dir / 'manifest.json', manifest)
    return run_dir, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant', action='append', default=[], metavar='NAME=PATH')
    parser.add_argument('--baseline')
    parser.add_argument('--test', action='append', default=[], metavar='ID_OR_GLOB')
    parser.add_argument('--srcdiff', type=Path)
    parser.add_argument('--output-root', type=Path, default=REPO_ROOT / 'benchmark-results/move-selection')
    parser.add_argument('--run-id')
    parser.add_argument('--timeout', type=float, default=600)
    args = parser.parse_args()
    try:
        pairs = [parse_named_path(value, 'variant') for value in args.variant]
        if not pairs:
            binary = find_srcmove(REPO_ROOT)
            if binary is None:
                raise ValueError('srcMove executable not found; pass --variant NAME=PATH')
            pairs = [('current', binary)]
        variants = dict(pairs)
        if len(variants) != len(pairs):
            raise ValueError('variant names must be unique')
        run_dir, summary = run_benchmark(variants=variants, output_root=args.output_root,
            baseline=args.baseline or pairs[0][0], run_id=args.run_id or utc_now().replace(':', '-').replace('+', '_'),
            test_patterns=args.test, srcdiff=args.srcdiff, timeout_seconds=args.timeout)
    except (OSError, ValueError, RuntimeError) as error:
        print(f'error: {error}', file=sys.stderr)
        return 2
    print(f'Comparison: {run_dir}')
    for name, counts in summary['variants'].items():
        print(f'{name}: {counts}')
    return int(bool(summary['hard_failures']))


if __name__ == '__main__':
    raise SystemExit(main())
