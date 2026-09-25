# Performance Optimization Status and Opportunities

## Purpose

This document records the current optimization state and the remaining ideas
worth revisiting. It is not an active implementation plan and does not claim
that an unmeasured change will improve performance.

Three performance questions must remain separate:

1. BigMoveBench throughput across many independent cases;
2. latency for the small file pairs common in srcMove History; and
3. srcMove time and memory on large multi-file srcDiff archives.

Use the [performance runner](../performance/README.md) to compare srcMove
builds. BigMoveBench is an accuracy workload with useful operational timings,
not a substitute for fixed performance workloads.

## Current state

The 2026 refactor removed the avoidable costs identified by the initial
profiles:

- candidate construction and the matching representations are built during one
  streaming pass;
- exact, Type-2, and Type-3 representations share incremental parsing work;
- group-selection keys and canonical forms are cached rather than repeatedly
  recomputed;
- candidate-owned XPaths eliminate the former annotation XPath-collection pass;
- `--results-only` skips annotated-XML serialization when JSON evidence is the
  only required output; and
- BigMoveBench uses reusable scratch archives, streamed database access,
  results-only srcMove execution, and bounded retained logs.

The current srcMove pipeline is documented in
[Architecture](architecture.md#performance-model). BigMoveBench's serial runner
and optional phase profiler are documented in its
[execution guide](../bigMoveBench/docs/execution.md). No further BigMoveBench
performance project is active.

Historical timings from earlier binaries should not be used as current
baselines. Rebuild current srcMove and srcDiff revisions and record executable,
workload, machine, and container identities before making a new optimization
decision.

## Remaining opportunities

These are investigation candidates, not a queued roadmap.

### Small-file and process overhead

Many srcMove History comparisons contain small files, where process startup,
dynamic loading, srcML/libxml initialization, and srcDiff orchestration may cost
more than matching. If this becomes important:

- compare no-op startup with end-to-end time;
- profile srcDiff and srcMove separately;
- evaluate a batch or persistent interface for many independent pairs; and
- consider an in-memory or library boundary only after ownership and global
  state are understood.

Piping alone removes an intermediate file but does not remove process startup or
the need to parse srcDiff output.

### Identical-file handling in srcDiff

History and directory comparisons may contain many byte-identical files. A
size check followed by a byte comparison could avoid unnecessary conversion and
comparison work. The design must preserve srcDiff's complete-document output
semantics; silently omitting identical units may break consumers. This belongs
in srcDiff and should be measured on representative directory workloads.

### Candidate-heavy Type-3 matching

Type-3 was not the dominant cost in the bounded profiles that motivated the
refactor. Optimize it only when a current candidate-heavy workload shows that
the two-row LCS work is material. Semantics-preserving experiments include:

1. reusing dynamic-programming buffers;
2. trimming common prefixes and suffixes;
3. rejecting pairs whose token-frequency intersection cannot meet the 0.90 LCS
   threshold; and
4. evaluating an exact bit-parallel LCS implementation.

Record candidate pairs, LCS calls, visited cells, early exits, and accepted
edges before changing the implementation.

### Selective XML patching

Annotated runs still make a second XML pass. Copying input bytes and inserting
attributes only at selected start tags might reduce output cost, but naive text
search is unsafe around encodings, entities, CDATA, namespaces, quoted
delimiters, and empty elements. Any prototype needs XML-aware offsets, a safe
fallback to the current writer, namespace coverage, and semantic-equivalence
tests. Results-only mode should remain the preferred path when XML is not
needed.

### Large archive parallelism

Bounded archive-unit parallelism remains a possible large-input optimization.
It does not address single-file startup latency and should be reopened only
after a current large archive profile justifies the complexity. The dormant
[parallel programming plan](parallel_programming_upgrade_plan.md) records the
ownership, determinism, and backpressure constraints.

## Evidence required before implementation

- Use fixed, checksummed workloads and current build receipts.
- Separate srcDiff, srcMove, supervision, validation, and persistence time.
- Report repeated-run wall time, CPU time, peak RSS, and variation.
- Include representative small inputs when measuring fixed overhead.
- Include candidate-heavy inputs when judging matching changes.
- Preserve XML and JSON behavior with regression tests.
- Stop when the measured bottleneck or practical target has been addressed.

Update this document when an opportunity is implemented, rejected by evidence,
or replaced by a clearer design. Do not preserve one-off timings here when the
corresponding artifacts already record them.
