# srcMove History Documentation

`srcmove_history` is srcMove's production tool for analyzing moves across
adjacent Git commits. This directory is the canonical home for its design,
runtime behavior, and research motivation.

## Current design and behavior

- [Architecture decision](architecture.md): product boundary, target runtime,
  authoritative state, and migration direction
- [Data model](data_model.md): entity ownership, canonical outcomes, and
  query contracts
- [CLI plan](cli_plan.md): intended commands, output contract, progress, and
  implementation sequence
- [Runtime behavior](runtime.md): current CLI, persistence, recovery, execution,
  storage, and verification contracts
- [Research motivation](research_motivation.md): why sequential commit analysis
  complements comparisons between distant revisions

The architecture decision defines the product boundary. The data model and CLI
plan define stable concepts and remaining interface work. The runtime document
is the authority for behavior verified by the current implementation.

## Supporting notes

- [Storage estimate](notes/storage_estimate.md)

Benchmark-specific setup remains in
[`benchmarks/repositories/README.md`](../../benchmarks/repositories/README.md).
Benchmarks may invoke `srcmove_history`, but they do not define its state or
execution semantics.
