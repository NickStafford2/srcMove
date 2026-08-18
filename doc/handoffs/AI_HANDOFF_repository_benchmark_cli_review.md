# srcMove Handoff: Repository Benchmark Suite and CLI Review

## Objective

Review, run, and improve the repository benchmark workflow, with particular
attention to the terminal output and to how the standard repository set is
configured.

The desired experience is similar to the recently improved BigCloneBench CLI:
the user should understand what is running, what took time, whether work was
created or reused, what the result means, and exactly where the artifacts are.

## Start Here

Work in `srcMove/` and read:

- `AGENTS.md`
- `benchmarks/README.md`
- `benchmarks/repositories/README.md`
- `benchmarks/repositories/run_case.py`
- `benchmarks/repositories/run.py`
- `benchmarks/progress.py`
- `benchmarks/corpus.py`
- `Makefile`

Check `git status` before editing. Preserve existing user and prior-session
changes. The user handles staging and commits.

## User Intent

The user wants:

- a convenient command for the normal repository benchmark suite;
- an explicit, reviewable configuration that defines which cases are standard;
- large or unusual repositories to remain available without running by default;
- the Linux kernel as an opt-in benchmark, not part of every run;
- `wowy_advanced_analytics` excluded from the default suite because it is a
  Python project and the current srcDiff pipeline excludes `.py` files;
- clearer, calmer CLI output and final summaries;
- the next Codex session to inspect the existing design, run a representative
  benchmark, and suggest improvements rather than blindly expanding it.

Do not run every repository or clone the Linux kernel as an initial diagnostic.
Start with one small configured case. Ask before an expensive large-repository
run if it would materially consume time, storage, or network bandwidth.

## Verified Current State

The public single-case command is:

```bash
make benchmark-repo CASE=notepadpp SERIES=cli-review
```

`SERIES` groups append-only repository run indexes beneath:

```text
benchmark-data/repository-runs/<series>/
```

The apparent batch runner, `benchmarks/repositories/run.py`, does not currently
represent a real suite configuration. Its hard-coded `BENCHMARKS` list contains
only `notepadpp`. There is no Make target that runs an explicit standard set.

Repository cases currently present are:

| Case | Current state | Default-suite concern |
| --- | --- | --- |
| `notepadpp` | pinned revisions | reasonable small starting case |
| `sqlite` | pinned revisions; `src/` only | reasonable standard candidate |
| `srcMove` | pinned revisions | reasonable standard candidate |
| `srcMoveFormattingOnly` | pinned revisions | useful focused candidate |
| `opencv` | pinned revisions | large; consider opt-in |
| `zlib` | pinned revisions | revisions appear reversed (`v1.3.2` to `v1.2.3`); review before trusting |
| `wowy_advanced_analytics` | pinned revisions | Python; exclude from the default suite |
| `context_export` | no revisions | currently skips |
| `firefox` | no revisions | currently skips and is very large |

There is not yet a Linux kernel case. Do not choose arbitrary kernel revisions
or a repository subdirectory without discussing the measurement goal with the
user. A new case must use stable, pinned revisions and clearly declare whether
it compares the full tree or a selected subdirectory.

The shared snapshot implementation can now report whether a snapshot was
`created` or checksum-verified and `reused`. Reuse that shared behavior instead
of inventing repository-specific wording.

## Review Tasks

### 1. Observe the existing CLI

Run one small case through Docker, preferably `notepadpp`, using a disposable
series name. Capture and assess the complete output from repository loading
through the saved result.

Do not treat a successful tool invocation as a correctness pass. Repository
benchmarks currently have no BigCloneBench-style ground-truth oracle; they are
real-revision observations. Use terms such as `COMPLETED`, `tool failure`, and
`moves reported` accurately.

Inspect the resulting repository index, run manifest, results, and series CSV.
Check whether the terminal summary exposes the most useful recorded fields,
including:

- requested revisions and resolved commits;
- included and excluded file counts;
- whether the snapshot and srcDiff corpus were created or reused;
- srcDiff and srcMove elapsed time and peak memory when available;
- move, move-group, move-pair, annotated-region, and total-region counts;
- failure status and actionable replay/isolation commands;
- complete paths to the primary result and series summary.

Do not dump every internal content identifier into the normal output merely
because it exists in a manifest.

### 2. Design an explicit suite configuration

Replace the hard-coded batch list with one small, versioned source of truth.
Prefer a repository-native format such as JSON unless another existing format
has a compelling advantage; avoid adding a dependency only to parse config.

The design should support at least:

- a named default or `standard` suite;
- opt-in suites or tags for large repositories;
- deterministic ordering;
- validation for unknown cases, duplicates, missing `info.json`, and cases
  without configured revisions;
- an easy way to list suites and resolved members without running them;
- explicit case selection or exclusion for one-off runs;
- a shared `SERIES` name for every case in one suite invocation;
- nonzero exit status when any selected case fails, while still preserving and
  summarizing completed results.

The standard suite must be explicitly listed. Do not define it as “all folders
under `benchmarks/repositories/`,” because new heavyweight, unsupported, or
language-incompatible cases must not begin running accidentally.

Candidate CLI shapes to evaluate, not requirements to copy verbatim:

```bash
make benchmark-repos SERIES=thesis-pilot
make benchmark-repos SUITE=standard SERIES=thesis-pilot
python3 benchmarks/repositories/run.py --list
python3 benchmarks/repositories/run.py --suite large --case linux
```

Keep `make benchmark-repo CASE=...` as the clear single-case entry point unless
there is a strong reason to change it.

### 3. Improve the output

Apply the useful conventions already established for BigCloneBench:

- live progress for operations that can appear frozen;
- precise completion verbs such as `created`, `reused`, `verified`, and
  `executed`;
- no dense final wall of `key=value` lines for the human-facing command;
- a short final result block with an unambiguous status;
- a readable failure section with the next diagnostic action;
- full paths for important artifacts rather than filenames implicitly relative
  to another line;
- durable machine-readable detail retained in manifests and CSV files;
- restrained output: do not repeat the same fact in progress, summary, and
  artifact sections without a reason.

For a suite, show both per-repository results and a final aggregate such as:

```text
Repository benchmark suite: COMPLETED WITH FAILURES

  Cases:      3 completed, 1 failed, 4 selected
  Series:     thesis-pilot

  notepadpp   completed   srcDiff 12.4s   srcMove 1.8s   37 moves
  sqlite      completed   srcDiff 48.1s   srcMove 4.2s   91 moves
  opencv      failed      srcDiff SIGSEGV

Artifacts:
  Series summary: /workspace/srcMove/benchmark-data/repository-runs/.../summary.csv
```

Treat this only as a readability target. Base the final fields on what the
current manifests can support reliably.

### 4. Review measurement quality

Before declaring the default suite suitable for thesis evidence, review:

- whether each revision pair is chronological and intentional;
- whether the revision span is so large that one project dominates runtime or
  move counts;
- whether directory filters make cross-project results misleading;
- whether excluded files leave meaningful inputs;
- whether the suite mixes smoke tests, performance stress cases, and thesis
  evaluation cases without labeling those roles;
- whether repeated runs append cleanly without making `summary.csv` ambiguous.

Report these findings to the user. Fix obvious correctness or usability issues
that are clearly in scope, but do not silently redefine the scientific meaning
of a benchmark case.

## Verification

At minimum:

```bash
./bin/srcml-dev-shell make -C srcMove test-unit
```

Run the command from the workspace root. Add focused unit tests for suite
configuration validation, selection ordering, failure aggregation, and CLI
rendering. Use a small real repository benchmark only for final manual review;
unit tests must not clone repositories or require network access.

Update `benchmarks/repositories/README.md` as the canonical operational guide
after the implementation settles. Do not duplicate durable suite instructions
in this handoff or other docs.

## Deliverable

Return to the user with:

1. a concise review of the current repository benchmark process;
2. the proposed standard and opt-in suite membership, with reasons;
3. the CLI and configuration changes implemented;
4. a sample of the improved output;
5. tests and representative benchmark commands run;
6. remaining measurement-quality questions, especially Linux scope and the
   reversed zlib revisions.
