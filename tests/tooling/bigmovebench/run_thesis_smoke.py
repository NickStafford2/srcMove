#!/usr/bin/env python3
"""Separate eight-case synthetic fixture smoke; never uses the thesis population."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarking.identity import canonical_json
from benchmarking.provenance import utc_now
from bigMoveBench.thesis_experiment import DEFAULT_CONFIG, execute, prepare
from bigMoveBench.selection_index import build_index
from tests.tooling.bigmovebench.test_selection_index import compile_fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    compiled = compile_fixture(root, repetitions=1)
    cache = root / 'data'
    index = cache / 'selection-index-v1.sqlite'
    build_index(compiled, index)
    config = json.loads(DEFAULT_CONFIG.read_text())
    config['designation'] = 'fixture-smoke'
    for allocation in config['allocations']:
        allocation['count'] = 1
    config['expected_total'] = 8
    prepared = prepare(config, compiled, index, cache, root / 'results',
                       audit_binding={'purpose': 'separate synthetic fixture smoke'}, development_paths=[])
    run, summary = execute(prepared, cache, root / 'results')
    # Exercise actual binary output, journal exports and correction provenance.
    for member in summary['member_summaries']:
        category = member['pair_set']
        detail = json.loads((run / category / 'summary.json').read_text())
        assert detail['development_srcdiff_cache']['enabled'] is False
        assert detail['counts']['selected'] == (4 if category == 'type3' else 1)
        assert detail['label_corrections']['registry']['sha256']
        fields = (run / category / 'cases.csv').read_text().splitlines()[0].split(',')
        assert 'outcome' in fields and 'reviewed_outcome' in fields
    result = {'schema_version': 1, 'purpose': 'fixture smoke; not final thesis evidence', 'completed_at': utc_now(),
        'prepared_experiment': str(prepared), 'run': str(run), 'selected': summary['selected'],
        'status': summary['status'], 'output_contracts': 'actual normalized journal, CSV, summary, supplied/reviewed labels, cache disabled',
        'interpretation': 'Fixture labels are synthetic test data; classification outcomes are not detector-performance evidence.'}
    (root / 'smoke-validation.json').write_bytes(canonical_json(result) + b'\n')
    print(root / 'smoke-validation.json')
    return 0 if summary['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
