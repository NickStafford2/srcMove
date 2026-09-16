# srcMove Performance Benchmark

This component measures one or more srcMove executables repeatedly over named,
pre-existing srcDiff XML workloads. It measures runtime and resource usage, not
move-detection accuracy.

- `benchmark.py` implements scheduling, measurement, and result summaries.
- `run.py` is the command-line entry point.
- `tests/` contains this component's focused unit tests.

The component reuses generic process-execution, provenance, atomic JSON, and
statistical utilities from [`benchmarks/`](../benchmarks/README.md). Its
workloads and local cache are independent of BigMoveBench and srcMove History.

Store reusable large XML files under the ignored
`performance/cache/workloads/` directory. This is a recommended local
location, not a CLI restriction: `--workload` accepts a file anywhere. The
runner consumes existing srcDiff XML and does not generate it from source
pairs.

For a quick view of one execution, use `srcMove --profile` directly. For
repeatable comparative evidence, run from the srcMove repository root:

```bash
python3 performance/run.py \
  --variant baseline=/path/to/baseline/srcMove \
  --variant candidate=/path/to/candidate/srcMove \
  --workload opencv=performance/cache/workloads/opencv.srcdiff.xml \
  --workload candidate-heavy=/path/to/candidate-heavy.srcdiff.xml \
  --warmups 1 \
  --repetitions 6 \
  --seed 2026 \
  --cache-policy warm_os_cache
```

The first variant is the comparison baseline. The recorded schedule keeps
variants adjacent for each workload and repetition, rotates their order, and
uses the declared seed to remain reproducible. Measured repetitions must be at
least the number of variants so each executable occupies every schedule
position. At least one explicit `--workload NAME=PATH` is required.

Each append-only run is stored under
`benchmark-results/performance/runs/<run-id>/`:

- `run.json` records each workload's resolved path, checksum, byte size, XML
  shape, XML element/unit counts, diff-region counts, executable provenance,
  policy, and schedule.
- `raw.csv` records every warmup and measured attempt, including failures.
- `summary.json` reports median/MAD measurements and paired comparisons.
- `attempts/` retains commands, bounded logs, terminal records, and failure
evidence; successful output XML is validated and then discarded.

Workload XML is read in place and is never copied into a run directory.

The runner captures external wall time, CPU time, Linux peak RSS when
available, and internal `srcMove --profile` timings. Its cache-policy value is
recorded metadata; the runner does not implicitly flush or warm operating-system
caches. A completed run retains failed measurements and exits nonzero when any
measured attempt fails.
