# srcMove Benchmarking

Benchmarks are experiments and are separate from the deterministic correctness
tests in [`tests/`](../tests/README.md).

- [BigMoveBench](../bigMoveBench/README.md) measures detection and
  classification on synthetic moves derived from BigCloneBench relationships.
- [Performance](../performance/README.md) compares srcMove executables over
  fixed, pre-existing srcDiff XML workloads.
- [Move selection](../moveSelectionBench/README.md) characterizes competing
  parent/child explanations, nesting, common ownership, and ambiguity.
- [History scaling](../srcmove_history/benchmarks/README.md) measures production
  `srcmove_history` throughput.

Each suite owns its methodology, commands, and output schema. Results from the
four suites answer different questions and must not be combined into one score.
BigMoveBench data is not a runtime benchmark, and repository-history move counts
are not accuracy measurements without an independent oracle.

## Shared infrastructure

This directory provides the small set of contracts reused by the benchmark
suites:

- `execution.py`: attempt lifecycle, process supervision, and recovery
- `provenance.py`: source, executable, build-receipt, and environment evidence
- `srcdiff_validation.py`: structural admission of srcDiff XML
- `identity.py`: deterministic content encoding and identifiers
- `statistics.py`: shared summary calculations
- `storage.py`: atomic JSON persistence
- `tooling.py`: executable discovery and command helpers

BigMoveBench owns its dataset compilation, selection, synthetic conversion,
case database, semantic eligibility, oracle, execution journal, and reports.
The performance runner owns its workload schedule and paired measurements.
History scaling owns its repository-analysis workloads.

## Storage and provenance

Generated data is ignored by Git:

- `bigMoveBench/cache/` stores compiled BigCloneBench evidence, selections,
  generated objects, benchmark-case databases, and the optional development
  srcDiff cache.
- `performance/cache/workloads/` is the recommended local location for reusable
  srcDiff XML performance inputs.
- `benchmark-results/` stores append-only BigMoveBench, performance, and history
  results.

Result-producing tools record executable and input identities. A build receipt
can bind a binary to observed source state; a path, nearby checkout, or version
string alone cannot. Development caches and historical runs retain their
declared limitations and must not be promoted silently to thesis evidence.

## Reporting and interpretation

Every reported result should make its population, unit, denominator, selection
policy, exclusions, tool revisions, and artifact identity explicit.

- BigMoveBench reports selected, excluded, srcDiff-ineligible, executed, and
  scored cases separately. Detection and classification are distinct outcomes,
  and positive and known-false-positive results are not combined.
- Repository evaluation reports exact revisions, selected scope, file and byte
  inventory, exclusions, tool failures, resource use, and observed move counts.
  Move counts alone do not establish accuracy.
- Performance comparisons retain raw observations and failures as well as
  summaries. Use checksummed workloads, warmups, repeated measurements,
  paired/interleaved execution, median and dispersion, wall and CPU time, peak
  RSS, and recorded cache and machine conditions.

Preserve upstream srcDiff failures and semantic ineligibility instead of
reclassifying them as srcMove misses. Preserve timeouts and failed measurements
as data instead of silently dropping them from denominators.

For current commands and interpretation rules, use the suite documentation
linked above. Large benchmark executions are never started by the normal test
runner.
