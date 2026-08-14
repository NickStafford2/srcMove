# srcMove Tests

`tests/run.py` is the canonical entry point for deterministic correctness tests.
From the repository root:

```bash
./build_and_test                 # build, then run every correctness suite
python3 tests/run.py              # run every suite with the existing build
python3 tests/run.py --list       # list suites and regression cases
```

Run a specific suite or case:

```bash
python3 tests/run.py --suite unit
python3 tests/run.py --suite xml
python3 tests/run.py --suite source
python3 tests/run.py --case 1x1_basic
python3 tests/run.py --case 1x1_basic --case blocks_swapped
```

`--case` finds the owning regression suite automatically. Combine it with
`--suite` if the same case name ever exists in both regression suites.

## Suites

- `unit`: Python tests for test and benchmark infrastructure.
- `xml`: checked-in srcDiff XML fixtures run directly through `srcMove`.
- `source`: checked-in source pairs regenerated with `srcdiff`, then run through
  `srcMove`.

Fixture discovery and layout validation are defined once in
`tests/support/cases.py`. XML cases contain `input.xml`, `expected.xml`, and
`expected.json`. Source cases contain `oracle.json` plus either one
`original.*`/`modified.*` file pair or `original/`/`modified/` directories for
archive comparisons. Malformed case directories are errors rather than being
silently ignored.

Generated artifacts never live beside checked-in fixtures. Both regression
suites write to `build/test-results/<suite>/<case>/`, using `srcdiff.xml`,
`srcmove.xml`, and `results.json` where applicable.

CTest is retired for this project. Use `tests/run.py` for all deterministic
correctness-test selection and execution.

## Tool Selection

All test and benchmark entry points use `tests/support/tooling.py` for executable
discovery and command execution. Explicit CLI paths take precedence, followed
by `SRCMOVE_BIN` or `SRCDIFF_BIN`, workspace build outputs, and finally `PATH`.
Override either tool when needed:

```bash
python3 tests/run.py --srcmove /path/to/srcMove --srcdiff /path/to/srcdiff
SRCMOVE_BIN=/path/to/srcMove python3 tests/run.py --suite xml
```

## Benchmarks

BigCloneBench and repository-scale workloads are experiments, not correctness
test suites. They have separate runners and are never included implicitly by
`tests/run.py`. See the [benchmark index](../benchmarks/README.md).
