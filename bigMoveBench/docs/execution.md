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
4. runs srcMove when that semantic check passes;
5. scores the result with the unchanged BigMoveBench oracle;
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

## Verified Migration

- The old and new workflows matched on all 80 small-profile cases.
- They matched on all 400 medium-profile cases.
- The suite now uses the database-backed runner directly.
- The old snapshot/corpus implementation and migration comparison command were
  removed so there is only one supported workflow.

## Remaining Scalability Work

These are performance improvements to the same workflow, not alternative ways
to define or score the benchmark:

1. Profile representative cases to identify the actual runtime bottleneck.
2. Measure journal and retained-output growth at useful, bounded scales.
3. Test recovery after forced termination during srcDiff and srcMove.
4. Compact retained tool output if it dominates storage.
5. Add bounded parallel workers only after profiling shows that process
   execution is the bottleneck and transactional claiming is proven safe.

The scientific questions and labels do not change when these optimizations are
added.

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
enabled, it appends one compact JSON object per completed case to `PATH` and
flushes each complete line, so completed records remain readable after an
interruption and a resumed run can continue the same file.

The records separate srcDiff and srcMove process windows from Python-only
supervision overhead, structural and semantic validation, scoring, scratch
materialization, attempt persistence, and SQLite commits. They also retain
counts and byte volumes for hard links, validation inputs, logs, JSON writes,
attempt directories, and transactions. The `runner.attempt_started_write_ms`
diagnostic overlaps the corresponding child-process window and therefore must
not be added to the exclusive wall-time phases.

For example, profile the frozen Type-3 small workload from the workspace root:

```bash
./bin/srcml-dev-shell bash -lc 'cd /workspace/srcMove && \
  python3 bigMoveBench/suite.py --profile small --pair-set type3 \
  --profile-runner benchmark-results/profiling/type3-small/raw.jsonl'
```

A bounded 20-case run on 2026-09-23 found that child-process windows accounted
for about 62% of measured per-case wall time. Atomic attempt persistence was
the largest exclusive Python phase; terminal attempt-record writes accounted
for about 84% of that phase. This is operational profiling evidence, not a
scientific benchmark result or a justification for changing recovery semantics.
