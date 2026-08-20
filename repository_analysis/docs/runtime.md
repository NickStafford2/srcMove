# Repository-History Analysis

This document describes verified current behavior. The accepted
[architecture decision](architecture.md) defines the consolidation and
refactoring direction without claiming that unimplemented structure exists.

## Purpose

`repository_analysis` runs srcDiff and srcMove across adjacent first-parent Git
commits. It is production analysis infrastructure; benchmarks may invoke it but
do not own its state format or execution semantics.

The public lifecycle is target-driven:

```bash
python3 -m repository_analysis analyze \
  --analysis-root ANALYSIS \
  --total-pairs 100 \
  --repository REPOSITORY \
  --repository-id NAME \
  --srcdiff PATH \
  --srcmove PATH

python3 -m repository_analysis analyze \
  --analysis-root ANALYSIS \
  --total-pairs 500

python3 -m repository_analysis status --analysis-root ANALYSIS
python3 -m repository_analysis inspect \
  --analysis-root ANALYSIS \
  --distance-from-newest 0
```

`analyze` creates, resumes, or extends the same analysis. There are no public
`start`, `resume`, or `continue-older` state machines.

Exactly one target is required:

- `--total-pairs N` requests an absolute completed-pair count;
- `--through COMMIT` requests a full, immutable commit object ID on the frozen
  first-parent history;
- `--all` continues in bounded batches until the repository root.

Repeating a satisfied target is a verified no-op. A branch moving after the
first invocation does not move the analysis's frozen newest anchor.

## Authoritative state

`ANALYSIS/analysis.sqlite3` is the only authoritative saved state. Python's
standard-library `sqlite3` module supplies transactions and indexing without an
external dependency. JSON or CSV output is a derived view, never a second
authority.

The database stores:

- one immutable analysis definition: repository identity and path,
  configuration, tool digests, schema versions, and retention policy;
- bounded frozen work batches;
- stable pair identities and terminal outcomes;
- compact, queryable move evidence.

`distance_from_newest` is the stable pair order key: zero is the newest pair and
larger values are older. Extending history never renumbers existing rows.

Old JSON chain roots are deliberately rejected. Mixing the old chain format
with SQLite would recreate multiple authorities and ambiguous recovery. Start a
new analysis root instead.

## Concurrency and recovery

Every mutating operation holds one nonblocking `flock` on
`ANALYSIS/.operation.lock` for its entire lifetime, including worker execution.
This intentionally favors simple behavior over optimistic concurrent work: a
second writer fails immediately before loading state or opening workers.

`activity.json` records `is_running`, start/end timestamps, PID, host, command,
and invocation ID for diagnostics. It is not the mutex. If a process crashes,
the kernel releases `flock`; stale activity is reported as interrupted on the
next invocation.

SQLite transactions define the durable boundaries:

1. Freeze a bounded pending batch in one transaction.
2. Publish each terminal pair outcome in its own transaction.
3. After every pair is terminal, commit the batch and advance coverage in one
   transaction.

On retry, a pending batch is resumed exactly. Its terminal prefix is not
recomputed. A request smaller than already-frozen pending coverage is rejected;
an equal or larger request completes the pending batch first. A crash after the
final coverage transaction but before output is safe because the same absolute
target is then a no-op.

Scratch trees are disposable. After acquiring the writer lock, the next
invocation removes stale scratch from an interrupted process. Durable results
are already in SQLite before a worker's scratch is acknowledged for deletion.

## Scale and storage

Internal batches are capped independently of the requested target. `--all`
therefore begins useful work without loading the full history or creating one
unshrinkable million-pair pending batch. Work and completion queues are also
bounded by worker count.

At analysis creation, exact srcDiff and srcMove bytes are copied into an
analysis-owned content-addressed tool store. Workers execute those admitted
copies, so replacement of the original executable cannot change a pending or
later batch.

Successful results retain compact evidence rather than complete XML or raw
moved source bodies:

- scalar and grouped metrics;
- match kind and source/destination XPath arrays for each move;
- SHA-256 and UTF-8 byte length for each moved raw-text region;
- results-file SHA-256 and byte length as an observation.

`inspect` loads one committed pair and its moves on demand. It does not scan or
materialize the full analysis.

Failures retain termination/resource observations and a bounded stdout/stderr
sample with complete-stream byte counts and hashes. Durable log data is capped
at 64 KiB per captured stream even when the runtime capture limit is larger.

## Execution contract

One work item is one adjacent commit pair containing all relevant changed paths,
not one file. This preserves cross-file move detection. Modified files appear
on both sides, additions only on the new side, deletions only on the old side,
and renames use their old/new paths.

Workers own private scratch and reusable Git object readers. Each worker runs at
most one srcDiff or srcMove process at a time. Outcomes may finish out of order,
but the coordinator publishes only a contiguous sequence.

Terminal statuses are:

- `completed`;
- `no_analyzable_change`;
- `export_failed`;
- `srcdiff_failed`;
- `srcmove_failed`;
- `orchestration_failed`.

Tool and validation failures count as covered terminal pairs. The CLI exits one
when committed coverage contains failures, but retrying the same target does not
rerun them. An unexpected coordinator or database error exits two and leaves
pending work recoverable.

## Verification

Run focused tests in the intended Docker environment:

```bash
./bin/srcml-dev-shell bash -lc \
  "cd srcMove && python3 -m unittest discover \
  -s tests/unit -p 'test_repository_analysis_*.py'"
```

The tests cover target convergence, root exhaustion, bounded all-history
planning, exact pending recovery, terminal-failure idempotency, lock contention,
stale scratch cleanup, frozen executable admission, compact storage, and
read-only status/inspection.
