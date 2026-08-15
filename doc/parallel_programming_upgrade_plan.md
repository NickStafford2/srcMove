# Parallel Programming Upgrade Plan

## Status and purpose

This document is a plan, not a description of implemented behavior. The
current pipeline remains documented in [Architecture](architecture.md), and
performance experiments must follow the
[Benchmarking upgrade plan](benchmarking_upgrade_plan.md).

The goal is to reduce srcMove wall-clock time on large multi-file srcDiff
archives, especially repository-scale inputs such as OpenCV, while preserving
deterministic move detection and bounded memory use. Parallel execution should
not complicate the matching model or weaken correctness evidence merely to
improve a synthetic throughput number.

## Evidence and current constraint

Historical profiling recorded in
[`AI_HANDOFF_annotation_performance_investigation.md`](handoffs/AI_HANDOFF_annotation_performance_investigation.md)
found that XML work, not content grouping, dominated execution:

| Workload | Parse regions | Candidate filtering | Annotation | Content grouping |
| --- | ---: | ---: | ---: | ---: |
| BigCloneBench Type-1 median | 39.5% | 13.7% | 45.6% | 0.1% |
| 76 MB OpenCV srcDiff | 28.4% | negligible | 71.6% | negligible |

Those profiles measured an older three-pass implementation. Commit `3afbc86`
removed the annotation XPath-collection pass by retaining candidate XPaths from
the initial parse. The current implementation still parses the input once to
detect moves and again to write annotations. The old percentages must not be
presented as current benchmark results, but they establish two useful facts:

1. parallelizing only grouping cannot materially improve the measured large
   repository workload;
2. the current commit must be reprofiled before choosing or judging a parallel
   implementation.

A rough subtraction of the removed pass from the historical OpenCV profile
suggests a current order of magnitude near 20 seconds rather than 29 seconds,
with roughly 8 seconds in initial parsing and 12 seconds in annotation and
writing. This is an estimate for planning only.

## Goals

- Improve large multi-file archive wall-clock time by at least 2x on a declared
  8-or-more-core reference machine, with 3x as a stretch target.
- Preserve existing XML, JSON, XPath, match-selection, and move-ID behavior.
- Keep output deterministic across thread counts and repeated runs.
- Use a bounded number of worker threads and bounded in-flight memory.
- Allow hundreds or thousands of file-unit tasks without creating one thread
  per task.
- Retain a simple single-thread path for debugging, comparison, and constrained
  environments.
- Make each optimization independently measurable and reversible.

## Non-goals

- Do not create 100 operating-system threads merely because an archive has 100
  file units. Task count and worker count are separate.
- Do not parallelize content grouping first; it was negligible in the available
  large-input profile.
- Do not change exact or Type-2 matching semantics as part of this work.
- Do not make Type-3, Type-4, scoring, or ambiguous-pairing changes.
- Do not require a new heavyweight concurrency dependency without benchmarked
  evidence that the standard-library implementation is insufficient.
- Do not claim a speedup from generated microbenchmarks alone.

## Concurrency model

### Work unit

The preferred fork/join task is one archive child file unit, identified by a
stable archive ordinal. A unit task may contain many diff regions and move
candidates. This granularity is large enough to amortize scheduling overhead
and naturally exposes parallel work in repository archives.

Candidate and annotation locations should evolve from one global node index to
a stable composite identity:

```text
unit_location = (archive_unit_ordinal, unit_local_node_index)
```

The root archive wrapper is owned by the coordinator. Single-file input is one
unit and therefore has limited unit-level parallelism.

### Worker policy

Use a bounded executor backed by a fixed set of C++ threads. Hundreds of unit
tasks are acceptable; hundreds of worker threads are not.

An initial policy should be:

```text
worker_count = min(requested_workers,
                   hardware_concurrency,
                   runnable_unit_count)
```

`--threads 1` must force serial execution. During development, parallelism
should be opt-in. After the implementation is validated, `--threads 0` may mean
automatic selection. Any automatic cap must be justified by CPU, memory, and
unit-size-skew measurements rather than a hard-coded assumption.

Tasks should be claimed dynamically because archive units can differ greatly
in size. A small number of large units must not be assigned permanently to one
worker while other workers become idle. Scheduling weight should initially use
captured node count or serialized unit size.

### Target pipeline

```text
serial archive/root discovery
             |
             v
bounded unit capture or dispatch
             |
             v
fork: prepare candidates for file units
             |
             v
join in archive order
             |
             v
serial global registry and move-group selection
             |
             v
build immutable annotation plan
             |
             v
fork: annotate/serialize file units
             |
             v
join serialized units in original archive order
             |
             v
atomic output publication
```

Cross-file move detection is preserved because all unit-local candidates join
into one global registry before the annotation plan is created.

## Design requirements

### Determinism

Parallel completion order must never define observable output order.

- Merge candidate vectors by archive ordinal and local source order.
- Assign candidate IDs only after that ordered merge.
- Keep exact-before-Type-2 selection and current overlap-suppression order.
- Generate move IDs on the coordinator after group order is final.
- Emit annotated units in original archive order.
- Propagate worker exceptions deterministically and cancel outstanding work.

The current UUID counter and profiling collector are not thread-safe. They
should remain coordinator-owned rather than gaining locks in worker hot paths.

### XML ownership

Each worker that invokes libxml or srcReader must own its reader, writer, and
associated document state. A `srcml_reader`, iterator, or libxml document must
not be shared concurrently.

The implementation must explicitly preserve namespace context when a child
unit is processed separately from the archive root. It must also preserve the
current XPath rules and output formatting expected by regression fixtures.

### Memory and backpressure

Retaining every parsed node could eliminate the second XML parse, but a 76 MB
XML file may expand to several times that size as C++ objects. This tradeoff
must be measured before it becomes the design.

Use a bounded queue or bounded number of retained units. If ordered output is
waiting for one slow early unit, later completed units must not accumulate
without limit. If spilling is necessary, use validated temporary files and
clean them after successful or failed execution.

The design must avoid memory growth proportional to
`worker_count * archive_size`. Peak RSS is a first-class benchmark result, not
an afterthought.

## Staged implementation

### Phase 0: establish the current baseline

Prepare immutable, checksummed srcDiff inputs through the benchmarking plan.
At minimum, use:

- the same large OpenCV corpus or an equivalently documented repository
  archive;
- a candidate-heavy archive, because the historical OpenCV input had almost no
  grouping work;
- representative small regression and BigCloneBench inputs.

Record input bytes, archive-unit count and size distribution, region and
candidate counts, wall time, CPU time, peak RSS, output checksum, build receipt,
and per-stage profiler values. Run enough repetitions to report a median and
variation rather than one favorable result.

**Decision gate:** do not start archive parallelization without a reproducible
current baseline.

### Phase 1: remove avoidable serial work

Before adding threads:

1. gate `print_greedy_matches(...)` behind an explicit diagnostic option;
2. measure the remaining XPath cost for tagged nodes during annotation writing;
   untagged nodes are already copied without requesting their XPath;
3. if that cost is material, reuse the XPath already retained by each candidate
   when materializing move summaries, or prototype a lightweight annotation-reader
   mode;
4. remove repeated temporary `vector<srcml_node>` copies during
   canonicalization;
5. compute exact and Type-2 canonical forms in one traversal when practical.

These changes simplify later worker tasks and may reduce the serial fraction
enough to alter the parallel design.

**Decision gate:** reprofile. If the large archive already meets the performance
target, stop rather than adding concurrency for its own sake.

### Phase 2: isolate pure candidate preparation

Create one testable operation that accepts immutable captured region or unit
data and returns owned candidate results. It must not mutate the global
registry, allocate move IDs, write profile entries, or access a shared reader.

First run this operation serially and require unchanged regression output. Then
execute it with the bounded worker pool and merge results in input order.

This phase provides a low-risk concurrency foundation, although historical
evidence predicts only a small OpenCV speedup from candidate work alone.

**Decision gate:** retain the parallel path only if it improves a candidate-heavy
workload without material small-input or memory regression.

### Phase 3: prototype unit retention versus unit replay

The remaining annotation pass cannot be removed until the complete move plan is
known. Compare two bounded designs:

1. **Retained compact units:** keep a compact token representation from the
   first parse, then annotate it after grouping. This avoids reparsing but uses
   more memory.
2. **Replayable units:** capture or index standalone unit fragments, then let
   workers reparse them after grouping. This reduces retained object memory but
   repeats parsing and may require temporary storage.

Do not use naive byte scanning to split XML. Encodings, entities, namespaces,
and quoted delimiters require XML-aware boundaries.

Measure wall time, CPU time, peak RSS, temporary bytes, and output equivalence
for both designs.

**Decision gate:** select a representation only if it improves the large-input
wall time while staying within an explicit memory budget.

### Phase 4: parallel unit annotation and ordered assembly

Build an immutable annotation plan keyed by `unit_location`. Each worker
annotates one unit using only that plan and unit-owned XML state. Completed
units are returned or staged with their archive ordinal.

The coordinator writes the archive root, consumes completed unit outputs in
ordinal order, writes the archive end, and atomically publishes the completed
file. A failed task must not leave an apparently valid partial destination.

Single-file inputs should continue through the same semantics without paying
for unnecessary worker setup.

**Decision gate:** require at least a 2x wall-clock improvement on the declared
large reference archive before making automatic parallel execution the default.

### Phase 5: tune and document automatic behavior

Benchmark `--threads 1`, `2`, `4`, `8`, and the reference machine's hardware
limit. Include highly skewed archives and archives with fewer units than
workers. Choose defaults from the throughput/RSS curve.

Document:

- thread-count semantics;
- memory implications;
- single-file limitations;
- benchmark machine and corpus;
- observed scaling rather than theoretical core-count claims.

## Verification

### Correctness

- Run all XML and source regression suites with one and multiple threads.
- Require identical XML and JSON outputs across thread counts.
- Repeat parallel runs to detect nondeterministic move IDs or ordering.
- Cover cross-file moves, pre-marked moves, malformed XML, empty archives,
  single-unit archives, and one very large unit.
- Add fault-injection coverage for a worker failure and output cleanup.

### Concurrency safety

- Run ThreadSanitizer in the Docker/Linux build where dependencies support it.
- Confirm that readers, writers, UUID generation, profile collection, and
  registry mutation have explicit single-owner boundaries.
- Test cancellation and exception propagation without deadlock.
- Test worker counts larger than unit counts without creating excess threads.

### Performance

- Compare the same binary configuration and checksummed input for every thread
  count.
- Report wall time, aggregate CPU time, peak RSS, output size, and checksums.
- Separate warm-cache and cold-cache experiments when filesystem effects
  matter.
- Profile stage timings; total speedup alone cannot identify whether work moved
  or memory usage became unacceptable.
- Run small inputs to quantify startup and scheduling overhead.

## Expected results

These are planning estimates, not claims:

- candidate-only fork/join: little or no improvement for the historical OpenCV
  workload;
- lightweight annotation reading and canonicalization cleanup: potentially
  useful even with one thread, but currently unmeasured;
- full archive-unit candidate preparation and annotation: plausibly 2x to 4x
  on an 8-to-16-core machine when units are sufficiently numerous and balanced;
- 100 worker threads: unlikely to help and likely to increase contention and
  memory use;
- 100 or more queued unit tasks on a bounded worker pool: reasonable.

Amdahl's law remains the governing limit. With 80% parallel work, the ideal
speedup is about 3.3x on eight workers and cannot exceed 5x at any worker count.
With 90% parallel work, the ideal speedup is about 4.7x on eight workers and
cannot exceed 10x. Actual speedup will be lower because of XML I/O, allocation,
scheduling, ordered assembly, and unit-size skew.

## Completion criteria

The upgrade is complete when:

- current single-thread and parallel results are demonstrably equivalent;
- the implementation uses a bounded worker pool rather than one thread per
  task;
- the chosen large reference archive improves by at least 2x on the declared
  reference machine;
- peak memory remains within a documented and justified bound;
- failures do not publish partial output;
- benchmark artifacts bind input, binary, source, machine, and thread count;
- current architecture and user-facing CLI documentation describe the final
  implemented behavior without duplicating this plan.
