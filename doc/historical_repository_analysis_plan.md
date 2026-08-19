# Repository-History Analysis Plan

## Status and purpose

This document is the implementation plan for a production repository-analysis
tool in srcMove. It is not a benchmark design and it does not describe the
current implementation.

The tool will run srcDiff and srcMove across adjacent Git commit pairs and
publish deterministic, resumable results. A separate benchmark will invoke the
production tool to measure throughput, memory use, and worker scaling.

The central rule is:

> Workers compute commit-pair outcomes; the coordinator publishes them.

The existing experimental runner under `benchmarks/repositories/` establishes
the current schemas, filtering behavior, failure evidence, and result semantics.
It should be migrated rather than copied into a second permanent implementation.

## Product boundary

Repository analysis belongs in a new production Python package outside
`benchmarks/`, provisionally:

```text
srcMove/
  repository_analysis/
    __init__.py
    cli.py
    contracts.py
    coordinator.py
    worker.py
    git.py
    process.py
    retention.py
    reporting.py

  benchmarks/repositories/
    benchmark_history_scaling.py
```

The exact module split may remain smaller while the implementation is young.
Create a module only when it owns a clear responsibility.

Python is the intended implementation language. Git, srcDiff, and srcMove do
the expensive work in external processes, so Python's GIL does not constrain
pair-level concurrency. Explicit `threading.Thread` and bounded `queue.Queue`
primitives provide sufficient control over long-lived workers, backpressure,
shutdown, and subprocess limits. Do not add Python worker processes merely to
coordinate programs that are already separate processes.

The initial public entry point may be:

```bash
python3 -m repository_analysis ...
```

Add an installed command such as `srcmove-history` after the interface is
stable. Do not force repository orchestration into the existing C++ XML CLI.
The C++ executable remains responsible for move detection; Python owns Git,
subprocess supervision, retention, resume, and reporting.

## History and pair definition

The initial traversal remains a bounded first-parent history. `--start S` is
the newest endpoint. For requested pair count `N`, select at most `N+1` commits,
reverse the ancestry order, and compare adjacent commits:

```text
C0 -> C1
C1 -> C2
...
C(N-1) -> CN
```

Ordering is ancestry order, not timestamp order. Record each commit hash, all
parent hashes, committer time, subject, and merge status. Reject shallow
repositories rather than treating a shallow boundary as a root commit. Freeze
the resolved commit list and retain its newest commit with a namespaced Git ref
so a moving remote reference cannot redefine an existing analysis.

One commit pair is one independent work item. Its srcDiff input is the sparse
old/new directory pair containing all relevant content-changing paths:

- modified files appear on both sides;
- additions appear only on the new side;
- deletions appear only on the old side;
- renames are represented by their old and new paths;
- unchanged files are omitted;
- configured directory and suffix filters remain explicit;
- symbolic links, submodules, unsafe paths, and unsupported modes produce
  explicit pair outcomes.

The work unit is never an individual file pair. A single srcDiff archive must
see all changed paths in the commit pair so cross-file moves remain detectable.

## Execution architecture

### Coordinator

The coordinator owns global mutable state. It:

- prepares or validates the repository once;
- freezes the ordered commit list and configuration;
- observes the srcDiff and srcMove executables once;
- creates a fixed number of long-lived workers;
- feeds a bounded queue of commit-pair work items;
- receives immutable outcomes in completion order;
- publishes pair receipts in commit order;
- derives history summaries and browse views;
- applies retention and acknowledges worker cleanup;
- stops scheduling safely on an integrity or orchestration failure.

The coordinator does not run srcDiff or srcMove and does not mutate a worker's
temporary files while that worker owns them.

### Workers

Each worker owns its temporary directory and process state for its lifetime. It
repeatedly claims the next available commit pair and performs:

```text
inventory
  -> materialize old/new Git blobs
  -> srcDiff
  -> validate srcDiff XML
  -> srcMove
  -> validate srcMove XML and results
  -> seal immutable PairOutcome
```

When one srcDiff invocation is unusually slow, other workers continue claiming
and completing later pairs. A fixed `--jobs N` pool means at most `N` expensive
tool processes are active: each worker runs at most one srcDiff or srcMove
process at a time.

A worker should keep one private `git cat-file --batch` process and reuse it
across its claimed pairs. Blob bytes are hashed while being written; do not
materialize an intermediate export tree or reopen newly written inputs merely
to calculate the same checksum.

### Bounded scheduling and deterministic publication

Do not submit the complete history as an unbounded list of futures. Use bounded
work and completion queues. Completed outcomes may arrive out of order, but the
coordinator publishes only the next contiguous sequence.

Out-of-order outcomes must not accumulate large result payloads in memory. A
worker seals its outcome and retained artifacts on disk and returns a small
immutable reference. The coordinator keeps only bounded metadata needed to
publish available outcomes. Workers may claim more work while an earlier slow
pair is still running.

The implementation must bound independently of history length:

- active workers;
- active Git/srcDiff/srcMove processes;
- queued work items;
- in-memory outcomes;
- captured stdout and stderr;
- retained temporary data after coordinator acknowledgement.

## Core contracts

Use frozen dataclasses or equivalent immutable values for boundaries between
workers and the coordinator.

### PairWorkItem

Contains only frozen input:

- sequence number;
- old and new commit hashes;
- repository and selected directory;
- filtering configuration;
- tool configuration and timeouts;
- pair fingerprint.

### VerifiedArtifact

Represents an artifact that was just created and admitted:

- owned path;
- size and SHA-256;
- artifact kind and schema or XML shape;
- validation status and details;
- producing command/stage;
- retention disposition.

Passing a `VerifiedArtifact` to the next stage is the explicit proof that the
artifact need not be reopened, rehashed, or reparsed by orchestration code. A
consumer such as srcMove will still read its actual input as part of doing its
work.

### ProcessOutcome

Preserves the useful behavior of the current generic attempt executor:

- command and working directory;
- start and completion times;
- exit, signal, timeout, spawn, and interruption status;
- process-group cleanup evidence;
- bounded stdout and stderr observations;
- peak RSS and OOM evidence where supported;
- admitted output artifact or validation failure.

### PairOutcome

The worker's immutable terminal result contains:

- pair identity and changed-path inventory;
- terminal pair status;
- normalized srcMove metrics and results when successful;
- srcDiff and srcMove process outcomes;
- retained artifact references and checksums;
- stage timings;
- a pair fingerprint tying the result to commits, tools, configuration, and
  contract versions.

The coordinator publishes this outcome without reconstructing a generic
snapshot, corpus, run, or repository-benchmark record.

## Correctness and failure semantics

Preserve these terminal pair states unless a schema migration deliberately
replaces them:

- `completed`;
- `no_analyzable_change`;
- `export_failed` or a more precise materialization failure;
- `srcdiff_failed`;
- `srcmove_failed`;
- `orchestration_failed`.

A successful zero-move result is different from a skipped, failed, or pending
pair. Never substitute zero for missing measurements.

Expected tool failures are immutable pair outcomes and do not stop unrelated
pairs. The production command may exit nonzero to alert the caller that the
analysis completed with pair failures, but the scaling benchmark must not treat
those deterministic failures as a benchmark infrastructure failure. Benchmark
failure means the production tool crashed, published incomplete or corrupt
state, changed configuration, or produced nonequivalent outcomes.

Unexpected coordinator failure stops new claims, allows controlled child
cleanup, and leaves sealed outcomes and published receipts recoverable.

## Artifact retention

Retention should be applied directly when sealing or publishing a pair, not by
promoting artifacts through several temporary ownership hierarchies.

The initial implementation must preserve current observable result contracts
while making failure evidence durable. A reasonable default retains:

- every pair receipt;
- `results.json` for every successful analyzed pair;
- compact normalized metrics for reporting;
- full command, termination, stdout, stderr, and partial-output evidence for
  failed pairs;
- srcDiff/srcMove XML for positive pairs only when selected by policy.

Temporary source trees and successful zero-move XML may be removed after the
coordinator acknowledges a sealed outcome. Positive XML, complete intermediates,
or ephemeral results remain explicit policy choices. Cleanup must never follow
symbolic links or delete outside the analysis-owned root.

## Resume and cache safety

Pair fingerprints cover at least:

- repository identity;
- resolved old and new commits;
- selected directory and changed-path filtering rules;
- srcDiff and srcMove executable SHA-256 values;
- archive, position, encoding, and timeout configuration;
- relevant result, validator, and receipt schema versions.

Resume loads the frozen history, verifies the global configuration, and skips
only sealed terminal outcomes whose fingerprints and required retained
artifacts still verify. It must not resolve the original branch again or rerun
a completed pair because its worker number changed.

Cache reuse is optional and separate from normal transient worker storage. A
cache entry is reusable only after an immutable complete outcome is published
under its pair fingerprint and its required artifacts verify. Do not introduce
flags such as `skip_verification=True`; represent verification explicitly with
typed values and sealed outcomes.

Interrupted unsealed worker directories are diagnostic evidence, not cache
entries. Resume may reconcile them using stable invocation identifiers, but it
must not silently admit partial output or duplicate a completed tool execution.

## What to reuse from the experimental implementation

Retain or extract, with tests:

- first-parent selection and commit metadata;
- changed-path inventory and filtering;
- path and Git-mode safety checks;
- direct Git blob materialization behavior;
- process-group timeout and cleanup semantics;
- bounded log capture and resource observation;
- structural srcDiff/srcMove XML admission;
- normalized srcMove result fields;
- atomic JSON publication;
- deterministic summary and browse-view behavior;
- existing pair and history fields required by consumers.

Do not make the production pair executor create these generic benchmark layers
for every fresh pair:

- content-addressed input-snapshot directories;
- generation batches;
- promoted srcDiff corpora;
- generic srcMove run manifests;
- per-pair environment and executable observations;
- recovery scans for unrelated attempts;
- repeated retention rewrites and artifact copies;
- a generic repository-benchmark summary before the history receipt.

The shared benchmark pipeline may continue serving datasets that genuinely need
those abstractions. Repository analysis should use a focused path rather than
adding bypass flags to the generic path.

## Implementation phases

### Phase 1: package and contracts

- Create the production package and initial module entry point.
- Define `PairWorkItem`, `VerifiedArtifact`, `ProcessOutcome`, and `PairOutcome`.
- Move or wrap pure commit-selection and changed-path logic without changing
  behavior.
- Freeze a versioned history configuration and pair fingerprint.

### Phase 2: coordinator with fake workers

- Implement fixed long-lived threads and bounded queues.
- Prove dynamic claiming when one early pair is slow.
- Collect outcomes in completion order and publish in sequence order.
- Prove bounded in-flight work and clean cancellation.
- Use fake workers before introducing Git or real tool processes.

### Phase 3: focused pair execution

- Add worker-owned Git batch materialization.
- Extract the necessary process supervision into the production package.
- Run srcDiff and srcMove sequentially inside one worker.
- Pass verified artifacts directly between stages.
- Seal successful and failed outcomes with the required evidence.

### Phase 4: retention, reporting, and resume

- Preserve normalized results and chronological summaries.
- Apply retention without generic corpus/run promotion.
- Add interruption checkpoints and sealed-outcome verification.
- Resume without duplicate execution.
- Add optional cache publication only after non-cache execution is stable.

### Phase 5: public interface and migration

- Stabilize the command-line interface and installable wrapper.
- Redirect repository-history documentation to the production command.
- Change the scaling driver to invoke that command.
- Compare normalized outcomes with the experimental runner.
- Remove the old history-to-generic-benchmark adapter only after equivalence is
  demonstrated.

## Verification strategy

Unit tests should use temporary Git repositories and fixture executables. They
must not require network access or real srcDiff/srcMove binaries.

Required coverage includes:

- exact first-parent selection and ancestry ordering;
- root-bounded and shallow histories;
- directory, suffix, mode, rename, addition, and deletion filtering;
- one repository preparation per invocation;
- worker-private temporary and process state;
- dynamic claiming around a deliberately slow first pair;
- completion-order collection with deterministic publication;
- bounded queue, outcome, worker, and subprocess counts;
- srcDiff and srcMove success, failure, timeout, signal, malformed XML, and
  missing-result behavior;
- bounded and checksum-recorded stdout/stderr;
- positive, zero-move, skipped, and failed retention;
- interruption before sealing, after sealing, and before publication;
- resume without duplicate srcDiff or srcMove execution;
- rejection of configuration, executable, or artifact drift;
- identical normalized outcomes at different worker counts;
- cleanup constrained to the analysis-owned directory.

After unit tests pass, run a 5-10 pair Docker pilot and inspect one success, one
zero-move result, and one failure if available. Expand to a representative
30-pair scaling check before running the fixed 300-pair validation.

## Benchmark boundary and success criteria

`benchmark_history_scaling.py` should benchmark the production command as a
black-box consumer. It owns trial scheduling, environment observation, resource
measurement, normalized equivalence comparison, and report promotion. The
production tool must not contain worker-count study logic.

The current fixed SQLite baseline at eight workers is approximately:

- 300 selected pairs;
- 149 `no_analyzable_change`, 135 completed, and 16 srcDiff failures;
- 50.44 seconds wall time;
- 1,212 MiB peak RSS;
- normalized result SHA-256
  `a75ab5cff7f92a80a241a5ced100ff1491824fa38d8c60569bcac6ac39b5ac5c`.

Before removing the experimental path, require:

- identical commit selection, pair statuses, normalized results, move counts,
  and required retained evidence;
- deterministic output across worker counts and completion orders;
- three measured repetitions per worker count with medians and MAD;
- at least 20% lower eight-worker median wall time than the baseline;
- at least 50% less summed non-tool pair time;
- peak RSS no higher than the baseline, preferably below 1 GiB at eight
  workers;
- no more than `jobs` expensive tool processes concurrently;
- memory and in-memory pending outcomes bounded independently of history
  length;
- interruption and resume without duplicate completed work.

The 4/6/8/12-worker curve should be rerun after the focused path is correct. A
multi-stage pipeline is not planned: current measurements show contention at
higher worker counts, not idle srcDiff capacity. Consider staging only if new
measurements demonstrate that whole-pair workers leave expensive srcDiff
capacity materially idle.

## Known uncertainties

- The public command name and eventual relationship to the C++ CLI remain to be
  finalized after the Python interface is usable.
- The exact default positive-XML retention policy needs confirmation against
  downstream inspection workflows.
- A focused prototype must separate necessary XML admission and monitoring cost
  from removable generic artifact-lifecycle overhead.
- Persistent Git batch sessions are expected to reduce process churn, but their
  benefit should be measured rather than assumed.
- The current SQLite scaling knee is evidence for the tested Docker allocation,
  not a universal default worker count.
