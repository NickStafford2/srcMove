# srcMove Handoff: BigCloneBench Test Framework Review

## Situation

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
python3 test/e2e_bigclonebench/run_tests.py --clone-type type1 --limit 100
```

Run Type-2:

```bash
python3 test/e2e_bigclonebench/run_tests.py --clone-type type2 --limit 100
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

## Current Failure Review

The user ran the generated Type-1 suite after dedupe/reporting improvements. A
request for 1000 cases selected 917 available cases. The run produced 876 passes
and 41 failures.

The 41 failures are not one problem. They split cleanly:

| Class                                   | Count | Cases                                            | Likely meaning                                                                                                                                                |
| --------------------------------------- | ----: | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| No move, raw fragments differ           |     5 | `000012`, `000342`, `000367`, `000379`, `000877` | srcMove does not match BigCloneBench Type-1 cases when raw text differs by comments/formatting, or the generated fragment may not be a clean whole construct. |
| Too many moves inside expected fragment |    34 | e.g. `000308`, `000428`, `000616`, `000621`      | srcMove finds many exact statement/child moves inside the expected function instead of one whole-function move.                                               |
| Anchor-only false positives             |     2 | `000423`, `000425`                               | The synthetic wrapper layout makes anchor methods look moved, and srcMove reports those instead of the intended BigCloneBench function.                       |

Representative cases:

- `bcb_t1_000012`: raw-different Type-1 case. The old side has comments and
  line wrapping; the new side removes comments and compresses formatting.
  srcMove reports one delete-only group and one insert-only group. Likely root
  cause: srcMove canonicalization still includes comments, while BigCloneBench
  Type-1 ignores comment/format differences.
- `bcb_t1_000342`: suspicious generated benchmark case. One extracted fragment
  is a full `search(...)` method; the other starts mid-control-flow with
  `return EMPTY_ITERATOR; } node = edge.getChild(); ...`. BigCloneBench labels
  the row Type-1, but the extracted source range looks partial. This may need
  filtering or special handling.
- `bcb_t1_000308`: raw fragments are identical `PrimeFactors` constructors.
  srcMove reports three exact moves inside the constructor instead of the whole
  constructor. This is probably a granularity mismatch, not a detection miss.
- `bcb_t1_000616` and `bcb_t1_000621`: same granularity issue amplified by
  large constructors. These reported 91 and 212 child moves, respectively.
- `bcb_t1_000423` and `bcb_t1_000425`: the reported moves are synthetic wrapper
  anchors such as `targetAnchor()` and `afterAnchor()`, not the BigCloneBench
  payload. The old/new wrapper layout deletes the payload before anchors and
  inserts it after anchors, so unchanged anchors can appear moved relative to
  the diff.

Do not interpret the current 41 failures as "srcMove failed 41 BigCloneBench
cases." A better reading is:

- 5 are real or possible Type-1 normalization misses or malformed-fragment
  issues.
- 34 are successful lower-granularity detections that the current oracle rejects.
- 2 are synthetic wrapper false positives.

## Recommended Next Step

Evaluate the failure classes above in srcMove itself. For each class, understand
why srcMove makes that choice, then decide whether the right fix belongs in
srcMove, the synthetic BigCloneBench generator, the oracle, or documentation.

Start with representative cases rather than all 41. Good first targets are:

- `bcb_t1_000012` for comment/format-sensitive Type-1 canonicalization.
- `bcb_t1_000342` for malformed or partial BigCloneBench ranges.
- `bcb_t1_000308` for whole-fragment versus child-move granularity.
- `bcb_t1_000423` for wrapper anchor false positives.

Only after that investigation should future work implement fixes. The fixes may
be different per class; do not collapse the 41 failures into one srcMove bug.

## Git Note

The user handles all git staging, commits, and pushes. Do not stage, commit, or
push unless the user explicitly changes that instruction.
