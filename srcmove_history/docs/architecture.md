# srcMove History Architecture Decision

- Status: accepted
- Date: 2026-08-20
- Last reviewed: 2026-09-15

## Context

srcMove has two remaining generations of repository-history analysis: the
production `srcmove_history` package and an experimental benchmark history
runner. An older receipt-based package architecture was removed during the
initial consolidation. The remaining implementations still overlap in
execution and presentation, leaving more than one apparent way to run the same
analysis.

## Decision

`srcmove_history` is the history-analysis component of the srcMove product. It
remains in the srcMove repository while retaining a distinct internal boundary.
Its SQLite database is the sole authoritative state. Benchmark tools may
configure or measure it, but must not own a competing execution pipeline or
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
        +----> status / report / list / show queries
```

`run` is the only CLI command that changes analysis coverage. It creates a new
analysis when none exists, resumes interrupted work, or extends completed
coverage until the requested absolute target is reached. If that target is
already satisfied, it validates the existing analysis and performs no pair
execution. Users do not need to choose separate start, resume, or continue
commands.

Program responsibilities are separated as follows:

- The CLI parses arguments and renders results; it does not orchestrate work.
- The application service owns create, resume, extension, and batch planning.
- The execution pipeline owns one frozen adjacent-commit pair and returns a
  normalized outcome without publishing shared state.
- The persistence layer owns schema migrations, transactions, and integrity.
- Query and reporting services do not schedule pair execution or modify
  analysis coverage. They read SQLite and may resolve retained analysis
  artifacts or frozen Git context needed for inspection.
- Benchmark adapters must select repositories, revisions, and measurement
  settings through the supported analysis interface used by the CLI. The
  remaining legacy benchmark history runner violates this boundary and is
  scheduled for retirement.

The durable model distinguishes an immutable analysis, a command invocation, a
frozen commit pair, its one canonical terminal outcome, and normalized move
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

Readable move browsing and research reporting now use the production analyzer.
The remaining scaling workflow must be rebuilt as a benchmark adapter over
`srcmove_history`; the legacy receipt-based runner must then be removed rather
than retained as a compatibility architecture.

Attempt history and in-place retry policy are deliberately deferred. They will
be added only if a concrete requirement cannot be met by rerunning unpublished
work or creating a separate analysis.

## Consequences

There is one supported production path for executing and resuming historical
analysis, one state model to verify, and one data source for later thesis
analysis. Explicit database versioning permits clean breaks that require a new
analysis root when an old format cannot be migrated safely. The legacy
benchmark runner remains temporary migration work, not a second supported
product path.
