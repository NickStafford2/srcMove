#!/usr/bin/env python3
"""Generate, prepare, corpus-build, and evaluate BigCloneBench in separate stages."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
TESTS_ROOT = REPO_ROOT / "tests"
for import_root in (REPO_ROOT, TESTS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from benchmarks.bigclonebench.adapter import (
    SEMANTIC_ORACLE_VERSION,
    BigCloneBenchAdapter,
)
from benchmarks.bigclonebench.evaluate import write_evaluation
from benchmarks.bigclonebench.generate import preflight
from benchmarks.contracts import RunMode
from benchmarks.corpus import create_preparation, generate_corpus, run_corpus
from support.tooling import find_srcdiff, find_srcmove


DEFAULT_DATA_ROOT = REPO_ROOT / "benchmark-data"
DEFAULT_CASES_ROOT = SCRIPT_DIR / "cases"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    stages = parser.add_subparsers(dest="stage", required=True)

    stages.add_parser("preflight")

    cases = stages.add_parser("cases", help="Generate synthetic source cases.")
    cases.add_argument("--clone-type", choices=("type1", "type2"), default="type1")
    cases.add_argument("--limit", type=int, default=1)
    cases.add_argument("--candidate-limit", type=int)
    cases.add_argument("--min-tokens", type=int, default=50)
    cases.add_argument(
        "--dedupe",
        choices=("none", "raw-text-pair", "trimmed-text-pair"),
        default="raw-text-pair",
    )
    cases.add_argument(
        "--text-change", choices=("any", "raw-different"), default="any"
    )
    cases.add_argument(
        "--selection-role",
        choices=("tuning", "evaluation"),
        default="tuning",
    )
    cases.add_argument("--out-dir", type=Path, default=DEFAULT_CASES_ROOT)

    prepare = stages.add_parser("prepare", help="Snapshot already-generated cases.")
    prepare.add_argument("--clone-type", choices=("type1", "type2"), default="type1")
    prepare.add_argument("--cases-dir", type=Path, default=DEFAULT_CASES_ROOT)

    corpus = stages.add_parser("corpus", help="Generate immutable srcDiff XML.")
    corpus.add_argument("preparation")
    corpus.add_argument("--srcdiff", type=Path)
    corpus.add_argument("--timeout", type=float, default=60.0)
    corpus.add_argument("--retry-failed", action="store_true")

    evaluate = stages.add_parser("evaluate", help="Run and strictly score srcMove.")
    evaluate.add_argument("corpus")
    evaluate.add_argument("--srcmove", type=Path)
    evaluate.add_argument("--timeout", type=float, default=300.0)
    evaluate.add_argument(
        "--mode",
        choices=[mode.value for mode in RunMode],
        default="development",
    )
    return parser.parse_args()


def _syntactic_type(clone_type: str) -> int:
    return int(clone_type.removeprefix("type"))


def main() -> int:
    args = parse_args()
    data_root = args.data_root.expanduser().resolve()
    exit_code = 0
    try:
        if args.stage == "preflight":
            failures = preflight()
            if failures:
                print(
                    "error: BigCloneBench is an external manual prerequisite; "
                    "nothing was downloaded.",
                    file=sys.stderr,
                )
                for failure in failures:
                    print(f"  - {failure}", file=sys.stderr)
                print(
                    "See benchmarks/bigclonebench/README.md for setup guidance.",
                    file=sys.stderr,
                )
                return 2
            print("BigCloneBench preflight passed")
            return 0

        if args.stage == "cases":
            command = [
                sys.executable,
                str(SCRIPT_DIR / "generate.py"),
                "--syntactic-type",
                str(_syntactic_type(args.clone_type)),
                "--limit",
                str(args.limit),
                "--min-tokens",
                str(args.min_tokens),
                "--dedupe",
                args.dedupe,
                "--text-change",
                args.text_change,
                "--selection-role",
                args.selection_role,
                "--out-dir",
                str(args.out_dir),
                "--overwrite",
            ]
            if args.candidate_limit is not None:
                command.extend(["--candidate-limit", str(args.candidate_limit)])
            return subprocess.run(command, cwd=REPO_ROOT, check=False).returncode

        if args.stage == "prepare":
            adapter = BigCloneBenchAdapter(
                args.cases_dir, _syntactic_type(args.clone_type)
            )
            directory, manifest = create_preparation(
                data_root=data_root,
                adapter=adapter,
                source=adapter.source_manifest(),
            )
            print(f"preparation_id={manifest['preparation_id']}")
        elif args.stage == "corpus":
            srcdiff = find_srcdiff(REPO_ROOT, args.srcdiff)
            if srcdiff is None:
                raise ValueError("srcdiff not found; pass --srcdiff")
            directory, manifest = generate_corpus(
                data_root=data_root,
                preparation=args.preparation,
                srcdiff=srcdiff,
                timeout_seconds=args.timeout,
                use_position=True,
                use_archive=False,
                retry_failed=args.retry_failed,
                semantic_validator=BigCloneBenchAdapter.validate_semantics,
                semantic_oracle={
                    "name": "bigclonebench-payload-exposure",
                    "version": SEMANTIC_ORACLE_VERSION,
                },
            )
            print(f"corpus_id={manifest['corpus_id']}")
            if manifest["counts"]["failed"]:
                print(
                    f"failed_cases={manifest['counts']['failed']}",
                    file=sys.stderr,
                )
                exit_code = 1
        else:
            srcmove = find_srcmove(REPO_ROOT, args.srcmove)
            if srcmove is None:
                raise ValueError("srcMove not found; pass --srcmove")
            run_dir, run_manifest = run_corpus(
                data_root=data_root,
                corpus=args.corpus,
                srcmove=srcmove,
                timeout_seconds=args.timeout,
                mode=RunMode(args.mode),
                require_semantic_eligible=True,
            )
            corpus_path = Path(args.corpus)
            if corpus_path.is_file():
                corpus_dir = corpus_path.resolve().parent
            elif corpus_path.is_dir():
                corpus_dir = corpus_path.resolve()
            else:
                corpus_dir = data_root / "corpora" / str(args.corpus)
            corpus_manifest = json.loads(
                (corpus_dir / "manifest.json").read_text(encoding="utf-8")
            )
            summary = write_evaluation(
                run_dir=run_dir,
                run_manifest=run_manifest,
                corpus_dir=corpus_dir,
                corpus_manifest=corpus_manifest,
            )
            directory = run_dir
            manifest = run_manifest
            print(f"run_id={manifest['run_id']}")
            print(f"summary={run_dir / 'summary.json'}")
            if summary["counts"]["oracle_pass"] != summary["counts"]["selected"]:
                print(
                    "one or more selected cases did not pass the strict oracle",
                    file=sys.stderr,
                )
                print(f"directory={directory}")
                return 1
        print(f"directory={directory}")
        return exit_code
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
