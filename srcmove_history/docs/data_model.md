# srcMove History Data Model

## Status

This document describes the conceptual model implemented by srcMove History.
It is not a table-by-table description of the SQLite schema; the schema in
`srcmove_history/database.py` remains authoritative for physical storage.

## Relationships

```text
Analysis
 ├─ Invocations
 └─ Batches
     └─ Pairs
         └─ Move evidence
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

The pair stores complete old and new Git object IDs. There is no separate
commit table and no frozen commit-subject, timestamp, parent-list, or merge
metadata. The `report` command resolves the limited date and history information
it needs from the configured repository and the analysis's retained Git ref.

Pair publication is transactional. A crash before publication creates no
durable outcome, leaving the pair pending for a later invocation to process.
There is no attempt record or accepted-outcome selection step.

### Move evidence

Move evidence belongs directly to the pair's canonical outcome. Normalized
evidence is queryable from SQLite; larger retained artifacts follow the
analysis retention policy.

Current admission requires results schema 3, including diagnostics schema 5 when
present, through the shared runtime validator. Compact pair schema 5 retains
`summary`, `configuration`, `pipeline_statistics`, `xpath_context`, `output_items`,
and complete `atomic_move_groups` evidence. Endpoint `raw_text` becomes a
SHA-256/UTF-8 byte-size observation; endpoint candidate ID, file, locator,
construct, correspondence, name evidence, location, and selection remain intact.
Diagnostic candidate bodies and traces are excluded from compact storage.
Compact SQLite storage retains no raw source bodies; larger execution artifacts
follow the retention policy. Existing states and snapshots are not rewritten.

SQLite `moves` rows and the established `move_*` query counts still describe
atomic groups. `atomic_metadata` joins explicit group IDs to compact row
ordinals; ordinals are not detector IDs. The query API's `reported_moves` is a
projection of output items with their `item:`/`sequence:` IDs and ordered member
group IDs. Sequences receive no aggregate selection or correspondence evidence.
Pair-detail JSON also exposes the retained schema-3 objects directly. This uses
the existing metrics JSON column without a database migration.

Output items partition the atomic groups. Human status, pair listings, and
research reports prefer output-item counts and relationships; JSON keeps
explicit atomic counts. A sequence combines Type-1 selected-pair members for
reporting and does not change atomic evidence or benchmark scoring.

Read-only access supports older compact schemas 3 and 4 with their previous
results-validator contract 3. Absent evidence remains unknown. Writing,
resuming, and comparison regeneration require compact schema 5 and validator 4;
the fingerprint records these contracts, preventing reuse of old outcomes in
new execution. Create a separate analysis state for current execution. Snapshot
exports preserve their canonical database and original manifest identities.

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
- `show` loads one pair and its canonical evidence lazily. It reads SQLite only
  and does not require the original repository.
- Query results are immutable presentation values. They do not expose writable
  database, coordinator, or worker objects.

These contracts are implemented independently of the CLI renderers so
presentation requirements do not become ad hoc SQL or orchestration
dependencies.
