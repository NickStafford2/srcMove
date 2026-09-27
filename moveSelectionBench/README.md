# Move-selection semantic benchmark

This suite measures the parent/child, nesting, `diff:common`, ambiguity, and
cross-Type decisions that the redesign is intended to improve. It complements
rather than replaces BigMoveBench and the performance runner:

- this suite asks whether a build chose the intended *explanation* of a move;
- BigMoveBench measures detection and Type-1/2/3 classification over a larger
  clone-derived population;
- `performance/` measures time, memory, and internal work over fixed inputs.

Every catalog case declares a `status`: an accepted `contract` or an
exploratory `hypothesis`. Normal benchmark runs record every semantic miss as
an observation so variants can be compared. The deterministic test suite runs
contracts with `--contracts-only --enforce-contracts`, making a contract miss a
test failure. Tool crashes, timeouts, malformed output, and invalid XML are
always hard failures.

The current catalog contains accepted contracts; the `hypothesis` status is
available for future questions that have not yet earned regression status.
This benchmark's status is independent of BigMoveBench's observational Type-3
population recall.

The separate `shadow_contracts.json` catalog is the reviewer-owned oracle for
the correspondence-classifier milestone. It does not describe current
production output and is not evaluated against the current `moves` array.
Instead, each entry records four independent parts:

- the required srcDiff delete/insert precondition and Type-1 cardinality;
- the structural context observations the future extractor must produce;
- the expected observation-only classification; and
- its stable machine-readable reason.

The move-selection unit suite validates the catalog schema and verifies the
declared srcDiff endpoint counts. Most inputs are small checked-in srcDiff XML
fixtures. The `nodiscard_signature_and_unwrap` case is regenerated from its
checked-in source pair so an upstream srcDiff alignment change cannot let the
contract pass without exposing the exact return as both deleted and inserted.
Raw path incompatibility without a reliable wrapper interpretation remains
`ambiguous`; paths alone never establish relocation or restructuring.

Run the current build:

```bash
python3 moveSelectionBench/benchmark.py \
  --variant current=build/srcMove \
  --run-id current-characterization
```

Compare a redesign with a baseline:

```bash
python3 moveSelectionBench/benchmark.py \
  --variant baseline=/path/to/baseline/srcMove \
  --variant candidate=/path/to/candidate/srcMove \
  --baseline baseline \
  --run-id parent-aware-selection
```

The append-only run directory contains a provenance manifest, sealed attempt
records and logs, per-case semantic outcomes, profiler metrics, a summary, and
baseline-to-candidate transition counts. Do not report only a pass total: review
the individual rationale and forbidden interpretations for changed cases.

## Adding cases

Add one isolated srcDiff XML input under `cases/` and one catalog entry. A
required expectation says that a move pair should exist. A forbidden
expectation says that an interpretation should not be selected. Raw text is
compared after whitespace normalization; match kinds remain explicit.

Archive fixtures declare `"input_shape": "archive"`; single-file fixtures may
omit the field. Set `"verify_results_only_equivalence": true` when a case must
also confirm that normal and `--results-only` executions select identical move
endpoints and match kinds.

Cases with no required moves are useful negative controls. Keep uncertain
examples as `hypothesis` cases. Change the status to `contract` only after the
expected behavior has been reviewed and accepted; contracts run under
`make test`.

Shadow-classifier contracts belong in `shadow_contracts.json` rather than the
production move catalog until observation-only diagnostics exist. Add a
single-purpose input under `shadow_cases/`, declare the exact srcDiff
precondition, fill every context dimension, and select a classification reason
from the stable vocabulary enforced by `shadow_contracts.py`. A source-level
alignment regression should use an `original`/`modified` pair and be generated
by the test instead of checking in a large real-world srcDiff artifact.
