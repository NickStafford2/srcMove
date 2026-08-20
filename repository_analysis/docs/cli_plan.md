# Repository Analysis CLI Plan

## Status

This document defines the intended command-line interface for
`repository_analysis`. The tool is under active development. Compatibility with
the current CLI, its JSON output, and existing analysis roots is not a design
constraint.

The runtime and storage model remain target-driven and resumable. This plan
changes how that model is presented to people and scripts.

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
```

There are no compatibility aliases. The Python module entry point may remain
available for development, but documentation and normal usage should use the
installed executable.

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
  --directory src \
  --srcdiff /workspace/srcDiff-install/bin/srcdiff \
  --srcmove /workspace/srcMove/build/srcMove \
  --jobs 6
```

Extension example:

```bash
srcmove-history run results/sqlite --pairs 500 --jobs 6
```

Creation requires `--repository` and `--name`. `--srcdiff` and `--srcmove`
default to the corresponding executables on `PATH`; explicit paths override
discovery. Before creating the analysis, the CLI prints the resolved repository,
revision, scope, tools, and target. These values are then frozen in the
authoritative database.

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

Writer activity must be determined by probing the operation lock. The activity
file supplies descriptive metadata but is not evidence that a process still
owns the analysis.

`status` includes the terminal prefix of a pending batch. A user should see the
same durable progress whether observing the active `run` command or invoking
`status` from another shell.

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

## Output contract

Every command accepts exactly one structured-output option:

```text
--format human|json
```

The default is `human`, regardless of whether stdout is a terminal. Scripts
must request JSON intentionally. This avoids output changing shape merely
because it was redirected.

Final results go to stdout. Progress and warnings go to stderr. JSON mode emits
one complete JSON document to stdout and never mixes it with progress output.

`run` additionally accepts:

```text
--progress auto|always|never
```

The default is `auto`: live progress on a TTY, periodic plain-text updates on a
non-TTY stderr stream, and no progress in JSON mode. `always` may be used to
request periodic progress while JSON is written to stdout.

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
0   requested target reached with no failed pairs
1   requested target reached, but one or more pairs failed
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

The status query needs one database snapshot that aggregates completed batches
and the terminal prefix of the pending batch. It should not ask callers to add
`completed_pair_count` and `pending.completed_prefix` themselves.

## Deliberate exclusions

The first redesign does not include:

- command or option aliases;
- compatibility with old command lines or JSON documents;
- migration of existing analysis roots;
- an interactive full-screen terminal interface;
- `status --watch`;
- shell completion;
- in-place reruns with different executable bytes;
- importing CLI code from the retiring benchmark implementation.

Executable immutability remains important. A future workflow for comparing a
new srcMove build should create a distinct analysis rather than silently
rewriting outcomes in an existing analysis.

## Implementation sequence

### 1. Data and query prerequisites

- settle the conceptual entities in [the data model](data_model.md) before
  changing presentation code;
- add explicit database schema versioning and the required migration boundary;
- persist invocation target, worker count, timestamps, wall duration, result,
  and last durable update, including verified no-op invocations;
- represent pair attempts separately from each pair's accepted outcome;
- freeze admitted commit metadata needed by `list` and `show`;
- implement snapshot-level `status`, bounded `list`, and lazy `show` query
  contracts without terminal formatting;
- add indexes only from demonstrated query needs.

### 2. Command and rendering foundation

- add the `srcmove-history` executable entry point;
- replace the current parser with `run`, `status`, `list`, and `show`;
- make the analysis path positional;
- add human and JSON renderers;
- record invocation wall time separately from summed pair timings;
- update CLI unit tests around user-visible behavior.

### 3. Durable progress

- add the observer interface and null implementation;
- emit publication and batch events from the analysis service;
- implement terminal-aware live and redirected progress;
- verify that rendering failures cannot corrupt analysis state;
- test ordered publication, resumed pending prefixes, and interruption output.

### 4. Operational status

- add a read-only writer-lock probe;
- combine activity metadata with authoritative lock state;
- aggregate committed and checkpointed outcomes in one database snapshot;
- render finite, through-commit, and all-history targets correctly.

### 5. Result exploration

- add indexed pair listing and filters;
- add one-pair human rendering;
- add optional Git diff presentation;
- keep verbose evidence lazy so large analyses remain inexpensive to inspect.

## Acceptance criteria

The redesign is complete when:

- a new user can understand the creation command from `run --help`;
- an active run always communicates durable progress within 30 seconds;
- another shell can report the same durable progress with `status`;
- final output distinguishes coverage, successful analysis, skips, and
  failures;
- parallel timing output distinguishes wall time from summed work;
- every failure summary points to a command that reveals the affected pairs;
- JSON stdout is valid, complete, versioned, and uncontaminated by progress;
- an interrupted run resumes without the UI overstating completed work;
- no production module imports the retiring benchmark CLI or progress code.
