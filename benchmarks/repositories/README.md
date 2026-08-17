# Repository Benchmarks

These benchmarks compare two configured revisions of a real repository, run
`srcdiff`, then run `srcMove`. Each case directory contains an `info.json`; its
generated checkout, exports, XML, results, and timing report live under the
ignored `work/` directory.

Run one case from the repository root:

```bash
python3 benchmarks/repositories/run_case.py notepadpp --refresh-repo
```

`--refresh-repo` explicitly permits the initial clone or a later fetch. Without
it, the runner uses an existing cached checkout offline and fails clearly when
the cache is absent.

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

## Staged workflow

For reusable measurements, prepare already-exported revision trees as an
immutable input snapshot:

```bash
python3 benchmarks/pipeline.py prepare \
  --case-id my-repository-case \
  --original /path/to/old/export \
  --modified /path/to/new/export \
  --source-json '{"repository":"URL","old":"COMMIT","new":"COMMIT"}'
```

Filters are non-destructive and part of the preparation identity. For the
current srcDiff Python limitation, add `--exclude-suffix .py`; the manifest
records every excluded path and the original export remains unchanged.

The command prints a preparation identifier. Generate a reusable srcDiff corpus
from it:

```bash
python3 benchmarks/pipeline.py generate PREPARATION_ID \
  --srcdiff /path/to/srcdiff \
  --timeout 1800
```

Generation writes a terminal attempt record even when srcDiff exits nonzero,
receives a signal, times out, omits output, or emits invalid XML. Only admitted
XML appears below `benchmark-data/corpora/`.

Generation is resumable. The same command skips terminal cases already present
in its checkpoint. Retry all failed cases, or selected failures, with:

```bash
python3 benchmarks/pipeline.py generate PREPARATION_ID \
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

`run_case.py` remains the legacy coupled clone/export/srcdiff/srcMove interface.
It is retained for compatibility while repository checkout/export automation is
migrated onto the staged workflow.
