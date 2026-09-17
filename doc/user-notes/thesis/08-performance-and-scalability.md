# Chapter 8: Performance and Scalability

> Draft status: first-pass thesis prose and experimental plan. The measurement
> infrastructure described here is implemented, but this draft reports no
> benchmark results. Hypotheses are explicitly prospective and must not be
> rewritten as findings until the frozen studies are complete.

## 8.1 Contribution and scope

Correct move classification is only one requirement for applying srcMove to
real software changes. The detector must also process useful srcDiff workloads
at an acceptable cost, and the history analyzer must apply the toolchain across
many commit pairs without sacrificing result identity or recovery. This chapter
separates those two performance questions:

1. **Core srcMove cost:** runtime, resource use, and internal phase costs when
   one srcMove executable processes a fixed srcDiff XML workload.
2. **History-analysis scalability:** end-to-end throughput and resource use
   when bounded workers execute Git materialization, srcDiff, srcMove, and
   persistence across a fixed commit-pair window.

These experiments have different units and include different systems. A core
benchmark isolates srcMove after srcDiff XML already exists. A history-scaling
trial includes repository traversal and materialization, srcDiff execution,
srcMove execution, coordination, and durable publication. Combining their
times into one performance claim would obscure the source of cost.

The contribution of the performance work is therefore both empirical and
methodological. The repository contains repeatable runners that record workload
and executable identity, retain failed attempts, and summarize repeated
measurements. Final claims must remain limited to the frozen workloads,
machines, container allocation, cache policy, and tool revisions used in those
runs.

## 8.2 Performance questions and hypotheses

The chapter asks:

- What wall-time, CPU-time, and peak-memory cost does srcMove incur on selected
  immutable srcDiff XML workloads?
- How is internally measured time distributed among the stages exposed by
  `srcMove --profile`?
- How variable are repeated executions, and what paired change is observed
  between explicitly named program revisions?
- How does end-to-end srcMove History throughput change as bounded worker count
  increases on a fixed repository window?
- Which measured resources or stages are associated with the point at which
  additional workers stop providing useful speedup?

The implementation suggests hypotheses, but does not prove them. Indexed exact
matching and cached canonical forms are expected to reduce repeated comparison
work. Size-window pruning and early-exit similarity checks are expected to be
most valuable when an input contains many plausible Type-3 candidates.
Streaming or bounded processing is expected to limit avoidable memory growth.
In history analysis, additional workers are expected to improve throughput only
until CPU, memory, filesystem, process-startup, or Docker resource contention
dominates.

Each hypothesis must be tied to a measurable comparison. A phase breakdown can
show where measured time was spent, but does not by itself establish why an
optimization helped. Likewise, a throughput plateau can identify a scaling
knee in one environment but cannot identify its cause without supporting CPU,
memory, disk, or profiling evidence.

## 8.3 Core benchmark infrastructure

The core performance component repeatedly executes one or more named srcMove
binaries over named, pre-existing srcDiff XML files. It measures performance,
not move-detection accuracy, and it does not generate source pairs or srcDiff
workloads. This boundary keeps workload construction separate from timed
execution and allows the same bytes to be reused across variants.

A run requires at least one explicit `NAME=PATH` workload and identifies each
executable variant by name. The first variant is the comparison baseline. For
each workload and measured repetition, the schedule keeps variants adjacent,
rotates their order, and records the seed used to construct that schedule.
Measured repetitions must be at least the number of variants so each executable
occupies every schedule position. This paired, interleaved design reduces—but
does not eliminate—bias from temporal drift and schedule position.

The runner records the resolved workload path, SHA-256 checksum, byte size, XML
shape, XML element and unit counts, diff-region counts, executable provenance,
declared cache policy, and complete schedule. Each attempt records external wall
time, CPU time, Linux peak RSS where available, and internal timings emitted by
`srcMove --profile`. Successful XML output is validated and discarded; bounded
logs and terminal records are retained. Failed warmups and measurements remain
part of the append-only evidence, and a run exits nonzero if any measured
attempt fails.

Completed run directories contain a manifest, raw attempt table, statistical
summary, paired comparisons, and per-attempt evidence. Summary statistics use
medians and median absolute deviations rather than selecting the fastest run.
The cache-policy field is declared metadata: the runner does not secretly flush
or warm operating-system caches. The experimental procedure must therefore say
how the chosen policy was realized and avoid claiming a cold-cache or warm-cache
condition merely because of its label.

## 8.4 Core srcMove experiment

### 8.4.1 Workload selection

The workload suite should exercise dimensions that affect candidate generation
and comparison, rather than representing size with input bytes alone. For each
immutable srcDiff XML file, record:

- checksum and byte size;
- archive or single-unit shape;
- file-unit and XML-element counts;
- deletion and insertion region counts;
- eligible candidate counts, if available;
- distribution of region sizes;
- observed match-kind counts; and
- a declared measure of Type-3 opportunity or candidate density.

Include ordinary project-derived inputs and at least one intentionally
candidate-heavy input if such a workload can be constructed without using the
final evaluation results for tuning. The suite should span small inputs useful
for startup-cost observation and larger inputs that exercise matching and XML
output. Workload selection must occur before comparative results are inspected.

> **Workload-table placeholder.** Insert stable workload names, provenance,
> checksums, structural counts, selection rationale, and whether each workload
> was used during optimization. Separate tuning workloads from final evaluation
> workloads.

### 8.4.2 Variants and procedure

For a single-version characterization, execute one frozen srcMove binary after
declared warmups for at least `[REPETITIONS TODO]` measured repetitions. For a
revision comparison, identify the baseline and candidate by commit and binary
digest, use an identical workload set and environment, and preserve the
interleaved schedule. Do not compare summaries from independent runs that used
different workload bytes or environment allocations as though they were
paired measurements.

Record the host processor, memory, operating system, container image and
resource allocation, filesystem location, compiler and build mode, srcMove and
dependency revisions, runner revision, cache policy, warmup count, repetition
count, and schedule seed. Background-load controls should be documented rather
than assumed.

### 8.4.3 Measures

For each workload and variant, report external wall time, CPU time, peak RSS
when available, and throughput normalized by both input bytes and diff-region
count. Report internal phase timings using the exact phase names emitted by the
frozen executable. If the sum of internal phases differs from external wall
time, present the difference rather than assigning it to an undocumented stage.

Comparative tables should report paired changes for each repetition as well as
variant-level medians and variability. A speedup ratio must state its direction
and denominator. Memory values unavailable on a platform should be marked
missing, not treated as zero.

## 8.5 History-scaling infrastructure

The history-scaling runner invokes the production srcMove History analyzer; it
does not maintain a second history execution model. Before trials begin, it
resolves the complete commit range and the exact srcDiff and srcMove
executables. Each timed trial receives a fresh SQLite analysis. Worker-count
order rotates deterministically, and a study is accepted only when every trial
produces the same analysis definition and normalized results.

The generated evidence records each trial, its history log, normalized analysis
result, wall time, end-to-end commit-pair throughput, successfully analyzed-pair
throughput, CPU utilization, peak RSS, disk usage, speedup, parallel efficiency,
and a conservatively selected scaling knee. When scratch execution uses
container-local storage, the non-relocatable analysis directory may be omitted
after its size is recorded; the normalized result and log remain.

Filesystem placement is an experimental factor. Docker Desktop bind mounts can
add overhead, while container-local temporary storage measures a different I/O
path. The study should either hold placement constant or run clearly separated
conditions. It must not generalize a container-local result to bind-mounted
execution without measurement.

## 8.6 History-scaling experiment

### 8.6.1 Frozen study definition

Select `[REPOSITORY TODO]` at full immutable commit
`[START COMMIT TODO]` and freeze an exact `[PAIR COUNT TODO]` first-parent
window. Record its commit-list hash, source exclusions, srcDiff/srcMove digests,
srcMove History and benchmark-runner revisions, timeouts, Docker image and
allocation, host hardware, filesystem placement, and environment label.

Use the worker sequence `[WORKER COUNTS TODO]`, `[WARMUPS TODO]` warmups, and
`[REPETITIONS TODO]` measured repetitions. The sequence should include one
worker as the speedup baseline and extend far enough to observe either a stable
plateau or the largest worker count justified by the machine's resources.
Worker-count order must follow the runner's deterministic rotation rather than
always increasing from one.

### 8.6.2 Correctness gate

Performance results are comparable only if all trials analyze the same study
and publish the same normalized outcomes. Reject or separately investigate a
trial if its analysis definition, commit-list identity, coverage, outcome
counts, exclusions, or normalized move evidence differs. Failed commit pairs
may be a reproducible part of a frozen study, but they must be identical across
worker counts and reported explicitly; otherwise throughput differences may be
caused by different work rather than parallelism.

### 8.6.3 Measures and scaling knee

Report total wall time, covered commit-pair throughput, successfully compared
pair throughput, CPU utilization, peak RSS, retained disk use, and cumulative
srcDiff/srcMove work where available. Define speedup relative to the one-worker
median:

\[
S_p = \frac{T_1}{T_p}
\]

and parallel efficiency as:

\[
E_p = \frac{S_p}{p}.
\]

The scaling knee must use the benchmark runner's documented conservative rule
or another rule fixed before inspecting the final data. It describes the tested
repository, window, environment, and tool revisions. It is not a universal
default for `--jobs`, because another repository or storage path may shift the
bottleneck.

## 8.7 Results

No performance results are asserted in this draft.

> **Results placeholder A — core characterization.** For each workload, insert
> the median and MAD for wall time, CPU time, peak RSS, byte throughput,
> region throughput, and internal phases. Include attempt counts and failures.

> **Results placeholder B — revision comparison.** Insert paired wall-time,
> memory, and phase changes for each baseline/candidate pair. Report binary
> digests and confidence or uncertainty summaries appropriate to the final
> design. Do not call a change an optimization unless accuracy/equivalence is
> established separately.

> **Results placeholder C — history scaling.** Insert wall time, both throughput
> definitions, CPU utilization, peak RSS, disk use, speedup, and efficiency for
> every worker count. Show all repetitions or their distribution, identify the
> prespecified knee, and state whether the normalized-result gate passed.

The core and history results should appear in separate tables and figures. A
phase-time chart for srcMove cannot explain the Git or srcDiff costs present in
history analysis, while end-to-end history throughput cannot isolate the cost
of the move detector.

## 8.8 Bottleneck analysis

Bottleneck claims require direct evidence. Core candidates include XML parsing
and writing, filtering, exact-match indexing, canonicalization, candidate
volume, and bounded-similarity comparisons. History candidates include Git
object access, tree materialization, native process startup, srcDiff work,
srcMove work, SQLite publication, filesystem latency, CPU saturation, and
memory pressure.

The final analysis should triangulate external measurements, internal profile
stages, per-pair work totals, CPU utilization, peak memory, and scaling shape.
For example, declining parallel efficiency accompanied by saturated CPU is
consistent with a CPU limit; declining efficiency with low CPU but increasing
wall time may justify investigating storage or serialization. These patterns
remain hypotheses unless the relevant resource is measured. Avoid assigning a
plateau to Docker, SQLite, or Type-3 matching solely because each is a plausible
cause.

| Observation | Required supporting evidence | Permitted interpretation |
| --- | --- | --- |
| One srcMove phase dominates | Frozen `--profile` output across repetitions | The phase dominates measured internal time on those workloads |
| Candidate-heavy workload grows disproportionately | Candidate counts plus wall/phase measurements | Candidate structure is associated with higher observed cost |
| History speedup plateaus | Repeated wall time, throughput, CPU, memory, and I/O context | A tested environment-specific scaling knee exists |
| Peak RSS rises with workers | Comparable normalized results and per-trial RSS | Additional concurrency increased measured process-tree memory |

## 8.9 Threats to validity and limitations

Performance is sensitive to input composition, machine architecture,
filesystem, operating system, compiler, container limits, cache state, and
background activity. A small workload suite may not represent the candidate
structure of other projects. Repeated execution reduces random noise but does
not remove systematic bias from thermal behavior, shared-host contention, or
an unmodeled cache condition.

Internal profile stages measure only code instrumented by srcMove and may omit
startup, scheduling, allocator, kernel, and output-validation costs. Linux peak
RSS may be unavailable elsewhere and does not describe the lifetime allocation
profile. Docker bind-mount measurements include a storage path that may differ
substantially from native Linux or container-local storage.

History scaling is further conditioned on one repository window and its mix of
successful, skipped, and failed pairs. Commit pairs vary widely in changed-file
count and diff complexity; pair throughput is therefore a useful end-to-end
measure but not a constant unit of computational work. The observed scaling
knee is a local operating point, not an asymptotic complexity result or a
universal worker recommendation.

Finally, faster execution does not establish equal detection behavior. Any
comparison between srcMove revisions must pair performance evidence with a
separate equivalence or accuracy check over appropriate test and evaluation
artifacts.

## Evidence still required

- [ ] Freeze tuning and final core workload sets with checksums and provenance.
- [ ] Freeze baseline/candidate binary identities and equivalence criteria.
- [ ] Record the full core benchmark environment and schedule.
- [ ] Execute repeated core measurements and retain the append-only run data.
- [ ] Freeze the history repository, start commit, pair window, worker sequence,
  storage condition, and environment.
- [ ] Execute the history-scaling study and confirm normalized-result identity.
- [ ] Replace results placeholders with tables, distributions, and artifact
  links.
- [ ] Support every bottleneck interpretation with measured evidence or label
  it as a hypothesis.

Canonical entry points are the
[srcMove performance benchmark](../../../performance/README.md) and the
[history-scaling benchmark guide](../../../srcmove_history/benchmarks/README.md).
