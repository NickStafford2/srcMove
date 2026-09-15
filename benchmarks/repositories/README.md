# History Scaling Benchmark

This directory contains the controlled throughput benchmark for the production
[`srcmove_history`](../../srcmove_history/docs/runtime.md) analyzer. The former
two-revision repository benchmark has been retired; use `srcmove-history
compare OLD NEW` for an intentional endpoint comparison.

Reference descriptions and ignored clones live in
[`reference-repositories/`](../../reference-repositories/README.md).

## Run a scaling study

From the workspace root, run a three-repeat, 300-pair study in Docker:

```bash
./bin/srcml-dev-shell make --no-print-directory -C srcMove history-scaling \
  CASE=sqlite \
  START=<fixed-full-commit-hash> \
  COUNT=300 \
  JOBS=1,2,4,6,8,12 \
  REPETITIONS=3 \
  WARMUPS=1 \
  OFFLINE=1 \
  ENVIRONMENT_LABEL=srcml-dev:ubuntu24.04 \
  LABEL=sqlite-300-scaling
```

Use an immutable full commit hash for `START`. The runner resolves the complete
commit range and both executables once, gives every trial a fresh SQLite
analysis, rotates worker-count order deterministically, and accepts the study
only when every trial produces the same analysis definition and normalized
results.

Docker Desktop bind mounts can add filesystem overhead. Add
`SCRATCH_ROOT=/tmp` to execute each timed analysis on container-local storage
while retaining its normalized result and log. Omit it when intentionally
measuring bind-mounted I/O.

Generated studies currently live below:

```text
benchmark-data/history-scaling/<study-id>/
  study.json
  trials.csv
  summary.json
  summary.csv
  trials/<trial-id>/
    trial.json
    history.log
    data/
      analysis-result.json
      analysis/
```

Scratch-backed trials omit the non-relocatable `analysis/` directory after
recording its size. The remaining records include wall time, end-to-end commit
pair throughput, analyzed-pair throughput, CPU utilization, peak RSS, disk
usage, speedup, parallel efficiency, and a conservative scaling knee.

Treat the reported knee as evidence for the tested repository, commit window,
machine, container allocation, and tool revisions—not as a universal worker
default. Compare program revisions only in separate studies with identical
commit-list hashes and environment allocations.
