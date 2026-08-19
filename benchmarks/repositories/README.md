# Repository Benchmarks

These benchmarks compare two configured revisions of a real repository through
the validated srcDiff corpus and srcMove run pipeline. Each invocation saves an
append-only result automatically; the mutable `work/` directory is only a
checkout/export cache.

From the workspace root, run and save one configured case in Docker:

```bash
make benchmark-repo CASE=notepadpp
```

Run the deterministic standard suite:

```bash
make benchmark-repos SERIES=thesis-pilot
```

[`suites.json`](suites.json) is the versioned source of truth for suite
membership and ordering. The runner never discovers cases from directories.
The standard suite contains only external repositories and spans several scales:

| Case | Scope | Role |
| --- | --- | --- |
| `notepadpp` | full tree, adjacent releases | cross-project baseline |
| `sqlite` | `src/`, pinned releases | source-focused baseline |
| `opencv` | full tree, `4.8.0` to `4.8.1` | large-repository baseline |

The Linux scheduler benchmark is isolated in the opt-in `linux` suite because
its repository checkout is unusually large. It compares `kernel/sched/` from
`v6.12` to `v6.13`; both the source scope and adjacent mainline release tags are
declared in [`linux/info.json`](linux/info.json). The two srcMove
self-benchmarks remain in the opt-in `srcmove` suite. List the resolved suites
without running them, or select one explicitly:

```bash
make benchmark-repos LIST=1
make benchmark-repos SUITE=linux SERIES=linux-scheduler-v6.12-v6.13
make benchmark-repos SUITE=srcmove SERIES=srcmove-investigation
```

Add or exclude a configured case for a one-off suite invocation with `CASE` or
`EXCLUDE_CASE`. The configured suite order is preserved, and explicit additions
follow it. Every selected case uses the same series. The runner continues after
a failed case, preserves its manifest, prints all case outcomes, and exits
nonzero if any case failed.

Group manual single-case invocations into a named series when a suite is not the
right abstraction:

```bash
make benchmark-repo CASE=notepadpp SERIES=thesis-pilot
make benchmark-repo CASE=sqlite SERIES=thesis-pilot
```

Inside `srcMove` in the Docker shell, the same `make benchmark-repo` commands
work. The runner clones a missing repository, otherwise reuses its local cache.
If a requested revision is missing, it fetches once and retries.

The command resolves exact commits, exports both revisions, creates or reuses an
[input snapshot](../README.md#staged-corpus-workflow) and srcDiff corpus, runs
srcMove only on admitted XML, and creates a new append-only srcMove run. It
prints live or periodic progress plus a readable result and artifact summary.
No benchmark artifacts are copied between runs.

Progress and summaries distinguish operations that were `created`, `reused`,
checksum-`verified`, or `executed`. A reused corpus reports the recorded time and
peak memory of its original srcDiff execution; it is not presented as time spent
by the current invocation. Manifests and CSV files retain the detailed numeric
and provenance fields used for later analysis.

Generated data defaults to:

```text
benchmark-data/
  input-snapshots/<content-id>/    frozen, checksummed old/new source pairs
  attempts/<attempt-id>/           srcDiff commands, logs, output, and status
  corpora/<content-id>/            admitted immutable srcDiff XML
  runs/<run-id>/                   append-only srcMove output and results
  repository-runs/<series>/
    repository-<id>.json           one readable index per invocation
    summary.csv                    concise series-level table
```

The small repository-run index references canonical artifacts; it does not
duplicate them. Repeating an identical case reuses its input snapshot and corpus
but always creates a distinct srcMove run and index record.

Successful srcDiff XML lives only in its corpus; the originating attempt records
the promoted corpus path and discards its temporary copy. A successful srcMove
run always retains `results.json`. It retains `srcmove.xml` when moves were found
and discards it after validation when `move_count` is zero. Failed or invalid
tool output is retained for diagnosis.

If srcDiff crashes, times out, or emits invalid archive XML, the command returns
nonzero, saves the failure, and prints exact `replay` and `isolate` commands. A
zero-move srcMove result remains a valid observation; structurally empty archive
output from srcDiff is rejected before srcMove runs.

Override revisions or explicitly update the cached checkout when needed:

```bash
python3 benchmarks/repositories/run_case.py notepadpp \
  --old-rev OLD \
  --new-rev NEW \
  --fetch
```

Use `UPDATE=1` with the Make target to fetch before a run. Use `OFFLINE=1` (or
`--offline` with `run_case.py`) to prohibit all clone and fetch operations.
Case configuration may use stable release tags for readability. Every run saves
both the requested tags and their resolved commit hashes for exact provenance.
Avoid moving references such as `HEAD` or branch names; use a full commit hash
when no suitable release tag exists.

The Linux kernel case uses a full, non-shallow repository cache so later history
analysis can resolve parent commits. The first `linux` suite run clones that
cache automatically, then runs the configured scheduler comparison:

```bash
make benchmark-repos SUITE=linux SERIES=linux-scheduler-v6.12-v6.13
```

The clone is stored at `benchmarks/repositories/linux/work/repo`. Listing suites
does not clone it, and the standard suite does not include Linux. To prepare the
checkout without starting a benchmark, run this from the workspace root:

```bash
git clone https://github.com/torvalds/linux.git \
  srcMove/benchmarks/repositories/linux/work/repo
```

Do not use `--depth`: the historical runner rejects shallow repositories. A
later history study should use commit-to-parent edges rather than treating the
kernel's merge-heavy first-parent chain as individual patch history.

`wowy_advanced_analytics` is excluded from every suite because it is Python and
the current snapshot pipeline excludes `.py` files. `zlib` is also excluded:
its current configuration runs backward from `v1.3.2` to `v1.2.3` and must not
be used until the intended comparison is confirmed. `context_export` and
`firefox` remain unavailable because they have no pinned revisions.

`build_examples.py` turns selected benchmark results into ignored example
artifacts for documentation or manual inspection.

## Experimental first-parent history runner

The initial historical-analysis runner can freeze and execute a bounded sequence
of adjacent first-parent commit pairs. For example, this selects the newest
three SQLite pairs after fetching and processes them oldest-to-newest:

```bash
python3 benchmarks/repositories/run_history.py start sqlite \
  --start origin/HEAD --count 3 --fetch --jobs 2
```

`--jobs N` bounds the number of commit pairs processed concurrently and
defaults to `1`. Pair selection, receipts, CSV rows, and command output remain
in oldest-to-newest sequence order. Each worker receives a separate numbered
export/work directory and only returns a structured pair outcome. The
coordinator alone checkpoints pair receipts and `history.json`, updates terminal
progress, and builds `summary.csv`, `moves/`, and the `latest` link. Derived
history-wide views are rebuilt only at history initialization and finalization,
not after every pair.

Show every detected move from the latest saved history:

```bash
make history-results

# Equivalent direct command:
python3 benchmarks/repositories/run_history.py show
```

The command prints only commit pairs with moves, including match kind, move ID,
source and destination file/function, and the moved text. Select a history by
ID, path, or label; repeated labels resolve to their most recently updated run:

```bash
make history-results HISTORY=sqlite-100-pair
```

Inspect one 1-based pair and include its source patch:

```bash
make history-results PAIR=16 DIFF=1
```

Use `VERBOSE=1` to include source/destination XPath values and canonical
`results.json` and annotated `srcmove.xml` paths. With the direct Python command,
the equivalent options are `--pair`, `--diff`, and `--verbose`. The annotated
XML exists only for successful runs that detected moves.

The case's configured directory still applies; SQLite currently measures
`src/`. A selected commit whose adjacent change has no paths remaining in that
scope and the mandatory suffix filters is recorded as `no_analyzable_change`,
not as zero moves. History studies use their own compact index:

```text
benchmark-data/repository-histories/<history-id>/
  history.json               study configuration, commits, status, aggregates
  pairs/000001.json          one canonical receipt per adjacent commit pair
  pairs/000002.json
  results/000001.json        srcMove result for each analyzed pair
  moves/000016/              browseable view of one positive pair
    results.json             relative link to the retained srcMove result
  summary.csv                table rebuilt from the pair receipts
```

History pairs do not also create `repository-runs/<history-id>/` entries or a
second summary. Pair receipts reference the canonical snapshot, corpus, attempt,
run, and result artifacts instead of copying them.

`benchmark-data/repository-histories/latest` points to the most recently written
history. Its `moves/` directory contains only pairs where srcMove detected at
least one move, so the underlying artifacts can be opened without following
content IDs or attempt UUIDs:

```bash
ls benchmark-data/repository-histories/latest/moves
python3 -m json.tool \
  benchmark-data/repository-histories/latest/moves/000016/results.json
```

The positive-move result is a relative symbolic link, not an artifact copy.
Zero-move observations retain their compact `results.json` for frequency
calculations but do not clutter the positive-move browse view. XML files appear
there only when an XML-retaining policy was selected.

### History retention

History runs default to `--retention results`. This keeps the history report and
every successful `results.json`, including zero-move observations, while
discarding successful srcDiff/srcMove XML, snapshots, corpora, attempts, and
other pipeline intermediates. Positive results are linked under `moves/` for
quick inspection. Failed-pair status remains in its pair receipt; the recorded
commits and tool configuration can be used to reproduce it.

The default runs in a history-owned isolated directory and removes that
directory only after the complete history has been finalized. It does not read,
populate, or delete the shared benchmark cache. `--no-cache` is an alias for
this default policy.

Use `--retention full` when repeated analysis speed matters more than storage.
It uses the shared content-addressed snapshot and srcDiff corpus cache, keeps
compact zero-move results, retains positive srcMove XML, and provides the
fastest repeated analysis.

For large one-off studies, compact retention runs the pipeline in a directory
owned only by that history:

```bash
python3 benchmarks/repositories/run_history.py start sqlite \
  --start origin/HEAD --count 100 --fetch \
  --label sqlite-100-pair --retention compact
```

After successful completion, compact retention keeps:

- the history manifest, pair receipts, and CSV summary;
- `results.json`, `srcmove.xml`, and `srcdiff.xml` for positive pairs;
- complete input, process, and output evidence for failed pairs.

It discards successful zero-move snapshots, corpora, runs, and attempts. The
Non-full modes never populate or delete the shared cache.

Ephemeral retention keeps only the history report and compact per-pair metrics:

```bash
python3 benchmarks/repositories/run_history.py start sqlite \
  --start origin/HEAD --count 100 --fetch \
  --label sqlite-100-pair --retention ephemeral
```

It records whether moves were detected but discards detailed move text, XML,
failure evidence, and all intermediate artifacts after a completed history. If
a results, compact, or ephemeral run is interrupted, its isolated `.pipeline` directory
is intentionally left intact for diagnosis rather than being cleaned blindly.

History pairs use sparse old/new exports containing only content-changing paths.
Modified files appear on both sides, additions only on the new side, and
deletions only on the old side. Renames are represented by their old and new
paths so cross-file moves remain detectable. Relative repository paths are
preserved, and the exact sparse selection is recorded in the history and input
snapshot identity. Parallel workers read the frozen Git repository concurrently
but never check it out or modify it; their numbered export/work directories are
removed after the coordinator has collected every outcome.

History timings distinguish work performed by the current command from cached
attempt provenance. `srcdiff_execution_seconds` counts only a srcDiff process
started by the current history run. Cache reuse time covers current snapshot and
corpus verification, while `srcdiff_cached_execution_seconds` retains the
original attempt duration for reference and is excluded from current-run totals.
Fine-grained profile fields record verification, interrupted-attempt recovery,
reconciliation, executable observation, and history-artifact writes.
New srcMove runs do not recover unrelated prior runs; an explicit resume recovers
only the selected run before reconciling its attempts.
srcDiff writes an initial generation checkpoint before execution. Fresh and
complete generations avoid global attempt scans; only an existing incomplete
generation performs recovery and reconciliation.

This is the create-only pilot described in the
[historical repository analysis plan](../../doc/historical_repository_analysis_plan.md).
Resume, retry, and crash-window reconciliation remain planned work.

## Advanced staged workflow

For advanced use with already-exported revision trees, create an input snapshot:

```bash
python3 benchmarks/pipeline.py snapshot \
  --case-id my-repository-case \
  --original /path/to/old/export \
  --modified /path/to/new/export \
  --source-json '{"repository":"URL","old":"COMMIT","new":"COMMIT"}'
```

Filters are non-destructive and part of the input snapshot identity. Python
files are always excluded because of the documented
[srcDiff language limitation](../README.md#current-srcdiff-language-limitation).
Use `--exclude-suffix` only for additional unsupported suffixes. The manifest
records every excluded path and the original export remains unchanged.

The command prints an input snapshot identifier. Generate a reusable srcDiff
corpus from it:

```bash
python3 benchmarks/pipeline.py generate INPUT_SNAPSHOT_ID \
  --srcdiff /path/to/srcdiff \
  --timeout 1800
```

Generation writes a terminal attempt record even when srcDiff exits nonzero,
receives a signal, times out, omits output, or emits invalid XML. Only admitted
XML appears below `benchmark-data/corpora/`.

Generation is resumable. The same command skips terminal cases already present
in its checkpoint. Retry all failed cases, or selected failures, with:

```bash
python3 benchmarks/pipeline.py generate INPUT_SNAPSHOT_ID \
  --srcdiff /path/to/srcdiff \
  --retry-failed \
  --case CASE_ID
```

Each retry points to its parent attempt and increments the retry ordinal.

Run srcMove from the immutable corpus as many times as needed:

```bash
python3 benchmarks/pipeline.py run CORPUS_ID \
  --srcmove /path/to/srcMove \
  --timeout 300
```

Each invocation creates a new directory below `benchmark-data/runs/`. Corpus
replay does not access the original exports or invoke srcDiff. Use `--data-root`
before the subcommand to select an external generated-data location.

Resume an interrupted run without repeating terminal cases, or retry selected
failures in that same run:

```bash
python3 benchmarks/pipeline.py run CORPUS_ID \
  --srcmove /path/to/srcMove \
  --resume-run RUN_ID \
  --retry-failed
```

Replay one failed srcDiff attempt on a preserved file pair, or bisect an archive
to retain a smaller reproduction:

```bash
python3 benchmarks/investigate.py replay ATTEMPT_ID \
  --relative-path path/to/file.cpp
python3 benchmarks/investigate.py isolate ATTEMPT_ID
```

The public `run_case.py` command performs these stages automatically. Use the
low-level commands only for debugging, unusual input snapshots, or retrying a
specific stage.
