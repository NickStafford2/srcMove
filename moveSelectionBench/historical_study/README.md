# Bounded Type-1/Type-2 historical study

**Completed:** [results and limitations](RESULTS.md), machine-readable
[historical counts](results.json), and [supplemental evidence](supplemental_results.json).
Start there before proposing more detector work. Frozen source reviews and
artifact-bound adjudications should be reused, not rediscovered or overwritten.

This is the execution home for the [evidence protocol](../type12_evaluation.md).
The frozen `selection.json` supersedes that proposal's numerical caps: 30
consecutive first-parent comparisons in each of SQLite, Notepad++, and OpenCV,
plus at most 20 source-diff inspections and six selected movement revisions per
repository. All ordinary comparisons remain, including no-source changes,
merges, failures, and previously studied cases. Prior exposure is explicit;
the entire sample must not be described as held out.

Only C/C++ extensions admitted by the production history service are executed.
All changed paths in that scope are included, preserving cross-file detection.
Tests and third-party source are not silently removed. `.in` is unsupported by
the current history path admission and stays an exclusion; the known SQLite
shell example is separate retained evidence, not a newly measured negative.
Selected historical constructs are source-labeled by repository-specific AI
reviewers before tool execution, with a second AI source review. They are not
independent human ground truth. Uncertain identity, edited parents, carried
children, and incomplete source review remain explicit. No promised event quota
is filled by relabeling.

## Durable files and authority

- `selection.json`: immutable windows, anchors, caps, and source scope.
- `reviews/*.json`: source-first inventories, endpoint hashes/ranges, search
  decisions, review limitations and prior-exposure flags.
- `seal.json`: hashes of selection and labels before detector execution.
- `study.py`: validation, production CLI orchestration, exact endpoint scoring.
- Later adjudication/report files: distinguish frozen labels from post-output
  review; never overwrite the frozen recall labels to match output.

Production history SQLite remains the execution authority in each clone's
`.srcmove-type12-20260927/`. Explicit comparisons retain artifacts in that
state directory; study output copies and hashes those artifacts under ignored
`benchmark-results/historical-type12-20260927/`. This is a scoring layer, not
a replacement history service. Execution failures and no-source comparisons
are separate from detection failures. A second run resumes immutable history;
changing binaries, labels, or the runner requires a new run output and, for
changed detector binaries, a separate production analysis state.

## Reproduce

From the parent workspace, after restoring the exact reference Git objects:

```bash
./bin/srcml-dev-shell make --no-print-directory -C srcMove build
./bin/srcml-dev-shell python3 srcMove/moveSelectionBench/historical_study/study.py seal
./bin/srcml-dev-shell python3 srcMove/moveSelectionBench/historical_study/study.py run \
  --srcmove /workspace/srcMove/build/srcMove \
  --srcdiff /workspace/srcDiff/build/bin/srcdiff
./bin/srcml-dev-shell python3 srcMove/moveSelectionBench/historical_study/study.py score
./bin/srcml-dev-shell python3 srcMove/moveSelectionBench/historical_study/explain.py
./bin/srcml-dev-shell python3 srcMove/moveSelectionBench/historical_study/summarize.py
./bin/srcml-dev-shell make --no-print-directory -C srcMove test-move-selection
```

The runner uses two production workers, 180-second srcDiff and 120-second
srcMove limits, UTF-8 and positions, with default detector granularity. It does
not modify repositories' existing `.srcmove` analyses. Endpoint hashes cover
inclusive lines using `bytes.splitlines(keepends=True)`.

Automatic scoring requires both exact revision-filtered XML endpoint texts and
the reviewed logical filenames in a one-to-one result. Whitespace inside source
is preserved; different literals cannot collapse through normalization. Repeated
source text without occurrence resolution is unresolved. A descendant cannot
satisfy a whole target. Formatting or boundary differences that prevent exact
resolution require source review, not an automatic recall-failure claim.

Every unpaired output needs source adjudication before precision is reported.
Whole constructs, independent descendants, repeated groups, partial coverage,
and Type-3 observations stay separate. Ordinary and targeted cohorts also stay
separate; this convenience study does not estimate population accuracy.

`summarize.py` validates every case, output index, confirmed target, source-review
association and artifact hash before publishing counts. The checked-in
adjudications are post-output source judgments, not detector-generated labels.
`explain.py` supplies additional position-based attribution and does not replace
those judgments. Its XPath resolver handles the production predicate subset
without repeatedly indexing the entire XML tree; unsupported paths stay unresolved.

Separate supplemental runs:

```bash
./bin/srcml-dev-shell python3 srcMove/moveSelectionBench/historical_study/controls.py \
  --srcmove /workspace/srcMove/build/srcMove \
  --srcdiff /workspace/srcDiff/build/bin/srcdiff --output /workspace/srcMove/benchmark-results/historical-type12-controls-replay
./bin/srcml-dev-shell python3 srcMove/moveSelectionBench/historical_study/retained_type2.py \
  --srcmove /workspace/srcMove/build/srcMove \
  --output /workspace/srcMove/benchmark-results/historical-type12-retained-replay
```

The retained replay requires the original ignored XML identified in
`retained_type2.json`; it verifies that XML reconstructs the exact Git sources.
It fails rather than silently generating a different input. Fresh source-to-XML
regeneration is a separate experiment. Original raw artifacts live under ignored
`benchmark-results/historical-type12-20260927/`, `historical-type12-controls/`,
and `historical-type12-retained/`. Reference-clone history states are also ignored.

Completed milestones were committed as `20f22b6` (source labels and seal),
`ab5bce3` (execution/scoring), and `04fd56d` (controls and attribution).
The final result commit adds adjudication and evaluation-tool refinements.
The initial full test run and all historical runs used unchanged production code.

## Scope and authorization

The user authorized implementation, agents, staging and incremental commits for
this study on 2026-09-27. This overrides the earlier session's no-commit request
and the default Git instruction in AGENTS.md for this task only. It does not
authorize Phase 5, Type-3 adoption, or a VERSION change. No detector behavior is
changed by this study.
