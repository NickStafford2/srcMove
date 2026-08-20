# Repository Analysis Architecture Decision

- Status: accepted
- Date: 2026-08-20

## Context

srcMove has two remaining generations of repository-history analysis: the
production `repository_analysis` package and an experimental benchmark history
runner. An older receipt-based package architecture was removed during the
initial consolidation. The remaining implementations still overlap in
execution and presentation, leaving more than one apparent way to run the same
analysis.

## Decision

`repository_analysis` is the sole product boundary for historical repository
analysis. Its SQLite database is the sole authoritative state. Benchmark tools
may configure or measure it, but must not own a competing execution pipeline or
state format.

The target runtime is:

```text
CLI or benchmark adapter
        |
        v
analysis coordinator
  freeze analysis definition
  select commit pairs
  create bounded work queue
        |
        v
+---------------- worker pool ----------------+
|                                             |
| Worker 1: pair A -> Git -> srcDiff -> srcMove
| Worker 2: pair B -> Git -> srcDiff -> srcMove
| Worker 3: pair C -> Git -> srcDiff -> srcMove
|                                             |
+---------------------------------------------+
        |
        | normalized pair outcomes
        v
single transactional SQLite writer
        |
        +----> status / list / show / export queries
```

`run` is the only CLI command that changes analysis coverage. It creates a new
analysis when none exists, resumes interrupted work, or extends completed
coverage until the requested absolute target is reached. If that target is
already satisfied, it validates the existing analysis and performs no pair
execution. Users do not need to choose separate start, resume, or continue
commands.

Program responsibilities will be separated as follows:

- The CLI parses arguments and renders results; it does not orchestrate work.
- The application service owns create, resume, extension, and batch planning.
- The execution pipeline owns one frozen adjacent-commit pair and returns a
  normalized outcome without publishing shared state.
- The persistence layer owns schema migrations, transactions, and integrity.
- Query and export services do not schedule pair execution or modify analysis
  coverage. They read SQLite and may resolve retained analysis artifacts or
  frozen Git context needed for inspection.
- Benchmark tools select repositories, revisions, and measurement settings,
  then invoke the same supported analysis interface used by the CLI. They do
  not implement a separate history-analysis pipeline or persistence format.

The durable model will distinguish an immutable analysis, a command invocation,
a frozen commit pair, its one canonical terminal outcome, and normalized move
evidence. Each terminal outcome identifies the invocation that produced it. A
crash before transactional publication leaves no durable outcome, so a later
invocation may process the still-pending pair. Once published, the outcome is
immutable within that analysis. Comparing different executable bytes or
configuration requires a separate analysis. Traversal and retention are frozen
analysis policies; first-parent traversal and compact evidence remain the
initial defaults.

The conceptual entities and read contracts are defined in the
[data model](data_model.md). Physical tables and migration code remain the
authority for storage details.

## Migration rules

Refactoring will preserve these established contracts:

- one SQLite authority and one nonblocking writer lock;
- frozen newest commit, configuration, and executable bytes;
- bounded batches, queues, and worker scratch;
- one work item per commit pair containing every relevant changed path;
- transactional pair publication and recoverable pending work;
- exactly one immutable terminal outcome per covered pair, linked to its
  producing invocation;
- stable pair ordering when older history is appended.

Features unique to the experimental runner, such as readable move browsing and
scaling studies, will be rebuilt as queries, exports, or benchmark adapters over
the production analyzer. Once equivalent behavior exists, the experimental
runner will become a small adapter or be removed rather than maintained as a
compatibility architecture. Superseded receipt-based package APIs have already
been removed.

Attempt history and in-place retry policy are deliberately deferred. They will
be added only if a concrete requirement cannot be met by rerunning unpublished
work or creating a separate analysis.

## Consequences

There will be one supported way to execute and resume historical analysis, one
state model to verify, and one data source for later thesis analysis. The
migration requires explicit database versioning and may require new analysis
roots when an old format cannot be migrated safely. Proposed structure in this
decision must not be described as implemented behavior until the runtime
documentation and tests confirm it.
