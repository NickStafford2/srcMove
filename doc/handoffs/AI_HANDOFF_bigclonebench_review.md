# srcMove Handoff: BigCloneBench Test Framework Review

## Situation

The user wants a critical review of the BigCloneBench-derived srcMove testing
framework before it grows much larger.

The framework currently converts BigCloneBench clone pairs into synthetic move
tests. This is useful, but it is not a direct historical move benchmark:
BigCloneBench says two Java fragments are clones; the local generator turns that
pair into an `original.java` delete and a `modified.java` insert, then checks
whether srcMove reports the expected move.

## User Intent

The user cares about three things:

- quality code
- quality documentation, neither too large nor too thin
- clear explanations of how the framework works and what needs improvement

They expect future AI sessions to improve the codebase and docs over time, but
without duplicating the same facts in several places. Put durable information in
the topic doc where it belongs, and keep handoffs/backlogs focused on active
review work.

## Current Files

- [scripts/generate_bigclonebench_move_cases.py](/home/nick/Projects/srcMLBuildTemplate/srcMove/scripts/generate_bigclonebench_move_cases.py:1)
- [test/e2e_bigclonebench/run_tests.py](/home/nick/Projects/srcMLBuildTemplate/srcMove/test/e2e_bigclonebench/run_tests.py:1)
- [test/e2e_bigclonebench/README.md](/home/nick/Projects/srcMLBuildTemplate/srcMove/test/e2e_bigclonebench/README.md:1)
- [doc/bigclonebench_srcmove_conversion.md](/home/nick/Projects/srcMLBuildTemplate/srcMove/doc/bigclonebench_srcmove_conversion.md:1)
- [doc/backlog.md](/home/nick/Projects/srcMLBuildTemplate/srcMove/doc/backlog.md:1)

Generated cases and summaries live under:

```text
test/e2e_bigclonebench/cases/
```

That directory is intentionally ignored by git.

## How It Works Today

Run Type-1:

```bash
python3 test/e2e_bigclonebench/run_tests.py --clone-type type1 --limit 10
```

Run Type-2:

```bash
python3 test/e2e_bigclonebench/run_tests.py --clone-type type2 --limit 10
```

The runner:

1. Generates deterministic synthetic cases from the local BigCloneBench H2 DB.
2. Runs `srcdiff original.java modified.java -o diff.xml --position`.
3. Runs `srcMove diff.xml diff_new.xml --results results.json`.
4. Validates expected move count, match kind, and generated source/target line
   range overlap.
5. Writes `test/e2e_bigclonebench/cases/summary.csv`.

Type-1 currently expects one `exact` move. Type-2 currently expects one `type2`
move. Type-3 and Type-4 are not supported as required pass tests.

## Known Design Problem: Dedupe

BigCloneBench stores clone pair rows, not necessarily independent test ideas.
Some Type-1 rows are effectively the same code fragment paired with many other
identical or near-identical fragments. This can inflate the apparent variety of
tested move shapes and make a high pass rate look broader than it is.

Do not treat dedupe as just a mechanical cleanup. It may expose a more basic
test-design question:

```text
What should count as one BigCloneBench-derived srcMove test?
```

Possible answers include:

- one database pair row
- one distinct raw text pair
- one normalized text pair
- one source fragment tested against representative target fragments
- one functionality/clone cluster

The best answer may differ for Type-1 baseline testing, Type-2 research metrics,
and future Type-3/Type-4 exploratory work.

## Review Goals

Perform a critical review before major expansion. Focus on correctness and
measurement quality before convenience.

Key questions:

- Does the oracle prove srcMove found the intended BigCloneBench fragment, not
  some easier anchor or wrapper?
- Are generated synthetic files representative enough to be useful?
- Are results reproducible across runs and machines?
- Does `summary.csv` contain enough metadata to review pass/fail patterns without
  opening every case?
- Are Type-1 and Type-2 metrics reported in a way that avoids overstating
  coverage?
- Should dedupe be implemented as an option, a default, or a separate reporting
  dimension?
- Is the documentation organized so a new AI can find the one canonical source
  for each fact?

## Recommended Next Step

Start small. First inspect a handful of generated Type-1 duplicates and Type-2
failures, then propose the smallest design change that makes the reported metrics
more honest.

Likely useful improvement:

- add explicit dedupe/reporting metadata before changing default behavior

For example, record a stable `dedupe_key` in `metadata.json` and `summary.csv`,
then decide whether the runner should support a flag such as:

```text
--dedupe none|raw-text-pair|normalized-text-pair
```

Do not make dedupe default until the metric definition is clear.

## Git Note

The user handles all git staging, commits, and pushes. Do not stage, commit, or
push unless the user explicitly changes that instruction.
