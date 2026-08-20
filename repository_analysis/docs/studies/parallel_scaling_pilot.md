# Preliminary Parallel Scaling Evaluation

> Superseded study: this pilot measured the retired experimental history
> runner, not the production `repository_analysis` implementation. Preserve it
> as historical evidence, but replace it with a repeated scaling study of the
> production analyzer before drawing current performance conclusions.

A preliminary scaling experiment evaluated repository-history analysis over 300 adjacent first-parent commits from SQLite. Worker counts of 1, 2, 4, 6, 8, 10, 12, and 16 were tested once each in Docker on a 16-logical-CPU Intel Core i9-9980HK system. Each run used the same commit range, executable binaries, and benchmark configuration.

| Workers | Time (s) | Speedup | Peak memory (MiB) |
|---:|---:|---:|---:|
| 1 | 291.43 | 1.00× | 269 |
| 2 | 168.99 | 1.72× | 417 |
| 4 | 124.61 | 2.34× | 708 |
| 6 | 107.40 | 2.71× | 741 |
| 8 | 107.84 | 2.70× | 761 |
| 10 | 132.89 | 2.19× | 767 |
| 12 | 106.08 | 2.75× | 882 |
| 16 | 108.00 | 2.70× | 1,056 |

Performance improved substantially up to six workers. Beyond this point, additional parallelism produced little or no reduction in wall-clock time while increasing memory consumption. Twelve workers achieved the shortest observed time, but improved on six workers by only 1.2% while using approximately 19% more memory. The anomalously slower ten-worker result indicates that repeated trials are necessary to quantify measurement variability. Overall, six workers appear to provide the best preliminary balance between throughput and resource consumption.

Of the 300 selected pairs, 135 were analyzed successfully, 149 contained no analyzable changes, and 16 consistently failed srcDiff structural validation. The same 16 pairs failed at every worker count, and all runs produced identical normalized result and configuration hashes. Thus, the failures were deterministic workload outcomes rather than concurrency-induced inconsistencies.

These results are preliminary because each worker count was measured only once. A final evaluation should use multiple repetitions, report median and dispersion, and distinguish selected-pair throughput from throughput over pairs that required complete srcDiff and srcMove analysis.

### CLI output

dev@58b83fafe8d6:/workspace/srcMove$ make history-scaling \
  CASE=sqlite \
  START=c69f996361cdaace1aa31176262d91b1ec546bea \
  COUNT=300 \
  JOBS=1,2,4,6,8,10,12,16 \
  REPETITIONS=1 \
  OFFLINE=1 \
  LABEL=sqlite-300-pilot
[1/8] measured repeat 1, jobs=6
  failed: 107.40s, 2.793 pairs/s, peak RSS 741.0 MiB
[2/8] measured repeat 1, jobs=8
  failed: 107.84s, 2.782 pairs/s, peak RSS 760.9 MiB
[3/8] measured repeat 1, jobs=12
  failed: 106.08s, 2.828 pairs/s, peak RSS 882.2 MiB
[4/8] measured repeat 1, jobs=16
  failed: 108.00s, 2.778 pairs/s, peak RSS 1055.6 MiB
[5/8] measured repeat 1, jobs=4
  failed: 124.61s, 2.408 pairs/s, peak RSS 708.4 MiB
[6/8] measured repeat 1, jobs=10
  failed: 132.89s, 2.257 pairs/s, peak RSS 767.1 MiB
[7/8] measured repeat 1, jobs=1
  failed: 291.43s, 1.029 pairs/s, peak RSS 269.1 MiB
[8/8] measured repeat 1, jobs=2
  failed: 168.99s, 1.775 pairs/s, peak RSS 416.9 MiB

History scaling study: scaling-2026-08-19T193301.276871-0000-sqlite-300-pilot-c199e721-7fca-4584-bfdd-b6679b3070a0
  Status: completed with failures
  Jobs   Median    Speedup   Efficiency   Throughput   Peak RSS
     1   insufficient successful trials
    10   insufficient successful trials
    12   insufficient successful trials
    16   insufficient successful trials
     2   insufficient successful trials
     4   insufficient successful trials
     6   insufficient successful trials
     8   insufficient successful trials
  Diminishing returns: not established
  Results equivalent: NO
  Study:   /workspace/srcMove/benchmark-data/history-scaling/scaling-2026-08-19T193301.276871-0000-sqlite-300-pilot-c199e721-7fca-4584-bfdd-b6679b3070a0/study.json
  Summary: /workspace/srcMove/benchmark-data/history-scaling/scaling-2026-08-19T193301.276871-0000-sqlite-300-pilot-c199e721-7fca-4584-bfdd-b6679b3070a0/summary.csv
make: *** [Makefile:69: history-scaling] Error 1
dev@58b83fafe8d6:/workspace/srcMove$
dev@58b83fafe8d6:/workspace/srcMove$
