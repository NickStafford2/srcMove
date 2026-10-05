# BigMoveBench Execution Architecture

This is the official BigMoveBench workflow. The former expanded
snapshot/corpus workflow was removed after the small and medium profiles
produced identical case IDs and scientific outcomes.

## Purpose

Represent each benchmark case as database rows referencing reusable immutable
Java objects. This keeps the model understandable and avoids permanently
creating four generated files for every clone pair.

```text
compiled BigCloneBench dataset (immutable evidence)
  catalog.sqlite
  fragments/<fragment-sha256>.java

generated object store (immutable wrappers)
  generated-objects/<object-sha256>.java

benchmark cases (immutable test definitions)
  benchmark-cases/<benchmark-cases-id>/manifest.json
  benchmark-cases/<benchmark-cases-id>/benchmark_cases.sqlite

execution result (append-only observations)
  benchmark-results/bigMoveBench/runs/<run-id>/execution.sqlite
  benchmark-results/bigMoveBench/runs/<run-id>/summary.json
  benchmark-results/bigMoveBench/runs/<run-id>/cases.csv
```

The compiled dataset answers “what did BigCloneBench label?” Benchmark cases
answer “what exact synthetic test will we run?” The execution journal answers
“what did this srcMove build do?” Keeping those questions separate is the main
architectural boundary.

## How One Case Runs

For each case, the serial runner:

1. reads four generated-object references from `benchmark_cases.sqlite`;
2. links them into one reusable scratch archive at the stable source and
   destination paths;
3. runs srcDiff and checks that the intended delete and insert are exposed;
4. runs srcMove in results-only mode when that semantic check passes;
5. resolves the reported move XPaths against the admitted srcDiff XML and
   scores the result with the BigMoveBench oracle;
6. commits the attempt and outcome in one SQLite transaction; and
7. clears and reuses the scratch archive.

`summary.json` and `cases.csv` are derived reports. `execution.sqlite` is the
recovery source of truth. On resume, committed cases are skipped and unfinished
attempts are recorded as interrupted rather than silently lost.

## Invariants

1. Compiled BigCloneBench evidence remains immutable and read-only.
2. Benchmark-case identity covers the dataset, selection, wrapper version,
   objects, case inventory, direction policy, and oracle configuration.
3. Generated objects are content-addressed and verified before publication.
4. Each case preserves the exact expected texts and line ranges used by the
   semantic and scoring oracles.
5. Multiple BigCloneBench rows may support one case, but one generated input is
   executed once per declared direction.
6. Retries create new attempts; they do not overwrite evidence.
7. Case collections and results are streamed in bounded batches.
8. Reviewed label corrections are loaded as a fixed registry snapshot for a run.
   Its digest participates in restart compatibility. Original-label outcomes
   remain in the journal and reports alongside reviewed outcomes; a correction
   changes the expected content type without bypassing detection or position
   checks. See the [scoring methodology](methodology.md#conversion-model).

BigMoveBench retains `results.json`, not annotated srcMove XML. The JSON
contains the move identity, classification, text, and source/destination
XPaths needed by the oracle. Resolving those XPaths against the already
admitted srcDiff XML preserves the positional overlap check while avoiding an
output artifact that the benchmark does not otherwise consume.

## Verified Migration

- The old and new workflows matched on all 80 small-profile cases.
- They matched on all 400 medium-profile cases.
- XPath-derived position ranges matched annotated-output ranges on all 400
  medium-profile cases before the runner switched to results-only execution.
- The suite now uses the database-backed runner directly.
- The old snapshot/corpus implementation and migration comparison command were
  removed so there is only one supported workflow.

## Performance status

The current workflow is intentionally serial. Results-only srcMove execution,
streamed database access, reusable scratch archives, and bounded retained logs
removed the known avoidable costs without changing the experiment. No further
BigMoveBench performance project is active. If throughput becomes a constraint
again, use the optional runner profiler below on current binaries before
reopening parallel execution or storage changes.

## Optional Development Cache

The runner can reuse srcDiff XML when invoked with `--cache` (or `CACHE=1` via
Make). This cache is intentionally outside the verified artifact model: its key
contains the generated case and wrapper version but not the srcDiff executable.
Only structurally valid XML is stored or accepted, and entries are compressed
and sharded by case identity. Every resulting report marks the run as using an
unversioned development cache and unsuitable for thesis results. The default
workflow does not read the cache.

## Optional Runner Profiling

The normalized runner and combined suite accept `--profile-runner PATH`. The
option is disabled by default and does not alter selection, execution,
validation, scoring, the execution journal, or derived report schemas. When
enabled, it writes one compact JSON object per newly executed case attempt to
`PATH`; cases skipped during resume do not create duplicate records. Each
record includes the run and attempt identities. The output must not already
exist, and it must be outside the authoritative execution run directory. Use a
new profile path when resuming an interrupted execution run; cases skipped
during that resume produce no records in the new file. When the combined suite
runs all pair sets, it inserts the pair-set name before the supplied filename
suffix and writes one JSONL file per pair set.

The records separate srcDiff and srcMove process windows from Python-only
supervision overhead, structural and semantic validation, scoring, scratch
materialization and cleanup, attempt persistence, and SQLite transactions.
They also retain counts and byte volumes for hard links, validation inputs,
logs, JSON writes, attempt directories, and transactions. The
`runner.attempt_started_write_ms`
diagnostic overlaps the corresponding child-process window and therefore must
not be added to the exclusive wall-time phases.

The profiler is absent from normal execution and report schemas. An invalid
output path fails before the execution journal is opened. If output fails after
execution begins, the runner warns, disables further profiling, and continues
the benchmark. Complete lines before a possible partial final line remain
usable.

For example, profile the frozen Type-3 small workload from the workspace root:

```bash
./bin/srcml-dev-shell bash -lc 'cd /workspace/srcMove && \
  python3 bigMoveBench/suite.py --profile small --pair-set type3 \
  --profile-runner benchmark-results/profiling/type3-small/raw.jsonl'
```

A bounded 20-case run on 2026-09-23 found that child-process windows accounted
for about 62% of measured per-case wall time. Atomic attempt persistence was
the largest exclusive Python phase; terminal attempt-record writes accounted
for about 84% of that phase. The entire persistence phase was only 7.9% of
measured case wall time, so eliminating it completely would cap the observed
single-worker speedup near 1.09x. This is operational profiling evidence, not a
scientific benchmark result or a justification for changing recovery semantics.

## Explicit thesis experiment

[`thesis_experiment.py`](../thesis_experiment.py) prepares the mixed census/sample
plan in [`thesis_experiment.json`](../thesis_experiment.json). This is a separate
entry point from the standard frozen small/medium profiles. It uses the existing
selection companion and canonical contributor hydration, direction, case
publisher, serial runner, and scoring oracles. It does not change frozen files
or detector behavior.

From a Docker shell, prepare and run the thesis experiment with the normal Make
entry points:

```bash
cd /workspace/srcMove
make bigmovebench-thesis-prepare
make bigmovebench-thesis-run
```

Preparation reuses the compiled source dataset. It runs the BigMoveBench unit
tests, focused classification regressions, and separate eight-case fixture
smoke, then records their logs and current Python source/runtime hashes in a
new validation directory. It freezes the current scoring rules and correction
registry in a new experiment. This validation runs fixture detectors only;
it does not evaluate the thesis population. The test-validation record and
the prepared-input checks are retained separately.

When an earlier completed run of the same design exists, preparation compares
the new selection with the first such run and requires identical fragment
pairs, directions, and Type-3 bands. Use
`THESIS_PREVIOUS_EXPERIMENT=<experiment-id-or-directory>` to name a baseline
explicitly. Schema-dependent case IDs may change. Old preparations, selections,
and result directories remain intact.

Successful preparation updates the convenience pointer
`benchmark-results/bigMoveBench/latest-thesis-preparation.json`. A failed refresh
disables that pointer so the run target cannot silently use an earlier
preparation. The run target verifies the preparation and current correction
registry, then starts all 5,598 cases in a new results directory. It never
resumes a legacy run or substitutes a small/medium development profile.
`BENCHMARK_CACHE_ROOT` and `BENCHMARK_RESULTS_ROOT` overrides must be the same
for both targets.

The lower-level commands remain available from the parent workspace root.
After benchmark Python code or runtime changes, pass a fresh
`--validation-record` to `prepare`; the Make preparation target generates one
automatically:

```bash
./bin/srcml-dev-shell python3 srcMove/bigMoveBench/thesis_experiment.py prepare --validation-record <fresh-validation.json>
./bin/srcml-dev-shell python3 srcMove/bigMoveBench/thesis_experiment.py verify <experiment-id>
# This last command runs the complete evaluation; preparation never does:
./bin/srcml-dev-shell python3 srcMove/bigMoveBench/thesis_experiment.py execute <experiment-id>
```

Preparation binds the verified Chapter 6 audit to the recorded dataset/index
identity, asserts the three census counts, and checks every sample quota before
hydration. Each sampled category/band uses the companion's
`python-random-sample-dense-positions-v1` procedure with seed 20261005. The request
records the exact canonical seed bytes, Python runtime/backend hashes, position
order and draw positions. Serialization and execution follow configuration band
order, then ascending frame IDs in each band. Census strata use all dense
positions without consulting the RNG. No replacement, quota redistribution,
substitution, or outcome-based filtering is allowed.

The publication contains five immutable selection manifests and five normalized
case collections, bound by an explicitly designated experiment manifest under
`benchmark-results/bigMoveBench/thesis-preparations/<experiment-id>/`. The
manifest freezes the configuration, correction snapshot, constructor and oracle
versions, Python source hashes, actual pair/case/fragment/functionality coverage,
and development-profile overlap. Selected contributors retain raw labels and
multiplicity, plus reverse-row provenance. Complete content-conflict evidence is
retained; sampling exclusions use the complement of recorded dense positions
instead of expanding millions of excluded frames. The current audited dataset
has no unavailable source rows; the CLI rejects an audit that reports any.

Final preparation also requires a passing validation record for the exact Python
sources/runtime (`--validation-record`, defaulting to the retained 2026-10-05
validation JSON). It copies that record into the immutable publication. The
record distinguishes focused unit/regression tests and the eight-case actual
binary fixture smoke from final experiment evidence. Reproducing preparation
can reuse this record while its source/runtime hashes still match.

Preparation hashes the catalog and companion once. Verification/restart use
canonical dataset identity checks, companion size/mtime, and complete hashes and
inventories for selected artifacts and generated objects; they do not repeatedly
hash the full source catalog. All prepared serial input/metadata contracts are
checked without running detectors. Selection and experiment files are published
through new content-addressed directories, refuse replacement, and are made
read-only. Normalized case collections retain the canonical publisher's
identity and checksum policy.

The execution command verifies the frozen Python source/runtime and input
contracts before running every member with the frozen correction snapshot and
no development srcDiff cache. It records actual executable hashes and build
receipt observations when execution starts. `--resume-run <run-directory>`
requires the same experiment, correction, and executable identities. Changes to
frozen execution sources or runtime fail explicitly; an ordinary Git commit with
unchanged file contents does not change those hashes.

Classification disagreements, misses, false positives, and semantic ineligibility
remain observations and never substitute or silently drop cases. In particular,
Type-2b retains its supplied expectation even though srcMove has no dedicated
blind-only matching stage; classification disagreement does not gate this
experiment. Tool/oracle failures are reported after all members run. Supplied
and reviewed outcomes remain separate in each `summary.json`, `cases.csv`, and
execution journal. Interpret the weak Type-3/Type-4 reference stratum as the
supplied raw syntactic-type-3 rows with conservative BOTH below 0.5; it is not an
independently verified semantic Type-4 dataset.

Retained frozen profiles are compared by exact unordered fragment hashes, with
shared IDs and per-final-category overlap recorded and no overlapping cases
removed. Default scope is the checked-in frozen table plus cache-root
`frozen-profiles*.jsonl`; `--development-profile <path>` can explicitly declare
another retained table. Historical execution outcomes are never consulted.

Focused fixtures and a separate actual-binary smoke can be run before final
preparation:

```bash
./bin/srcml-dev-shell bash -lc 'cd /workspace/srcMove && python3 -m unittest bigMoveBench.tests.test_thesis_experiment bigMoveBench.tests.test_selection_index bigMoveBench.tests.test_benchmark_cases bigMoveBench.tests.test_normalized_execution -v'
./bin/srcml-dev-shell python3 srcMove/bigMoveBench/tests/run_thesis_smoke.py --output-dir srcMove/benchmark-results/bigMoveBench/thesis-fixture-smoke-<new-name>
```

The smoke uses an eight-case synthetic fixture and a `fixture-smoke` designation,
with separate artifacts/results. Its labels and timings are compatibility tests,
not final thesis detector measurements. Shared fragments and functionalities
also mean distinct selected content pairs are not necessarily independent.
Report strata separately and distinguish supplied negatives from positive rates.

## Read-only run browser

The `bigMoveBench.browser` subpackage exposes a schema-version-1 JSON projection
of completed thesis runs for srcDiffVisual. It reads existing aggregate summaries,
execution journals, benchmark-case definitions, and compiled fragment caches;
it never executes tools or modifies benchmark evidence. Original and reviewed
outcomes remain separate. See srcDiffVisual's
[results and review guide](../../../srcDiffVisual/docs/bigmovebench-review.md)
for the UI and HTTP interface.

From the workspace root, query it directly with:

```bash
./bin/srcml-dev-shell bash -lc 'cd /workspace/srcMove && python3 -m bigMoveBench.browser --results-root benchmark-results/bigMoveBench/thesis-runs --cache-root bigMoveBench/cache list-runs'
```

Other commands are `show-run RUN_ID`, `list-cases RUN_ID`, and
`show-case RUN_ID CATEGORY CASE_ID`. `show-source RUN_ID CATEGORY CASE_ID`
returns the checksum-verified retained positioned srcDiff input and scored move
results for annotation reconstruction by the viewer. Missing completed results
or mismatched retained input are explicit errors. Journals are copied to a
temporary snapshot, including retained WAL pages, to avoid writing SQLite
sidecars into saved benchmark directories. Case lists accept `--category`, `--outcome`,
`--basis original|reviewed`, `--query`, `--offset`, and `--limit` (1–100).
The browser code is separate from the construction/execution source files bound
to prepared experiment identities.
