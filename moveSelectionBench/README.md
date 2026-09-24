# Move-selection characterization benchmark

This suite measures the parent/child, nesting, `diff:common`, ambiguity, and
cross-Type decisions that the redesign is intended to improve. It complements
rather than replaces BigMoveBench and the performance runner:

- this suite asks whether a build chose the intended *explanation* of a move;
- BigMoveBench measures detection and Type-1/2/3 classification over a larger
  clone-derived population;
- `performance/` measures time, memory, and internal work over fixed inputs.

The checked-in expectations are hypotheses that should be reviewed and revised
as the selection model matures. A semantic miss is recorded in `outcomes.json`
and does not make the command fail. Tool crashes, timeouts, malformed output,
and invalid XML are hard failures and do produce a nonzero exit status.

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

Cases with no required moves are useful negative controls. Keep uncertain
examples here as characterization cases. Promote a behavior into the normal
regression suites only after it becomes an accepted product contract.
