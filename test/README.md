# srcMove Tests

`test/run.py` is the canonical entry point for deterministic correctness tests.
From the repository root:

```bash
./build_and_test                 # build, then run every correctness suite
python3 test/run.py              # run every suite with the existing build
python3 test/run.py --list       # list suites and regression cases
```

Run a specific suite or case:

```bash
python3 test/run.py --suite unit
python3 test/run.py --suite xml
python3 test/run.py --suite source
python3 test/run.py --case 1x1_basic
python3 test/run.py --case 1x1_basic --case blocks_swapped
```

`--case` finds the owning regression suite automatically. Combine it with
`--suite` if the same case name ever exists in both regression suites.

## Suites

- `unit`: Python tests for test and benchmark infrastructure.
- `xml`: checked-in srcDiff XML fixtures run directly through `srcMove`.
- `source`: checked-in source pairs regenerated with `srcdiff`, then run through
  `srcMove`.

CTest is retired for this project. `test/run_all.py` remains only as a temporary
compatibility wrapper around `test/run.py`.

## Tool Selection

All test and benchmark entry points use `test/tooling.py` for executable
discovery and command execution. Explicit CLI paths take precedence, followed
by `SRCMOVE_BIN` or `SRCDIFF_BIN`, workspace build outputs, and finally `PATH`.
Override either tool when needed:

```bash
python3 test/run.py --srcmove /path/to/srcMove --srcdiff /path/to/srcdiff
SRCMOVE_BIN=/path/to/srcMove python3 test/run.py --suite xml
```

## Benchmarks

BigCloneBench and repository-scale workloads are experiments, not correctness
test suites. They have separate runners and are never included implicitly by
`test/run.py`.

## BigCloneBench

BigCloneBench-generated tests live in `test/e2e_bigclonebench/`. The generated
case directories are ignored by git, and the active manifest decides which cases
belong to the current run.

The suite is no longer just a tiny sample. A large batch can generate and run
over a thousand Type-1 and Type-2 synthetic move cases. In this checkout, the
current manifests list 915 Type-1 cases and 640 Type-2 cases, both selected from
`--limit 1000` runs with `--dedupe raw-text-pair`.

Type-1 is the default; Type-2 is available by option. Type-3 and Type-4 moves
are not supported.

Run the default one-case Type-1 smoke test directly:

```bash
python3 test/e2e_bigclonebench/run_tests.py
```

Run a larger Type-1 batch:

```bash
python3 test/e2e_bigclonebench/run_tests.py --clone-type type1 --limit 1000
```

Run a larger Type-2 batch. This is a strict test mode and may fail until srcMove
supports the selected BigCloneBench Type-2 pairs:

```bash
python3 test/e2e_bigclonebench/run_tests.py --clone-type type2 --limit 1000
```

See [e2e_bigclonebench/README.md](e2e_bigclonebench/README.md) for dedupe modes,
summary output, and validation rules.
