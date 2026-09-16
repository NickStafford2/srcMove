# srcMove Performance Benchmark

This component measures one or more srcMove executables repeatedly over the
same immutable, checksummed srcDiff XML inputs. It is a scalability and runtime
benchmark, not a move-detection accuracy benchmark.

- `benchmark.py` implements scheduling, measurement, and result summaries.
- `run.py` is the command-line entry point.
- `tests/` contains this component's focused unit tests.

The component uses the shared corpus, process-execution, provenance, and
storage contracts in [`benchmarks/`](../benchmarks/README.md). It does not
depend on BigMoveBench or srcMove History.

For a quick view of one execution, use `srcMove --profile` directly. For
repeatable comparative evidence, run from the srcMove repository root:

```bash
python3 performance/run.py \
  --variant baseline=/path/to/baseline/srcMove \
  --variant candidate=/path/to/candidate/srcMove \
  --corpus CORPUS_ID \
  --warmups 1 \
  --repetitions 6 \
  --seed 2026 \
  --cache-policy warm_os_cache
```

The first variant is the comparison baseline. The recorded schedule keeps
variants adjacent for each case and repetition, rotates their order, and uses
the declared seed to remain reproducible. Measured repetitions must be at least
the number of variants so each executable occupies every schedule position.

Use repeatable `--case CASE_ID` options to select accepted corpus cases. For a
small standalone experiment, replace `--corpus` with repeatable
`--input NAME=/path/to/input.srcdiff.xml` options.

Each append-only run is stored under
`benchmark-results/performance/runs/<run-id>/`:

- `run.json` records inputs, executables, provenance, policy, and schedule.
- `raw.csv` records every warmup and measured attempt, including failures.
- `summary.json` reports median/MAD measurements and paired comparisons.
- `attempts/` retains commands, bounded logs, terminal records, and failure
  evidence; successful output XML is validated and then discarded.

The runner captures external wall time, CPU time, Linux peak RSS when
available, and internal `srcMove --profile` timings. Its cache-policy value is
recorded metadata; the runner does not implicitly flush or warm operating-system
caches. A completed run retains failed measurements and exits nonzero when any
measured attempt fails.
