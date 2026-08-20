# Repository Analysis Data Model

## Status

This document defines the conceptual target model for the repository-analysis
refactor. It is not a table-by-table description of the current SQLite schema.
The schema and migrations remain authoritative for physical storage details.

## Relationships

```text
Analysis
 ├─ Invocation
 ├─ Commit
 └─ Batch
     └─ Pair
         └─ Move Evidence
```

## Entities and ownership

### Analysis

An analysis is one immutable study definition with accumulated history
coverage. It owns the repository identity and frozen newest anchor, traversal
and retention policies, source scope, tool identities, and relevant schema
versions. Extending coverage does not change that definition.

### Invocation

An invocation records one `run` command, including its absolute target, worker
count, start and end times, wall duration, result, and last durable update.
Every invocation is recorded, including a verified no-op against an already
satisfied target. The operation lock determines whether a writer is currently
active; invocation records describe activity but do not prove liveness.

### Commit

A commit is identified by its complete native Git object ID. Metadata needed
for later analysis or display is frozen when history is planned rather than
queried from mutable repository state later. This includes parent IDs,
timestamp, subject, and merge status when those fields are admitted to the
schema.

### Batch

A batch is bounded, frozen work created at one analysis frontier. It owns a
contiguous sequence of adjacent commit pairs. A pending batch is recoverable;
committing the complete batch advances the analysis frontier atomically.

### Pair

A pair is one stable old/new commit edge and contains every relevant changed
path for that edge. Its `distance_from_newest` identity does not change when
older history is appended. It begins pending and may acquire exactly one
canonical terminal outcome: analyzed, skipped, or failed. The outcome owns its
process observations, timings, errors, and retained artifacts, and identifies
the invocation that published it. Once published, it is immutable within the
analysis and makes the pair covered.

Pair publication is transactional. A crash before publication creates no
durable outcome, leaving the pair pending for a later invocation to process.
There is no attempt record or accepted-outcome selection step in the current
target model.

### Move evidence

Move evidence belongs directly to the pair's canonical outcome. Normalized
evidence is queryable from SQLite; larger retained artifacts follow the
analysis retention policy.

## Deferred retries

Attempt history and in-place retries are intentionally excluded until there is
a concrete requirement for them. Reprocessing unpublished work after a crash
does not require attempt storage. Comparing different tools or configuration
requires a separate analysis because those values are part of the immutable
study definition. If a later requirement demands retries within one analysis,
the attempt and selection semantics must be designed explicitly rather than
inferred from overwritten pair state.

## Query contracts

- `status` reads one consistent database snapshot containing the latest
  invocation, committed coverage, the terminal prefix of any pending batch,
  outcome totals, move totals, and last durable update.
- `list` queries stable pair identities and canonical outcomes with indexed
  ordering, filtering, and bounded pagination.
- `show` loads one pair and its canonical evidence lazily. Stored evidence does
  not require the original repository; optional Git reconstruction reports its
  own availability.
- Query results are immutable presentation values. They do not expose writable
  database, coordinator, or worker objects.

These contracts are implemented independently of the future CLI renderer so
presentation requirements do not become ad hoc SQL or orchestration
dependencies.
