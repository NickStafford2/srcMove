# BigCloneBench Tests

This suite generates a tiny synthetic move benchmark from BigCloneBench clone
pairs.

Run one Type-1 case:

```bash
python3 test/e2e_bigclonebench/run_tests.py
```

Run more Type-1 cases:

```bash
python3 test/e2e_bigclonebench/run_tests.py --limit 10
```

Run Type-2 cases:

```bash
python3 test/e2e_bigclonebench/run_tests.py --clone-type type2 --limit 10
```

The BigCloneBench-native spelling also works:

```bash
python3 test/e2e_bigclonebench/run_tests.py --syntactic-type 2 --limit 10
```

Generated cases are written to `test/e2e_bigclonebench/cases/` and are ignored by
git.

Each run also writes `test/e2e_bigclonebench/cases/summary.csv`. This is the
quick index for reviewing a batch without opening every generated case. It
records the case id, pass/fail status, clone type, BigCloneBench function ids,
source files, reported move counts, reported match-kind counts, and failure
messages.

## Validation

- Type-1 expects one `exact` move.
- Type-2 expects one `type2` move.
- The reported delete and insert move positions must overlap the synthetic line
  ranges for the BigCloneBench fragments stored in `metadata.json`.

The runner invokes `srcdiff` with `--position` so `diff_new.xml` contains
`pos:start` / `pos:end` attributes. This makes the oracle independent of raw
string formatting differences introduced by the synthetic wrapper.

Type-2 is a strict test mode. If current srcMove does not detect a generated
BigCloneBench Type-2 pair, the command exits nonzero and reports the missed move.

Type-3 and Type-4 moves are not supported.
