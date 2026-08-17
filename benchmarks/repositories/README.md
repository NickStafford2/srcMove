# Repository Benchmarks

These benchmarks compare two configured revisions of a real repository through
the validated srcDiff corpus and srcMove run pipeline. Each invocation saves an
append-only result automatically; the mutable `work/` directory is only a
checkout/export cache.

From the workspace root, run and save one configured case in Docker:

```bash
make benchmark-repo CASE=notepadpp REFRESH=1
```

Group related invocations into a named series:

```bash
make benchmark-repo CASE=notepadpp SERIES=thesis-pilot REFRESH=1
make benchmark-repo CASE=sqlite SERIES=thesis-pilot REFRESH=1
```

Inside `srcMove` in the Docker shell, the same `make benchmark-repo` commands
work. `REFRESH=1` explicitly permits the initial clone or a later fetch. Omit it
to reuse the cached checkout offline.

The command resolves exact commits, exports both revisions, creates or reuses an
[input snapshot](../README.md#staged-corpus-workflow) and srcDiff corpus, runs
srcMove only on admitted XML, and creates a new append-only srcMove run. It
prints the saved benchmark index and series summary. No benchmark artifacts are
copied between runs.

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

If srcDiff crashes, times out, or emits invalid archive XML, the command returns
nonzero, saves the failure, and prints exact `replay` and `isolate` commands. A
zero-move srcMove result remains a valid observation; structurally empty archive
output from srcDiff is rejected before srcMove runs.

Override revisions or refresh the cached checkout when needed:

```bash
python3 benchmarks/repositories/run_case.py notepadpp \
  --old-rev OLD \
  --new-rev NEW \
  --refresh-repo
```

`run.py` executes the small configured batch. `build_examples.py` turns selected
benchmark results into ignored example artifacts for documentation or manual
inspection.

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
