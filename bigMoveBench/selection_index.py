#!/usr/bin/env python3
"""Build an immutable, versioned selection companion; never modifies a catalog."""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
import tempfile
import time
from collections import defaultdict
from contextlib import closing
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bigMoveBench.catalog import load_compiled_dataset
from bigMoveBench.categories import CATEGORY_RULES_VERSION, benchmark_category
from bigMoveBench.paths import DEFAULT_CACHE_ROOT
from bigMoveBench.progress import ProgressDisplay
from bigMoveBench.selection import (
    TYPE3_STRATA, _catalog_connection, _grouped_rows, _row_groups_for_identifiers,
    _frame, _ROW_QUERY, _row_record, type3_stratum,
)
from benchmarking.identity import canonical_json

INDEX_VERSION = 1
APPLICATION_ID = 0x42434249
ALGORITHM = "python-random-sample-dense-positions-v1"
CATEGORIES = ("type1", "type2b", "type2c", "type3", "known-false-positive")
LOOKUP_SQL = "SELECT frame_id FROM frames WHERE category=? AND band=? AND position=?"


def identity(compiled):
    return {
        "index_version": INDEX_VERSION,
        "category_rules_version": CATEGORY_RULES_VERSION,
        "dataset_id": compiled.dataset_id,
        "manifest_sha256": compiled.manifest_sha256,
        "catalog_sha256": compiled.manifest["artifacts"]["catalog"]["sha256"],
        "eligibility": "available; exclude positive-negative content conflicts",
        "dedupe": "exact-unordered-fragment-pair",
        "position_order": "unordered_pair_id ascending within category/band",
    }


def build_index(compiled, output: Path):
    output = output.expanduser().resolve()
    if output.exists():
        raise ValueError(f"index output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".selection-index-", dir=output.parent)
    os.close(descriptor)
    temporary = Path(name)
    started = time.monotonic()
    phases = {}
    try:
        with closing(_catalog_connection(compiled)) as source, closing(sqlite3.connect(temporary)) as target:
            target.executescript(f"""
                PRAGMA application_id={APPLICATION_ID};
                PRAGMA user_version={INDEX_VERSION};
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
                CREATE TABLE frames (
                    category TEXT, band TEXT, position INTEGER CHECK(position>=0), frame_id TEXT,
                    catalog_rows INTEGER, source_rows INTEGER,
                    PRIMARY KEY(category,band,position), UNIQUE(category,frame_id)
                ) WITHOUT ROWID;
                CREATE TABLE contributors (
                    category TEXT, frame_id TEXT, pair_id INTEGER,
                    PRIMARY KEY(category,frame_id,pair_id)
                ) WITHOUT ROWID;
                CREATE TABLE exclusions (frame_id TEXT PRIMARY KEY, evidence TEXT NOT NULL) WITHOUT ROWID;
                CREATE TABLE counts (
                    category TEXT, band TEXT, frames INTEGER, catalog_rows INTEGER, source_rows INTEGER,
                    PRIMARY KEY(category,band)
                ) WITHOUT ROWID;
            """)
            counts = {(cat, band): [0, 0, 0] for cat in CATEGORIES
                      for band in ([v[0] for v in TYPE3_STRATA] if cat == 'type3' else [''])}
            phase_start = time.monotonic()
            with ProgressDisplay("index/count", detail="counting available catalog rows"):
                total = source.execute("SELECT COUNT(*) FROM pair_rows WHERE source_status='available'").fetchone()[0]
            phases['count_seconds'] = time.monotonic() - phase_start
            phase_start = time.monotonic()
            with ProgressDisplay("index/materialize", total=total, detail="grouping content identities; retaining contributors") as progress:
                rows = source.execute("SELECT * FROM pair_rows INDEXED BY pair_unordered_idx WHERE source_status='available' ORDER BY unordered_pair_id")
                processed = 0
                for frame_id, group in _grouped_rows(rows, 'unordered_pair_id'):
                    kinds = {r['pair_kind'] for r in group}
                    if 'positive' in kinds and 'known_false_positive' in kinds:
                        # Complete evidence uses the same row serializer as the selector.
                        evidence_rows = []
                        for r in group:
                            full = source.execute(_ROW_QUERY + ' WHERE p.pair_id=?', (r['pair_id'],)).fetchone()
                            evidence_rows.append(_row_record(full))
                        target.execute('INSERT INTO exclusions VALUES (?,?)', (frame_id, canonical_json({
                            'unordered_pair_id': frame_id, 'reason': 'positive_negative_content_label_conflict',
                            'rows': sorted(evidence_rows, key=lambda r: (r['pair_kind'], r['source_row_id'])),
                        }).decode()))
                    else:
                        groups = defaultdict(list)
                        for r in group:
                            category = benchmark_category(dict(r)).replace('known_false_positive', 'known-false-positive')
                            groups[category].append(r)
                        for category, contributors in sorted(groups.items()):
                            band = type3_stratum(min(min(r['similarity_line'], r['similarity_token']) for r in contributors)) if category == 'type3' else ''
                            count = counts[category, band]
                            multiplicity = sum(r['source_row_multiplicity'] for r in contributors)
                            target.execute('INSERT INTO frames VALUES (?,?,?,?,?,?)',
                                           (category, band, count[0], frame_id, len(contributors), multiplicity))
                            target.executemany('INSERT INTO contributors VALUES (?,?,?)',
                                               ((category, frame_id, r['pair_id']) for r in contributors))
                            count[0] += 1; count[1] += len(contributors); count[2] += multiplicity
                    processed += len(group)
                    if processed % 1000 < len(group) or processed == total:
                        progress.update(processed, detail="processed available catalog rows")
            phases['materialize_seconds'] = time.monotonic() - phase_start
            phase_start = time.monotonic()
            with ProgressDisplay("index/finalize", detail="persisting counts and indexed tables"):
                target.executemany('INSERT INTO counts VALUES (?,?,?,?,?)',
                                   ((cat, band, *values) for (cat, band), values in counts.items()))
                target.execute('INSERT INTO metadata VALUES (?,?)', ('identity', canonical_json(identity(compiled)).decode()))
                target.commit()
            phases['finalize_seconds'] = time.monotonic() - phase_start
            report = {**phases, 'construction_seconds': time.monotonic() - started,
                      'available_catalog_rows': total, 'eligible_frames': sum(v[0] for v in counts.values()),
                      'excluded_content_frames': target.execute('SELECT COUNT(*) FROM exclusions').fetchone()[0],
                      'catalog_bytes': (compiled.directory / 'catalog.sqlite').stat().st_size}
            target.execute('INSERT INTO metadata VALUES (?,?)', ('construction', canonical_json(report).decode()))
            target.commit()
        with ProgressDisplay("index/publish", detail="exclusive companion publication"):
            with temporary.open('rb') as stream:
                os.fsync(stream.fileno())
            os.link(temporary, output)
        return {**report, 'companion_bytes': output.stat().st_size}
    finally:
        temporary.unlink(missing_ok=True)


def open_index(compiled, path: Path):
    connection = sqlite3.connect(path.expanduser().resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        if (connection.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID or
                connection.execute('PRAGMA user_version').fetchone()[0] != INDEX_VERSION):
            raise ValueError('unsupported selection index version')
        recorded = connection.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
        if recorded is None or json.loads(recorded[0]) != identity(compiled):
            raise ValueError('selection index does not match compiled catalog identity/rules')
        return connection
    except BaseException:
        connection.close()
        raise


def sample_frames(compiled, index_path: Path, *, seed: int, per_category: int = 100, progress: ProgressDisplay | None = None):
    if per_category <= 0 or per_category % 4:
        raise ValueError('profile sample size must be positive and divisible by four')
    frames = {category: [] for category in CATEGORIES}
    with closing(open_index(compiled, index_path)) as index, closing(_catalog_connection(compiled)) as source:
        counts = list(index.execute('SELECT category,band,frames,catalog_rows,source_rows FROM counts ORDER BY category,band'))
        # Refuse shortages before retrieving any frames; no fallback algorithm.
        for cat, band, count, _, _ in counts:
            size = per_category // 4 if cat == 'type3' else per_category
            if count < size:
                raise ValueError(f'insufficient indexed frames for {cat}/{band}: {count} < {size}')
        for cat, band, count, _, _ in counts:
            size = per_category // 4 if cat == 'type3' else per_category
            rng = random.Random(canonical_json({'algorithm': ALGORITHM, 'seed': seed, 'category': cat, 'band': band}))
            identifiers = [index.execute(LOOKUP_SQL, (cat, band, position)).fetchone()[0]
                           for position in rng.sample(range(count), size)]
            by_id = {key: _frame(key, rows, 'exact-unordered-fragment-pair')
                     for key, rows in _row_groups_for_identifiers(source, cat, 'exact-unordered-fragment-pair', identifiers)}
            frames[cat].extend(by_id[key] for key in identifiers)
            if progress is not None:
                progress.update(sum(len(values) for values in frames.values()), detail=f"retrieved {cat}/{band or 'all'}")
        metadata = {'algorithm': ALGORITHM, 'population_counts': [
            {'category': c, 'band': b, 'frames': n, 'catalog_rows': r, 'source_rows': s}
            for c,b,n,r,s in counts], 'index_identity': identity(compiled)}
    return frames, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset')
    parser.add_argument('--cache-root', type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        with ProgressDisplay('index/validate', detail='checking compiled dataset identity'):
            compiled = load_compiled_dataset(args.dataset, data_root=args.cache_root, verification='identity')
        print(json.dumps(build_index(compiled, args.output), sort_keys=True))
        return 0
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f'error: {error}', file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
