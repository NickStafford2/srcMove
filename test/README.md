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

All test and benchmark entry points use `test/tooling.py` for executable
discovery and command execution. Explicit CLI paths take precedence, followed
by `SRCMOVE_BIN` or `SRCDIFF_BIN`, workspace build outputs, and finally `PATH`.
This keeps direct suite runs consistent with `test/run_all.py`.

## Optional Suites

These are intentionally excluded from the normal suite:

- `--include-bigclonebench`: runs a one-case generated BigCloneBench Type-1
  smoke test.
- `--include-stress`: runs large repository stress tests.

CTest is retired for this project. Use `./build_and_test` or
`python3 test/run_all.py` as the test entry point.

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
