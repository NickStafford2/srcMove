# srcMove Benchmarking

Benchmarks are experiments and are intentionally separate from deterministic
correctness tests in `tests/`.

- [BigMoveBench](../bigMoveBench/README.md): srcMove's benchmark derived from
  BigCloneBench clone pairs and known false positives.
- [History scaling](../srcmove_history/benchmarks/README.md): controlled throughput measurements
  for production `srcmove_history` analyses.
- [Performance benchmark](../performance/README.md): paired/interleaved
  measurements over named, pre-existing srcDiff XML workloads that capture
  external process timings and `srcMove --profile` stage timings.

Generated benchmark storage is ignored by Git and split by purpose:

- `bigMoveBench/cache/` holds BigMoveBench inputs and intermediates: frozen
  source snapshots, srcDiff attempts, verified srcDiff corpora, generation
  batches, and compiled or selected BigCloneBench data.
- `performance/cache/workloads/` is the ignored recommended location for
  reusable performance workloads. It is independent of the BigMoveBench cache.
- `benchmark-results/` holds completed srcMove evaluations, performance runs,
  history-scaling studies, and combined-suite summaries.

A corpus is a reusable set of validated srcDiff XML inputs. A generation batch
is the resumable record of the srcDiff attempts that produced one. Neither is a
thesis result. Treat completed manifests under `benchmark-results/` and their
referenced immutable cache inputs as the authoritative result.

Dataset-oriented CLI tools expose `--cache-root` where applicable. Performance
accepts explicit `--workload NAME=PATH` values instead. Result-producing tools
use `--results-root`; Make targets use `BENCHMARK_CACHE_ROOT` and
`BENCHMARK_RESULTS_ROOT` where applicable.

The phased upgrade of reusable srcDiff data, provenance, failure incidents,
dataset adapters, and publication runs is described in the
[benchmarking upgrade plan](../doc/benchmarking_upgrade_plan.md).

## Upgrade contracts

This directory contains infrastructure shared by the independently owned
benchmark suites listed above. It does not contain a benchmark suite itself.

`contracts.py` defines the canonical content-identity encoding, shared
process/XML/provenance status vocabulary, and development/publication labels.
`execution.py` owns benchmark-attempt lifecycle and recovery;
`process_supervision.py` owns bounded logs, process groups, and resource
observation; `srcdiff_validation.py` owns structural XML admission; and
`storage.py` owns atomic JSON persistence.
`tooling.py` provides the common executable-discovery and simple command helpers
used by test and benchmark entry points.
BigMoveBench owns its source-pair, semantic-eligibility, and adapter contracts
in [`bigMoveBench/contracts.py`](../bigMoveBench/contracts.py).

Phase 0 characterization is entirely offline. Tiny source and srcDiff fixtures,
a configurable fake executable, and strict BigMoveBench oracle tests live under
`bigMoveBench/tests/`. BigCloneBench remains an external manual prerequisite;
normal tests neither download it nor depend on historical large-run counts.

The [performance benchmark](../performance/README.md) reads explicit existing
XML workloads in place and writes ignored local runs under the selected results
root. BigMoveBench owns its staged corpus workflow in
[`bigMoveBench/corpus.py`](../bigMoveBench/corpus.py).

Previously archived thesis results are historical evidence, not regression
expectations for the refactored implementation.

## Provenance foundation

`provenance.py` provides read-only collection of repository state, relevant
untracked source checksums, executable and input checksums, and a small host
environment snapshot. It validates a build receipt when one exists but never
infers that a nearby binary came from the current checkout. Binary verification
and current-checkout agreement are reported separately.

The supported CMake build writes
`<srcMove executable>.build-receipt.json` immediately after linking `srcMove`.
The receipt binds the executable checksum to the observed srcMove/srcReader
source state, workspace-lock checksum when available, compiler, configuration,
and relevant CMake options. It records tests as `not_run`; building alone is not
evidence that tests passed.

Development and publication labels are part of observation manifests, but
publication requirements are not enforced yet. Benchmark workflows record
these observations; legacy coupled runners do not. BigMoveBench's
[workflow guide](../bigMoveBench/README.md) is the canonical documentation for
its input snapshots, srcDiff corpora, resumable attempts, and evaluation runs.

## Reporting wishlist

These are desired thesis-facing outputs, not claims about fields already present
in every summary. Some underlying counts are recorded today but still need to be
calculated and presented consistently.

Highest priority:

- **Moved-region share:** report `annotated_region_count / regions_total` as a
  percentage, always alongside both counts. This answers what proportion of
  srcDiff's inserted and deleted regions srcMove classified as belonging to a
  move. Keep move-group and move-pair counts separate because they use different
  units.
- **Change composition:** report inserted regions, deleted regions, total changed
  regions, and unchanged or whitespace-only elements excluded from the
  denominator.
- **Move structure:** report one-to-one, many-region, exact, Type-2, ambiguous,
  insertion-only, deletion-only, and copy-or-repeat groups, with counts and
  percentages.
- **Move size distribution:** report moved lines or tokens per move using median,
  quartiles, range, and a small histogram. A few very large moves should not
  obscure the typical detected move.
- **Scale-normalized results:** report moves and moved regions per thousand
  changed lines or per thousand diff regions, together with files and source
  lines examined. This makes projects of different sizes comparable.
- **Per-project distributions:** retain every project/revision-pair result and
  summarize across projects with medians and quartiles. Do not rely only on one
  pooled total dominated by the largest repository.

For datasets with a trustworthy oracle, such as the controlled BigCloneBench
cases:

- report true positives, false positives, false negatives, precision, recall,
  and F1, split by Type-1 and Type-2 cases;
- report the number selected, excluded, semantically ineligible, executed, and
  successfully scored so every accuracy denominator is auditable;
- keep tuning and evaluation results separate and label them prominently.

For performance and reliability:

- report srcDiff and srcMove wall time and peak memory separately, plus srcMove
  throughput normalized by input bytes and diff-region count;
- report repeated-run medians, variability, paired deltas, and practical effect
  sizes when comparing srcMove builds;
- report srcDiff failures, invalid XML, timeouts, srcMove failures, and excluded
  files as first-class results rather than silently dropping them;
- attach workload identity to every performance table and the applicable
  dataset identity to every accuracy table, together with executable,
  configuration, environment, and source revision identifiers.
