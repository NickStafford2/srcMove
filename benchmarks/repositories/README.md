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

Do not use `--depth`: srcMove History rejects shallow repositories. A history
study should use commit-to-parent edges rather than treating the kernel's
merge-heavy first-parent chain as individual patch history.

`wowy_advanced_analytics` is excluded from every suite because it is Python and
the current snapshot pipeline excludes `.py` files. `zlib` is also excluded:
its current configuration runs backward from `v1.3.2` to `v1.2.3` and must not
be used until the intended comparison is confirmed. `context_export` and
`firefox` remain unavailable because they have no pinned revisions.

`build_examples.py` turns selected benchmark results into ignored example
artifacts for documentation or manual inspection.

## srcMove History scaling studies

[`benchmark_history_scaling.py`](benchmark_history_scaling.py) measures the
production [`srcmove_history`](../../srcmove_history/docs/runtime.md) runtime
across a fixed set of worker counts. It resolves the commit range and both tool
executables once, runs every trial against a fresh SQLite analysis, rotates
job-count order deterministically, and rejects a study as successful if
normalized results or analysis definitions differ between trials.

From the workspace root, run a three-repeat, 300-pair scaling study in Docker:

```bash
./bin/srcml-dev-shell make --no-print-directory -C srcMove history-scaling \
  CASE=sqlite \
  START=c69f996361cdaace1aa31176262d91b1ec546bea \
  COUNT=300 \
  JOBS=1,2,4,6,8,10,12,16 \
  REPETITIONS=3 \
  OFFLINE=1 \
  ENVIRONMENT_LABEL=srcml-dev:ubuntu24.04 \
  LABEL=sqlite-300-scaling
```

Docker Desktop bind mounts can add filesystem overhead. To keep the study and
final reports durable on the host while executing each timed trial on
container-local storage, add:

```bash
  SCRATCH_ROOT=/tmp
```

The scaling coordinator creates a private directory per trial, excludes report
promotion time from the benchmark wall time, promotes the portable normalized
result and logs, records the promotion duration, and removes the non-relocatable
scratch analysis. `SCRATCH_ROOT` must name an existing, non-symbolic-link
directory. Omit it to retain each SQLite analysis and measure normal bind-mounted
I/O. `WARMUPS=1` runs one unmeasured trial at every worker count; it is
deliberately off by default because a complete warmup sweep can be expensive.

The study observes Git revisions and dirty source state, exact srcDiff/srcMove
binary checksums and build-receipt status, runner checksums, CPU model/count,
memory, cgroup limits, kernel, and Python/Git versions. Docker does not expose
its image tag inside the container, so use `ENVIRONMENT_LABEL` to record the
image or Docker Desktop allocation name used for the study.

Generated studies live below:

```text
benchmark-data/history-scaling/<study-id>/
  study.json                 frozen workload, schedule, provenance, status
  trials.csv                 one row per raw warmup or measured trial
  summary.json               medians, MAD, speedup, efficiency, scaling knee
  summary.csv                spreadsheet-friendly per-job summary
  trials/<trial-id>/
    trial.json               command, timing, CPU, peak RSS, result hash
    history.log              complete srcMove History output
    data/
      analysis-result.json   portable normalized outcomes and fingerprints
      analysis/              SQLite state; omitted for scratch-backed trials
```

The reported knee is conservative: it identifies the worker count before two
consecutive job-count increases both improve median wall time by less than the
configured threshold (10% by default). Treat it as evidence for the tested
machine and workload, not as a universal default. Compare program revisions in
separate studies with the same commit-list hash and environment allocation so
algorithm changes are not confused with worker scaling.

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
