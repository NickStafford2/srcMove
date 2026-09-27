# srcMove History Documentation

srcMove History is srcMove's production tool for analyzing moves across
adjacent Git commits. The executable is `srcmove-history`; `srcmove_history` is
the internal Python package name. This directory is the canonical home for the
component's design, runtime behavior, and research motivation.

## Current design and behavior

- [Architecture decision](architecture.md): product boundary, runtime,
  authoritative state, and compatibility direction
- [Data model](data_model.md): current entity ownership, canonical outcomes,
  and query contracts
- [Runtime behavior](runtime.md): current CLI, persistence, recovery, execution,
  storage, and verification contracts
- [Research motivation](research_motivation.md): why sequential commit analysis
  complements comparisons between distant revisions

The architecture decision defines the product boundary. The runtime document
is the authority for behavior verified by the current implementation. Remaining
ideas live in the repository's [`doc/backlog.md`](../../doc/backlog.md), not in
the current-behavior documentation.

## Supporting notes

- [Storage estimate](notes/storage_estimate.md)

Benchmark-specific setup remains in
[`srcmove_history/benchmarks/README.md`](../benchmarks/README.md).
Benchmarks may invoke `srcmove_history`, but they do not define its state or
execution semantics.
