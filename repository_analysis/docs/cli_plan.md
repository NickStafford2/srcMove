# Repository Analysis CLI Plan

## Status

This document defines the intended command-line interface for
`repository_analysis`. The tool is under active development. Compatibility with
the current CLI, its JSON output, and existing analysis roots is not a design
constraint.

The runtime and storage model remain target-driven and resumable. This plan
changes how that model is presented to people and scripts.

## Implementation snapshot

As of 2026-08-20, the backend foundation is substantially further along than
the user interface. Do not infer CLI completion from an implemented query or
storage contract.

| Area | State | What exists | What remains |
| --- | --- | --- | --- |
| Target-driven runtime | Implemented | `run` presents create, resume, extend, no-op verification, bounded batches, parallel workers, and failure exit status | Live progress is tracked separately below |
| Durable state | Implemented | SQLite schema v3, immutable analysis definition, admitted executable bytes, invocation records, terminal outcomes, and pending-batch recovery | No CLI-specific work required |
| Status data | First slice implemented | Snapshot aggregation, analysis identity, real writer-lock state, derived product state, and human/JSON output | Add verbose frozen configuration/tool detail and `status --watch` |
| Pair exploration | First slice implemented | `list` filtering/pagination and `show` evidence are exposed with human/JSON output | Add optional Git diff and refine verbose move evidence |
| Command surface | Partial | Repository-local `srcmove-history` with positional `run`, `status`, `list`, and `show`; PATH tool discovery | Add preflight, `--dry-run`, creation presets, and eventual installed-image PATH setup |
| Human output | First slice implemented | Run/status summaries and compact list/show views use analyzed/skipped/covered terminology | Add live progress and continue usability refinement from real studies |
| Live progress | Not implemented | Coordinator already publishes durable outcomes in order | Observer events, TTY display, redirected updates, ETA, and interruption rendering |
| Export | Not implemented | Normalized evidence is queryable in SQLite | Stable CSV/JSONL research exports |
| Benchmark retirement | Not started | Both implementations still exist | Move remaining studies/adapters to the production service, then remove the old runner |

In phase terms, the data/query prerequisites and first command/rendering slice
are complete. Result browsing has its first usable slice. Durable live progress
is now the highest-value next increment, followed by preflight/presets, Git diff
inspection, and export.

## Design assessment

Keep the current plan's strongest decisions:

- one `run` lifecycle instead of separate create/resume/continue commands;
- a positional analysis path;
- human output by default and explicitly requested structured output;
- durable progress as the primary progress number;
- final summaries that distinguish wall time from summed parallel work;
- no dependency from production code on the retiring benchmark runner.

The redesign should also address three workflow gaps:

1. **Creation is too verbose.** Tool discovery, sensible defaults, and an
   optional creation preset should make the common command short without
   hiding the frozen study definition.
2. **Status lacks a product-level state.** Raw counters are insufficient. The
   CLI must say whether the analysis is running, interrupted, idle, complete,
   or complete with pair failures, then show the evidence behind that state.
3. **Analysis is not the final research workflow.** Users need stable exports
   of pairs and moves without querying implementation tables or preserving a
   second results authority.

## Goals

The CLI should make five facts immediately clear:

1. which repository and analysis are being used;
2. what coverage target was requested;
3. how many pairs have been durably processed;
4. how those pairs ended: analyzed, skipped, or failed;
5. where to inspect moves and failures.

The interface should be small, predictable, and suitable for both interactive
use and automation. Human-readable output is the default. Structured output is
explicit.

## Terminology

Use the following words consistently in commands, documentation, and output:

- **analysis**: one immutable repository/configuration/tool definition and its
  accumulated history coverage;
- **target**: the absolute coverage requested by one invocation;
- **covered pair**: a pair with a durable terminal outcome, including a skip or
  failure;
- **analyzed pair**: a pair for which srcDiff and srcMove completed
  successfully;
- **skipped pair**: a pair with no analyzable change;
- **failed pair**: a pair that ended in export, srcDiff, srcMove, or
  orchestration failure;
- **checkpointed pair**: a durable outcome in the current pending batch;
- **committed coverage**: completed batches incorporated into the analysis
  frontier.

Do not use `completed` in human-facing output to mean only successful analysis.
For example, a target with 41 successful pairs, 56 skips, and 3 failures is:

```text
100/100 covered: 41 analyzed, 56 skipped, 3 failed
```

## Program and command structure

Install one executable named `srcmove-history`.

```text
srcmove-history run ANALYSIS [OPTIONS]
srcmove-history status ANALYSIS [OPTIONS]
srcmove-history list ANALYSIS [OPTIONS]
srcmove-history show ANALYSIS PAIR [OPTIONS]
srcmove-history export ANALYSIS [OPTIONS]
```

There are no compatibility aliases. The Python module entry point may remain
available for development, but documentation and normal usage should use the
executable. The first delivery may be a repository-owned `bin/srcmove-history`
wrapper made available on the development image's `PATH`; do not introduce a
Python packaging system solely to rename this command. A package entry point
can replace the wrapper later without changing the interface.

`ANALYSIS` is a positional path in every command. A positional path is shorter
and easier to scan than repeating `--analysis-root`.

### `run`

`run` creates, resumes, or extends an analysis toward one absolute target. It
does not expose separate `create`, `resume`, or `continue` state machines.

Exactly one target is required:

```text
--pairs N          cover the newest N adjacent pairs in total
--through COMMIT   cover through one full first-parent commit ID
--all              cover all available first-parent history
```

`--pairs` is absolute, not incremental. Repeating a satisfied target verifies
the analysis and exits without opening workers.

Creation example:

```bash
srcmove-history run results/sqlite \
  --pairs 100 \
  --repository benchmarks/repositories/sqlite/work/repo \
  --name sqlite \
  --start version-3.50.0 \
  --directory src \
  --srcdiff /workspace/srcDiff/build/bin/srcdiff \
  --srcmove /workspace/srcMove/build/srcMove \
  --jobs 6
```

Extension example:

```bash
srcmove-history run results/sqlite --pairs 500 --jobs 6
```

Creation requires `--repository`. `--name` defaults to a clearly displayed
name derived from the repository or analysis directory. `--start` defaults to
`HEAD`; the resolved full commit ID is frozen. `--srcdiff` and `--srcmove`
default to the corresponding executables on `PATH`; explicit paths override
discovery. If discovery fails, the error names the missing executable and the
option that supplies it.

Before doing work, the CLI prints a preflight containing the resolved
repository, revision, scope, executable paths and digests, target, and worker
count. These values are then frozen in the authoritative database. `--dry-run`
performs the complete preflight without creating the analysis or opening
workers.

An optional TOML creation preset removes repeated setup from study workflows:

```bash
srcmove-history run results/sqlite-300 \
  --config studies/sqlite.toml \
  --pairs 300 \
  --jobs 8
```

The preset is an input, not saved authority. CLI options override preset
values, the resolved definition and preset digest are recorded at creation,
and later runs read the definition from SQLite rather than rereading the file.
Do not add a global mutable profile registry or an implicit "latest" analysis;
explicit analysis paths are easier to reproduce in thesis automation.

Configuration options such as `--directory`, encodings, exclusions, and tool
timeouts are creation-only. Passing one while resuming an existing analysis is
an error, even if it happens to equal the stored value. This gives every option
one clear purpose and avoids an apparent ability to modify frozen state.

`--jobs` is invocation configuration and may change between runs.

### `status`

`status` reports a read-only snapshot of an analysis:

```bash
srcmove-history status results/sqlite
```

It reports:

- running, idle, interrupted, or target-reached state;
- current or most recent invocation metadata;
- requested target;
- committed and checkpointed coverage;
- analyzed, skipped, and failed outcomes;
- move totals;
- newest commit and current history frontier;
- elapsed wall time and last durable update.

The first line is a derived product state, not an invocation result copied from
the database:

- `running`: the writer lock is held;
- `target reached`: durable coverage satisfies the most recent target with no
  failed pairs;
- `target reached with failures`: coverage satisfies the target but includes
  failed pairs;
- `history exhausted`: the repository root was reached before a numeric target
  could be satisfied (for example, 300 available pairs of 500 requested);
- `interrupted`: no writer owns the lock and the latest invocation did not
  finish;
- `idle`: the analysis is valid but has not reached the latest target;
- `failed`: the most recent command failed at orchestration or storage level.

Writer activity must be determined by probing the operation lock. The activity
file supplies descriptive metadata but is not evidence that a process still
owns the analysis.

`status` includes the terminal prefix of a pending batch. A user should see the
same durable progress whether observing the active `run` command or invoking
`status` from another shell.

`status --watch` is a line-oriented view of repeated snapshots. It redraws on a
TTY and emits sparse updates when redirected. This is valuable when `run` is in
another Docker shell and does not require a full-screen terminal UI.

For the example analysis in this plan's motivating workflow, normal status
should resemble:

```text
SQLite — target reached with failures

Coverage   300/300 pairs (100%)
Results     70 analyzed · 211 skipped · 19 failed
Failures    19 srcDiff
Moves       59 groups · 67 move pairs · 156 annotated regions
Time         2m 07s wall · 187.0s srcDiff work · 43.0s srcMove work
Frontier     3f523613 → 0a4af54a
Analysis     /workspace/srcMove/benchmark-data/repository-analysis/sqlite-300

Inspect: srcmove-history list .../sqlite-300 --failed
```

Human status calls the durable total `coverage`; it does not label the 70
successful outcomes `completed`. Committed/checkpointed detail is shown only
while useful (an active or interrupted pending batch) or under `--verbose`.

### `list`

`list` shows compact pair rows. Its filters answer the common follow-up
questions without dumping the database representation.

```bash
srcmove-history list results/sqlite
srcmove-history list results/sqlite --failed
srcmove-history list results/sqlite --moves
srcmove-history list results/sqlite --status srcdiff-failed
```

`--failed`, `--moves`, and `--status` are mutually exclusive filters. Pagination
or a default row limit should be added before this command is used for very
large analyses. Ordering is newest to oldest unless the user requests
`--oldest-first`.

Each row contains a stable displayed pair number, abbreviated old and new
commits, status, changed/analyzable path counts, move count, and elapsed pair
time. The full stable `distance_from_newest` value is available in structured
output.

### `show`

`show` presents the evidence for one pair:

```bash
srcmove-history show results/sqlite 42
srcmove-history show results/sqlite 42 --diff
srcmove-history show results/sqlite 42 --verbose
```

Displayed pair numbers are one-based and newest-first. Output also identifies
the underlying `distance_from_newest` value so ordering semantics are explicit.

Normal output includes commits, status, changed-path counts, timings, failure
detail, and detected moves. `--diff` obtains the Git diff from the frozen
commits. Stored pair evidence remains available without the original repository,
but reconstructing a diff requires the configured repository and retained Git
objects. If that reconstruction is unavailable, `show` still renders stored
evidence, reports the diff error explicitly, and exits two because the requested
enrichment was not fulfilled. JSON represents the unavailable diff as a
structured status and error rather than emitting partial text. Without
`--diff`, `show` never requires Git access.

`--verbose` adds XPaths, digests, executable observations, and other diagnostic
evidence.

### `export`

`export` produces stable research tables from the authoritative database:

```bash
srcmove-history export results/sqlite --table pairs --format csv > pairs.csv
srcmove-history export results/sqlite --table moves --format jsonl > moves.jsonl
```

The initial tables are `pairs` and `moves`. Each row includes the analysis
identity and full commit IDs so concatenating exports from several analyses is
safe. CSV and JSONL schemas are explicitly versioned in documentation and are
independent of physical SQLite tables. Export writes data to stdout and a short
summary to stderr; it never writes a hidden derived authority inside the
analysis root.

## Output contract

`run`, `status`, `list`, and `show` accept one presentation option:

```text
--format human|json
```

The default is `human`, regardless of whether stdout is a terminal. Scripts
must request JSON intentionally. This avoids output changing shape merely
because it was redirected.

Final results go to stdout. Progress and warnings go to stderr. JSON mode emits
one complete JSON document to stdout and never mixes it with progress output.
`export` instead uses `--format csv|jsonl` because its stdout is a research
table rather than a command result.

`run` additionally accepts:

```text
--progress auto|always|never
```

The default is `auto`: live progress on a TTY, periodic plain-text updates on a
non-TTY stderr stream, and no progress in JSON mode. `always` may be used to
request periodic progress while JSON is written to stdout.

All commands also accept `--quiet` to suppress nonessential stderr output.
`--quiet` does not change stdout's selected format and never suppresses errors.

Human output may evolve for clarity. JSON documents are versioned and should
use nested concepts rather than exposing a flat copy of database columns:

```json
{
  "schema_version": 1,
  "analysis": {
    "name": "sqlite",
    "root": "/workspace/repository_analysis/results/sqlite"
  },
  "state": "target_reached_with_failures",
  "target": {"kind": "pairs", "value": 100},
  "coverage": {
    "target": 100,
    "committed": 100,
    "checkpointed": 0,
    "durable": 100
  },
  "outcomes": {"analyzed": 41, "skipped": 56, "failed": 3},
  "moves": {"groups": 1, "pairs": 1, "annotated_regions": 2}
}
```

Do not expose internal batch IDs, database revisions, or schema mechanics in
default human output. They belong in JSON or verbose diagnostics.

## Live progress

Progress represents durable work first. Update it only after a pair outcome has
been successfully recorded.

For a finite target:

```text
⠼ Analyzing sqlite [██████████······] 63/100  63%  01:14  ETA 00:44
  24 analyzed · 37 skipped · 2 failed · 1 move · 6 workers
```

Workers can finish out of order while publication waits for an earlier pair.
If useful, a secondary `finished` count may expose this distinction, but the
primary number is always durable, contiguous progress.

ETA is omitted until enough current-invocation samples exist and is based on
recent durable throughput rather than lifetime average pair work. A misleading
ETA is worse than no ETA. The progress detail may show `finished` separately
when publication is waiting on an earlier slow pair.

For `--all`, the final size is unknown. Do not display a percentage or invented
ETA:

```text
⠼ Analyzing sqlite 327 pairs covered · current batch 27/100 · 08:42
```

When stderr is not a TTY, emit a start line, updates at meaningful milestones
or at most once every 30 seconds, and one finish line. Do not emit one log line
per pair by default.

## Final summaries

A successful run without analysis failures ends with:

```text
SQLite history analysis complete

Coverage   100/100 pairs
Results     44 analyzed · 56 skipped · 0 failed
Moves        1 group · 1 move pair · 2 annotated regions
Time         1m 59s wall · 87.3s srcDiff work · 23.0s srcMove work
History      9e5727e5 → 7d3a41d1
Analysis     /workspace/repository_analysis/results/sqlite
```

A run containing terminal failures is explicit and actionable:

```text
SQLite history analysis reached its target with failures

Coverage   100/100 pairs
Results     41 analyzed · 56 skipped · 3 failed
Failures     3 srcDiff
Moves        1 group · 1 move pair · 2 annotated regions
Time         1m 59s wall · 87.3s srcDiff work · 23.0s srcMove work
History      9e5727e5 → 7d3a41d1
Analysis     /workspace/repository_analysis/results/sqlite

Inspect: srcmove-history list /workspace/repository_analysis/results/sqlite --failed
```

Wall time and summed worker time are different measurements when jobs run in
parallel. Always label summed srcDiff and srcMove durations as work; never
present their sum as invocation wall time.

## Exit status

Use a small, documented exit-status contract:

```text
0   run completed with no failed pairs, including clean history exhaustion
1   run completed, but one or more covered pairs failed
2   usage, configuration, storage, or execution error
130 interrupted by the user
```

`status`, `list`, and `show` return zero when their query succeeds. A historical
pair failure is data for those commands, not a command failure.

## Internal design

Terminal rendering must not be embedded in worker, coordinator, or database
code. Add a small observer interface at the analysis service boundary:

```python
class AnalysisObserver(Protocol):
    def analysis_started(self, snapshot): ...
    def batch_started(self, snapshot): ...
    def pair_finished(self, event): ...
    def pair_published(self, event): ...
    def batch_committed(self, snapshot): ...
    def analysis_finished(self, summary): ...
```

Initial implementations are:

- `NullObserver` for library callers and most tests;
- `TerminalObserver` for human progress.

`pair_published` fires only after the outcome transaction commits. A separate
`pair_finished` event may support an out-of-order worker count, but it never
advances the durable progress bar.

The observer receives immutable presentation values, not database or worker
objects. It must not be able to affect scheduling, publication, recovery, or
exit status.

Human and JSON renderers likewise consume immutable command result models.
They do not receive database rows. Keep naming conversion in one presentation
layer: stored `completed` becomes human `analyzed`, and
`no_analyzable_change` becomes human `skipped`.

The status query needs one database snapshot that aggregates completed batches
and the terminal prefix of the pending batch. It should not ask callers to add
`completed_pair_count` and `pending.completed_prefix` themselves.

## Deliberate exclusions

The first redesign does not include:

- command or option aliases;
- compatibility with old command lines or JSON documents;
- migration of existing analysis roots;
- an interactive full-screen terminal interface;
- shell completion;
- in-place reruns with different executable bytes;
- an implicit global catalog or "latest analysis" lookup;
- cross-analysis comparison;
- importing CLI code from the retiring benchmark implementation.

Executable immutability remains important. A future workflow for comparing a
new srcMove build should create a distinct analysis rather than silently
rewriting outcomes in an existing analysis.

## Implementation sequence

Update the implementation snapshot above whenever a phase lands. A checked-off
backend item is not evidence that its CLI is complete.

### 1. Close presentation-model gaps

- add analysis identity, frozen repository/configuration, and admitted-tool
  summaries to the read model;
- freeze commit subject, timestamp, parents, and merge status needed by list
  and show, or explicitly defer each field from the first renderer;
- add a read-only writer-lock probe and combine it with activity metadata;
- define versioned result models for human/JSON status and exports;
- retain the existing snapshot-level status, bounded list, and lazy show query
  contracts rather than adding presentation SQL.

### 2. Ship a `run`/`status` vertical slice

- add the installed `srcmove-history` executable;
- replace `analyze` with `run` and make the analysis path positional;
- add human and JSON renderers with the terminology in this plan;
- implement executable discovery, preflight, `--dry-run`, and creation presets;
- render the lock-aware product state and actionable failure command;
- update CLI tests around stdout/stderr separation and user-visible behavior.

This phase is the first useful release of the redesigned CLI. Do not wait for
every browsing feature before making normal runs understandable.

### 3. Add durable progress and watching

- add the observer interface and null implementation;
- emit publication and batch events from the analysis service;
- implement terminal-aware live and redirected progress;
- verify that rendering failures cannot corrupt analysis state;
- test ordered publication, resumed pending prefixes, and interruption output.
- implement `status --watch` over the same status snapshots, not a second
  monitoring protocol.

### 4. Expose result exploration

- add indexed pair listing and filters;
- add one-pair human rendering;
- add optional Git diff presentation;
- keep verbose evidence lazy so large analyses remain inexpensive to inspect.

### 5. Export and retire the old runner

- implement versioned `pairs` and `moves` CSV/JSONL exports;
- port benchmark adapters and scaling studies to the production service;
- verify that production browsing covers the useful old `show` workflow;
- remove `benchmarks/repositories/run_history.py` only after its remaining
  consumers have migrated.

## Acceptance criteria

The redesign is complete when:

- a new user can understand the creation command from `run --help`;
- `run --dry-run` shows the exact frozen definition without changing state;
- an active run always communicates durable progress within 30 seconds;
- another shell can report the same durable progress with `status`;
- `status --watch` never reports stale activity as a live writer;
- final output distinguishes coverage, successful analysis, skips, and
  failures;
- parallel timing output distinguishes wall time from summed work;
- every failure summary points to a command that reveals the affected pairs;
- JSON stdout is valid, complete, versioned, and uncontaminated by progress;
- an interrupted run resumes without the UI overstating completed work;
- pair and move exports have documented, versioned schemas independent of the
  SQLite layout;
- no production module imports the retiring benchmark CLI or progress code.
