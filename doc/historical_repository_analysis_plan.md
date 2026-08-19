# Historical Repository Analysis Plan

## Status and purpose

This document is an implementation plan, not a description of current behavior.
The current two-revision workflow is documented in the
[repository benchmark guide](../benchmarks/repositories/README.md).

The goal is to measure how srcMove's observed move counts change across a
linear sequence of adjacent repository commits. The program should select a
bounded commit history, run the existing srcDiff and srcMove benchmark pipeline
for each adjacent pair, and save a chronological, resumable result suitable for
later statistical analysis or visualization.

This is an extension of the repository benchmark, not a new detector and not a
change to srcMove's C++ pipeline. Existing input snapshots, srcDiff attempts,
corpora, srcMove runs, validation, provenance, and failure records remain the
authoritative per-pair artifacts.

## Research interpretation

Historical repository results are observations made by the current srcMove
algorithm. Without a labeled oracle, they do not establish the true number of
moves, precision, recall, or historical-move accuracy.

Report these units separately:

- `move_group_count`: logical move groups detected by srcMove; the primary
  longitudinal count
- `move_pair_count`: estimated paired regions, calculated as the sum of
  `min(delete_count, insert_count)` for each reported move group
- `annotated_region_count`: the sum of the reported move groups'
  `from_xpaths` and `to_xpaths`
- `regions_total`: all diff regions parsed from the srcDiff document, before
  move-candidate filtering
- moved-region share: `annotated_region_count / regions_total`, reported with
  both counts and left undefined when the denominator is zero

Keep exact and Type-2 match counts as separate series. Do not label any of
these fields simply as ground-truth "moves."

## Initial history definition

The first version should traverse Git's first-parent history. `--start S` is the
newest endpoint. Given requested pair count `N`, use the equivalent of
`git rev-list --first-parent --max-count=N+1 S`, then reverse that ancestry
order and compare each adjacent pair:

```text
C0 -> C1
C1 -> C2
...
C(N-1) -> CN
```

First-parent traversal provides one deterministic mainline through merge
history. A merge commit is compared with its first parent, so the result
measures what the merge introduced relative to that parent. Traversing every
parent edge, following side branches, and comparing arbitrary time windows are
future extensions because they describe different datasets.

"Chronological" means oldest-to-newest ancestry order, not sorting by commit
timestamp; Git timestamps need not be monotonic. Record all parent hashes,
`parent_count`, and ISO-8601 committer time. Derive merge status from
`parent_count > 1`.

If the selected history reaches the root commit, run the available pairs and
record that fewer than `N` pairs existed. Empty histories and histories with
only one reachable commit should fail before invoking srcDiff. Detect shallow
repositories and fail clearly rather than misreporting a shallow boundary as a
root commit.

## Proposed interface

Add `benchmarks/repositories/run_history.py` with separate create and resume
forms shaped like:

```bash
python3 benchmarks/repositories/run_history.py start CASE \
  --start REVISION \
  --count PAIRS \
  --label OPTIONAL_LABEL

python3 benchmarks/repositories/run_history.py resume HISTORY_ID \
  --retry-failed
```

The initial command should also accept the repository benchmark's relevant
overrides:

- `--directory`
- `--fetch` and `--offline`, which remain mutually exclusive
- `--data-root`
- `--srcdiff` and `--srcmove`
- srcDiff and srcMove timeouts
- source encoding
- `--position`, off by default as in the single-pair runner

Require a positive `--count` and an explicit `--start` in the first version. A
history manifest must store the requested revision and its resolved commit so a
moving branch name cannot silently change an existing study. History execution
requires archive-mode srcDiff; the single-pair `--no-srcdiff-archive` option is
intentionally not supported because multi-file and cross-file moves are part of
the dataset.

Do not add an excluded-suffix CLI until that option is shared cleanly with the
single-pair runner. The existing mandatory exclusions still apply. Record the
position setting and all filtering behavior in the manifest. A later
position-enabled study can support graph work without increasing every initial
counting run's corpus identity, runtime, and storage.

## Execution design

### 1. Reuse the repository cache

Use the case's existing `info.json` and `work/repo` cache. Clone or fetch at
most once per history invocation, then resolve the complete first-parent commit
list before processing any pair. Store that frozen list in the history
manifest.

Do not check out commits in the cached repository. Continue using `git archive`
exports so the developer's checkout and repository cache remain detached from
benchmark state. Create and record a namespaced local Git ref at the resolved
start commit so pending ancestors remain reachable if remote references move;
do not delete that ref automatically. On resume, verify that every frozen
commit object still exists before running another pair.

### 2. Prepare the staged per-pair interface

The current `run_staged_repository_benchmark()` is close to the required
boundary, but it does not yet fulfill the history runner's retry and
reconciliation contracts. Refactor it before adding the traversal loop so it:

- returns a structured terminal outcome and allocated benchmark entry path for
  `completed`, `srcdiff_failed`, `srcmove_failed`, and
  `orchestration_failed` outcomes instead of writing and then raising without a
  recoverable receipt
- accepts non-identity invocation context, including a stable history pair key
- checkpoints stage receipts containing at least the benchmark ID, input
  snapshot ID, generation or corpus ID, and run ID before or as each stage
  starts
- propagates the stable pair key into generation, run, and attempt context so
  partially indexed work can be reconciled
- exposes explicit failed-srcDiff retry control to `generate_corpus()`
- preserves the existing single-pair CLI and append-only attempt evidence

A repeated failed pair must not silently reuse a terminal failed srcDiff
attempt. `resume --retry-failed` should create a new repository benchmark entry
linked to the previous entry. A failed srcDiff stage requests a child attempt
through its existing generation batch. A terminal `srcmove_failed` entry reuses
the immutable corpus but creates a fresh srcMove run; it must not mutate the
failed run manifest in place. Reserve `run_corpus(..., resume_run=...)` for
recovering the same interrupted invocation using its checkpointed run ID. The
history pair record points to the latest entry while retaining the complete
entry and attempt chain. Successful pairs are never rerun during resume.

### 3. Reuse the staged per-pair pipeline

For each pair, export sparse old and new trees containing the changed source
paths and call
`run_staged_repository_benchmark()`. That function remains responsible for:

- filtered, checksummed input snapshots
- isolated srcDiff attempts and XML validation
- promotion into an immutable srcDiff corpus
- srcMove execution and JSON results
- timing, memory, executable provenance, and failure evidence
- append-only repository benchmark entries

The history runner should orchestrate these calls, not reproduce their storage
or process-control logic. Any small refactoring needed to expose repository
preparation or export helpers should preserve the existing single-pair CLI.

Use the union of content-changing paths from both revisions, preserving their
repository-relative paths. Modified paths appear on both sides, additions only
on the new side, and deletions only on the old side. Treat renames as a deletion
plus an addition so cross-file move candidates remain visible. Unchanged files
cannot contribute insert or delete regions and needlessly dominate srcDiff time
on large repositories. Record the sparse path selection as part of the pair's
filtering scope and snapshot identity.

Reject symbolic links, submodules, and other non-regular Git objects as explicit
pair outcomes before extraction. Treat mode-only changes and pairs containing
only excluded suffixes as `no_analyzable_change`.

### 4. Keep pair identity independent of history selection

Input snapshot identity currently includes the dataset case ID, `source`,
filtering configuration, file identities, and adapter metadata. Do not place a
history ID, sequence number, requested branch name, commit subject, or display
label in those identity inputs.

Separate the current `source` argument into a canonical snapshot identity and
non-identity selection metadata if necessary. The canonical repository-pair
identity should contain only the configured case name, repository URL, resolved
old and new commit hashes, selected directory, and filtering scope. Store
history selection metadata in the repository benchmark entry and history index.
This allows the same resolved pair selected by two studies to reuse an input
snapshot and corpus. Add a test that proves this reuse; if the existing identity
contract cannot be changed safely, document the accepted non-reuse instead of
claiming it.

### 5. Add a history-level index

Create a small history index below the generated data root:

```text
benchmark-data/
  repository-histories/
    <history-id>/
      history.json
      summary.csv
```

`history.json` should contain:

- schema version, history ID, status, timestamps, and optional display label
- repository URL, selected directory, requested start revision, resolved start
  commit, traversal mode, and requested/available pair counts
- the complete ordered commit list and per-commit metadata used for reporting
- a frozen configuration fingerprint covering repository URL and directory,
  ordered commits, srcDiff and srcMove executable SHA-256 hashes,
  archive/position/source-encoding settings, normalized exclusions, timeouts,
  and relevant schema versions
- one ordered record per pair with sequence number, old/new hashes, status, and
  the relative path or identifier of its latest repository benchmark entry
- aggregate completed, no-analyzable-change, failed, and pending counts, plus
  move totals derived only from completed pairs

The history ID is the study identity and should also namespace the underlying
repository series. A user label is display metadata, not a second grouping
identity. The history index references canonical artifacts and must not copy
srcDiff XML, srcMove XML, results JSON, or attempt logs. Write it atomically
after every terminal pair so interruption does not erase completed work.

There is still a crash window between committing a per-pair repository entry
and updating `history.json`. Store a stable invocation key derived from
`history_id + sequence` in every repository entry. On startup and resume,
reconcile repository entries, stage receipts, runs, and attempts with those keys
before executing pending work. This also covers interruption after srcMove
finishes but before repository indexing. Allocate the benchmark ID before
expensive work and checkpoint in-progress stage ownership in `history.json`.

`summary.csv` is a convenience view rebuilt from `history.json` and referenced
per-pair benchmark entries. Its rows must follow commit order, not filename or
completion-time order. Include at least:

```text
sequence
old_commit
new_commit
new_committer_time_iso8601
new_commit_subject_display
is_merge
status
changed_paths
analyzable_changed_paths
included_files
excluded_files
move_group_count
move_pair_count
annotated_region_count
regions_total
moved_region_share
match_kind_exact_group_count
match_kind_type2_group_count
srcdiff_seconds
srcmove_seconds
repository_benchmark_id
```

Preserve missing values for failed pairs rather than substituting zero. A zero
from a successful srcMove run is a valid observation; a missing result is not.
`included_files` and `excluded_files` count snapshot entries across both old
and new sides, not changed paths. A reused corpus reports the duration of its
original srcDiff attempt, not time spent by the current history invocation.
Keep the raw commit subject in `history.json`; make the CSV display field safe
for spreadsheet formula interpretation while preserving normal CSV quoting.
Any history-wide move total must state its coverage as completed pairs over
selected pairs; failed and no-analyzable-change pairs are not implicit zeros.

### 6. Classify pair outcomes and continue through failures

Before exporting, inventory changed paths for the pair under the selected
directory and explicit suffix filters. Record total changed paths and those
remaining after these filters. If none remain, record
`no_analyzable_change` without invoking srcDiff; its metrics remain not
applicable rather than zero. This preflight describes explicit repository
filters, not a guarantee that srcDiff supports every remaining file.

Retain the underlying repository status without collapsing it into a generic
failure. Initial history statuses are `completed`, `no_analyzable_change`,
`export_failed`, `srcdiff_failed`, `srcmove_failed`, and
`orchestration_failed`. Define a missing selected directory, an unexportable
submodule, and rejected symbolic-link input as explicit per-pair data outcomes
rather than aborting the rest of the history.

A srcDiff crash, invalid XML document, timeout, or srcMove failure should
produce a failed pair record and allow later pairs to run. Unexpected
orchestration errors should checkpoint the current history as interrupted and
exit nonzero.

The final command should exit nonzero when any pair fails, while still printing
the completed/failed totals and artifact paths. This matches the repository
suite behavior and prevents partial datasets from appearing fully successful.

### 7. Resume without redefining the dataset

`resume HISTORY_ID` should load the frozen commit list and configuration from
`history.json`. It must not resolve the original branch or tag again. Skip
terminal successful and no-analyzable-change pairs and leave their artifact
references unchanged. Pending pairs run normally; failed pairs run again only
with `--retry-failed`.

Resume derives the case and configuration from its manifest rather than
accepting create-time overrides. Verify frozen commit availability and the
configuration fingerprint, including executable hashes, before continuing. A
changed tool, filter, timeout, or traversal definition requires a fresh history
ID rather than silently changing the study.

## Implementation sequence

### Phase 1: commit selection

- Add a pure helper that returns a chronological first-parent commit list.
- Collect commit hash, all parent hashes, ISO-8601 committer time, and subject in
  one bounded Git query.
- Define merge status from the number of parents.
- Reject shallow history and retain the resolved start with a namespaced local
  ref.
- Unit-test linear history, a merge, non-monotonic timestamps, a
  short/root-bounded history, shallow history, an invalid start revision, and
  invalid counts using temporary local repositories.

### Phase 2: staged-runner contract

- Separate canonical pair identity from invocation and selection metadata.
- Return structured outcomes for all terminal repository benchmark states.
- Add stable invocation keys and an early benchmark-ID checkpoint.
- Checkpoint stage identifiers and propagate invocation keys into attempt/run
  context for reconciliation.
- Expose explicit srcDiff failure retry; create a fresh run for a terminal
  srcMove failure and reserve in-place run resume for interrupted work.
- Verify that the existing single-pair runner remains unchanged for users.

### Phase 3: history orchestration

- Add the CLI and prepare the repository cache once.
- Freeze and save the selected commits before the first expensive tool run.
- Inventory filtered changed paths and classify pairs with no analyzable change.
- Export and execute each adjacent pair through the existing staged runner.
- Keep the configured repository case name and canonical resolved pair metadata
  stable so equivalent pairs can reuse artifacts across histories.
- Continue after terminal tool failures and checkpoint after each pair.

### Phase 4: reporting and resume

- Generate chronological `summary.csv` rows from canonical per-pair entries.
- Reconcile the crash window between repository and history checkpoints using
  the stable invocation key.
- Implement interruption-safe resume against the frozen manifest.
- Clearly distinguish zero moves, failed measurement, and pending work.
- Print a compact final report with totals and artifact paths.

### Phase 5: public entry points and documentation

- Add a focused Make target only after the Python interface is stable.
- Document operational commands in
  `benchmarks/repositories/README.md` and link back to this plan while work is
  incomplete.
- Update `benchmarks/README.md` only if the new workflow changes the benchmark
  taxonomy or public entry points.

## Verification strategy

Tests should use temporary local Git repositories and fixture executables; they
must not require network access or the real srcDiff/srcMove binaries.

Required coverage:

- exact adjacent-pair selection and chronological ordering
- first-parent behavior at merge commits
- ancestry ordering when commit timestamps are not monotonic
- root-bounded histories with fewer pairs than requested
- shallow-repository rejection and missing-object detection on resume
- one cache preparation per invocation
- successful multi-pair output and count propagation
- reuse of an identical resolved pair selected through two histories
- a pair with no changed paths remaining after directory/suffix filtering
- a selected directory absent from one revision
- a middle-pair srcDiff or srcMove failure followed by a successful later pair
- retry of a terminal failed srcDiff attempt only when requested
- atomic checkpoint state after interruption
- crash-window reconciliation without a duplicate repository entry or srcMove
  run
- interruption after srcMove completion but before repository indexing
- resume without rerunning completed pairs
- rejection of executable-hash or other configuration drift during resume
- CSV distinction between zero, failed, and pending results
- correct metric formulas, CSV quoting, and spreadsheet-safe subject display
- paths and identifiers that remain within the configured data root

After unit tests pass, run a small manual pilot of roughly 5–10 commits on a
compact C/C++ repository in Docker. Inspect at least one preserved srcDiff XML,
srcMove XML, results JSON, history manifest, and CSV row before attempting a
larger study.

## Scalability and limitations

The initial implementation favors auditable results over maximum throughput.
Each distinct adjacent pair normally creates a distinct sparse input snapshot
and corpus, and a change to one very large file may still dominate runtime.
Large projects or long histories should begin with a repository subdirectory
and a small pilot.

The existing pipeline excludes Python files because of the documented srcDiff
limitation. All exclusions must remain visible per pair and in the history
configuration. Changes involving only excluded or unsupported files must not be
interpreted as evidence of zero source movement across the whole commit.

Parallel pair execution is out of scope initially. Sequential execution makes
resource use, progress, failure diagnosis, and checkpointing easier to reason
about. Add bounded concurrency only if real measurements justify the added
complexity.

Tracking the identity of a code fragment across three or more revisions and
building a graph of where it moved are also out of scope. An explicitly
position-enabled study can preserve position-annotated XML alongside commit
hashes, XPaths, raw texts, and move groups for that later research, but a future
design must define identity across edits rather than assuming equal text means
the same historical entity.

## Completion criteria

The first version is complete when it can reproducibly select a bounded
first-parent history, process every adjacent pair through the existing staged
pipeline, reconcile interruption without duplicate work, retry failures only
when requested, resume against a frozen configuration, and emit an auditable
chronological summary that keeps move groups, estimated pairs, and annotated
regions distinct.
