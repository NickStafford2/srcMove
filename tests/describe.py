#!/usr/bin/env python3
"""Export a readable index of exactly the correctness runner's inventory."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.support.catalog import build_catalog, render_html


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('build/readable-suite/catalog.html'))
    parser.add_argument('--json', type=Path, default=Path('build/readable-suite/catalog.json'))
    args = parser.parse_args()
    catalog = build_catalog()
    for path in (args.output, args.json):
        path.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_html(catalog), encoding='utf-8')
    args.json.write_text(json.dumps(catalog, indent=2) + '\n', encoding='utf-8')
    print(f'{len(catalog["entries"])} test entries: {catalog["counts"]}')
    print(args.output.resolve())


if __name__ == '__main__':
    main()
