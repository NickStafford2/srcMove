# srcMove Handoff: BigCloneBench Oracle Next Step

## Situation

Recent work improved the BigCloneBench synthetic generator, but the headline
failure count did not change. That is expected: the remaining failures are now
mostly oracle/granularity issues instead of synthetic wrapper false positives.

Canonical background lives in
[doc/bigclonebench_srcmove_conversion.md](../bigclonebench_srcmove_conversion.md).
Do not duplicate that conversion model here; update that doc for durable
generator behavior.

## Recent Changes

- `scripts/generate_bigclonebench_move_cases.py` now extracts BigCloneBench line
  ranges using LF-delimited lines. This avoids standalone carriage returns in
  IJaDataset comments shifting extracted fragments.
- The generator no longer uses synthetic `beforeAnchor`, `middleAnchor`,
  `targetAnchor`, or `afterAnchor` methods.
- Synthetic files now put the old payload inside a wrapper class and the new
  payload after that class at top-level srcML scope. This avoids comparable
  parent blocks on both sides, which previously let srcDiff align wrappers and
  hide the payload as common code.
- The top-level generated payload is dedented so generated `modified.java` files
  do not contain misleading class-body indentation after the closing wrapper
  class.
- `test/test_bigclonebench_generator.py` covers the LF extraction behavior and
  the synthetic source shape. `test/run_all.py` runs this test as part of the
  normal suite.

## Current Observed State

After the user reran:

```bash
python3 test/e2e_bigclonebench/run_tests.py --clone-type type1 --limit 1000
```

the summary selected 915 distinct cases and reported 39 failures:

```text
36 validation_failure
3  no_move_raw_different
0  anchor_only_false_positive
0  no_move_raw_identical
```

## Recommended Next Step

Read srcMove src code ask the user.

## Verification Commands

Normal suite:

```bash
python3 test/run_all.py
```

Focused BigCloneBench check:

```bash
python3 test/e2e_bigclonebench/run_tests.py --clone-type type1 --limit 424
```

Large review run:

```bash
python3 test/e2e_bigclonebench/run_tests.py --clone-type type1 --limit 1000
```

## Notes For The Next Agent

- Do not use case numbers as durable identifiers across generator changes.
  Dedupe and extraction changes can shift case numbering. Use
  `function_id_one`, `function_id_two`, source file paths, and line ranges.
- Generated cases under `test/e2e_bigclonebench/cases/` are ignored by git.
- The user handles git staging/commits unless explicitly saying otherwise.
