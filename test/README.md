# srcMove Tests

Run the normal test suite from the repository root:

```bash
./build_and_test
```

For an already-built tree, use:

```bash
python3 test/run_all.py
```

## Normal Suite

`test/run_all.py` runs the reliable day-to-day tests:

- `test/e2e_custom`: checked-in srcDiff XML fixtures run directly through
  `srcMove`
- `test/e2e_generated`: checked-in source pairs regenerated with `srcdiff`, then
  run through `srcMove`

The runner finds `srcdiff` on `PATH` or in the sibling workspace at
`../srcDiff/build/bin/srcdiff`.

## Optional Suites

These are intentionally excluded from the normal suite:

- `--include-bigclonebench`: runs the tiny generated BigCloneBench Type-1 suite.
- `--include-stress`: runs large repository stress tests.

CTest is retired for this project. Use `./build_and_test` or
`python3 test/run_all.py` as the test entry point.

## BigCloneBench

BigCloneBench-generated tests should live in a separate suite. Start with
Type-1 clone pairs only; Type-3 and Type-4 moves are not supported.

Run the tiny Type-1 suite directly:

```bash
python3 test/e2e_bigclonebench/run_tests.py
```
