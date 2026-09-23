# Parallel Programming Upgrade Plan

## Status

This is a dormant design for large multi-file srcDiff archives. It is not an
active BigMoveBench project and does not describe implemented behavior. The
current serial pipeline is documented in [Architecture](architecture.md).

Reopen this plan only when profiling a current large archive shows that
archive-level concurrency is likely to provide a useful improvement after
accounting for memory, XML I/O, and the remaining serial work.

## Goal and scope

The goal is to reduce srcMove wall time on archives containing many file units
while preserving deterministic move selection and bounded memory. The design
does not target single-file startup cost, change matching semantics, or create
one worker per file.

Success requires:

- identical XML and JSON behavior across worker counts;
- stable move IDs, candidate ordering, and partner XPaths;
- a bounded worker pool and bounded in-flight data;
- clean cancellation without publishing partial output;
- an explicit peak-memory limit; and
- at least a 2x measured improvement on a declared multi-file workload before
  automatic parallel execution is considered.

## Work unit and ownership

The preferred task is one archive child file unit identified by a stable archive
ordinal. Candidate and annotation locations would use a composite identity:

```text
(archive_unit_ordinal, unit_local_node_index)
```

Workers may prepare or annotate file units, but the coordinator owns global
candidate ordering, group selection, move-ID generation, and final publication.
Cross-file moves remain possible because unit-local candidates join one global
registry before matching.

Every worker invoking libxml or srcReader must own its reader, writer, and
document state. Readers, iterators, and libxml documents must not be shared
concurrently. Audit srcReader for mutable process-global state before enabling
parallel readers or writers.

Generic archive-unit capture and fragment serialization belong in srcReader.
srcMove owns scheduling, matching barriers, annotation plans, cancellation, and
ordered publication. Do not copy srcReader's XML serializer into srcMove.

## Deterministic pipeline

```text
serial archive discovery
        -> bounded unit capture or dispatch
        -> parallel candidate preparation
        -> ordered merge by archive ordinal and local source order
        -> serial global group selection and move-ID assignment
        -> immutable annotation plan
        -> parallel unit annotation or serialization
        -> ordered archive assembly
        -> atomic publication
```

Parallel completion order must never determine visible output. Exceptions and
cancellation must also be propagated deterministically. Profiling collectors
and move-ID generation should remain coordinator-owned rather than adding locks
to worker hot paths.

## Memory and backpressure

Avoid memory growth proportional to `worker_count * archive_size`. Retaining a
parsed archive could eliminate reparsing but may multiply the input size in
memory. Compare two bounded representations before choosing:

1. retained compact units, which avoid reparsing at a higher memory cost; and
2. replayable unit fragments, which reduce retained objects but repeat parsing
   and may require temporary storage.

Use a bounded queue. If an early slow unit delays ordered output, later completed
units must not accumulate without limit. Any temporary spill files must be
validated and cleaned after both success and failure. XML-aware capture is
required; naive byte splitting is unsafe around namespaces, encodings, entities,
and quoted delimiters.

## Staged decision gates

### 1. Establish a current baseline

Measure a checksummed multi-file archive and a candidate-heavy archive with the
current performance runner. Record archive-unit distribution, input bytes,
regions, candidates, wall and CPU time, peak RSS, stage timings, output hashes,
and build provenance. Also measure small inputs to quantify scheduling overhead.

Stop if the current implementation already meets the practical target.

### 2. Isolate unit-local candidate preparation

Define a serial operation that accepts immutable unit data and returns owned
candidates without mutating the registry, allocating move IDs, or sharing a
reader. Require unchanged regression output before running it through a bounded
worker pool and merging by input order.

Keep this path only if it helps a candidate-heavy archive without a material
small-input or memory regression.

### 3. Add srcReader unit capture and fragment writing

Implement the smallest general srcReader interface needed to capture and write
one archive child while preserving inherited namespaces. First run capture,
annotation, fragment serialization, and ordered assembly with one worker.
Require equivalent XML and JSON on single-unit, multi-unit, cross-file, nested
diff, and malformed-input fixtures.

Do not parallelize annotation until one-worker assembly is correct and one of
the bounded representations improves large-input time within the memory budget.

### 4. Parallelize annotation and ordered assembly

Build an immutable annotation plan keyed by composite unit location. Workers
annotate units using unit-owned XML state; the coordinator consumes outputs in
ordinal order and atomically publishes the complete archive.

Benchmark worker counts 1, 2, 4, 8, and the reference machine's useful limit.
Include skewed archives and archives with fewer units than workers. Choose any
default from the measured throughput/RSS curve rather than core count alone.

## Verification

- Run all correctness suites with serial and parallel configurations.
- Compare XML and JSON outputs byte-for-byte where formatting is contractual.
- Repeat runs to expose nondeterministic IDs or ordering.
- Cover cross-file moves, namespaces, pre-marked moves, empty and malformed
  archives, one very large unit, and worker failures.
- Use ThreadSanitizer where the dependency stack supports it.
- Report wall time, CPU time, peak RSS, temporary bytes, checksums, and stage
  timings for each worker count.

Do not promise linear scaling. The serial matching barrier, XML I/O, allocation,
ordered assembly, and unit-size skew limit the attainable speedup.
