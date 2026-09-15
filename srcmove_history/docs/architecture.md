# srcMove History Architecture Decision

- Status: accepted
- Date: 2026-08-20
- Last reviewed: 2026-09-15

## Context

srcMove previously had a production `srcmove_history` package and an
experimental receipt-based benchmark history runner. Their overlapping
execution and persistence models created more than one apparent way to run the
same analysis. The experimental runner was removed after its scaling study was
migrated to the production service.

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
- Benchmark adapters select repositories, revisions, and measurement settings
  through the supported analysis interface used by the CLI. They do not own a
  competing execution pipeline or persistence format.

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

## Boundary rules

Refactoring will preserve these established contracts:

- one SQLite authority and one nonblocking writer lock;
- frozen newest commit, configuration, and executable bytes;
- bounded batches, queues, and worker scratch;
- one work item per commit pair containing every relevant changed path;
- transactional pair publication and recoverable pending work;
- exactly one immutable terminal outcome per covered pair, linked to its
  producing invocation;
- stable pair ordering when older history is appended.

Readable move browsing, research reporting, and scaling studies use the
production analyzer. The retired receipt format has no compatibility reader or
migration path because preserving it would recreate a second state authority.

Attempt history and in-place retry policy are deliberately deferred. They will
be added only if a concrete requirement cannot be met by rerunning unpublished
work or creating a separate analysis.

## Consequences

There is one supported production path for executing and resuming historical
analysis, one state model to verify, and one data source for later thesis
analysis. Explicit database versioning permits clean breaks that require a new
analysis root when an old format cannot be migrated safely.
