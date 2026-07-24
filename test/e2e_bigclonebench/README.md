# BigCloneBench Type-1 Tests

This suite generates a tiny synthetic move benchmark from BigCloneBench Type-1
clone pairs.

Run one case:

```bash
python3 test/e2e_bigclonebench/run_tests.py
```

Run more cases:

```bash
python3 test/e2e_bigclonebench/run_tests.py --limit 10
```

Generated cases are written to `test/e2e_bigclonebench/cases/` and are ignored by
git.

Only Type-1 clone pairs are used. Type-3 and Type-4 moves are not supported.

