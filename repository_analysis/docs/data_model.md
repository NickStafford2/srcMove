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
         ├─ Attempt
         │   └─ Move Evidence
         └─ Accepted Outcome
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
older history is appended. A pair is covered when it has an accepted durable
outcome, including an analyzed, skipped, or failed outcome.

### Attempt and accepted outcome

An attempt is one execution of a frozen pair with the analysis's frozen tools
and configuration. It owns process observations, timings, errors, and retained
artifacts. Attempts are append-only.

A pair points to one accepted outcome used by coverage summaries and queries.
Initially this is its first terminal attempt. A future explicit retry policy may
accept a later attempt made with the same frozen pair definition while retaining
earlier failures as provenance. Retrying with different executable bytes
requires a different analysis.

### Move evidence

Move evidence belongs to the attempt that produced it. Normalized evidence is
queryable from SQLite; larger retained artifacts follow the analysis retention
policy. Summaries use only evidence from each pair's accepted outcome.

## Query contracts

- `status` reads one consistent database snapshot containing the latest
  invocation, committed coverage, the terminal prefix of any pending batch,
  outcome totals, move totals, and last durable update.
- `list` queries stable pair identities and accepted outcomes with indexed
  ordering, filtering, and bounded pagination.
- `show` loads one pair and its accepted evidence lazily. Stored evidence does
  not require the original repository; optional Git reconstruction reports its
  own availability.
- Query results are immutable presentation values. They do not expose writable
  database, coordinator, or worker objects.

These contracts should be implemented before the CLI renderer so presentation
requirements do not become ad hoc SQL or orchestration dependencies.
