# Repository Analysis Documentation

`repository_analysis` is srcMove's production tool for analyzing moves across
adjacent Git commits. This directory is the canonical home for its design,
runtime behavior, research motivation, and study results.

## Current design and behavior

- [Architecture decision](architecture.md): product boundary, target runtime,
  authoritative state, and migration direction
- [Data model](data_model.md): target entity ownership, accepted outcomes, and
  query contracts
- [CLI plan](cli_plan.md): intended commands, output contract, progress, and
  implementation sequence
- [Runtime behavior](runtime.md): current CLI, persistence, recovery, execution,
  storage, and verification contracts
- [Research motivation](research_motivation.md): why sequential commit analysis
  complements comparisons between distant revisions

The architecture decision defines where the program is going. The data model
and CLI plan refine that direction. The runtime document describes what the
current implementation has verified today. Keep those roles separate: proposed
structure does not become documented behavior until it is implemented and
tested.

## Studies and supporting notes

- [Preliminary parallel-scaling study](studies/parallel_scaling_pilot.md)
- [Storage estimate](notes/storage_estimate.md)

Files under `history/` preserve implementation context from completed phases.
They are not current requirements and should not be used in place of the two
current documents above.

Benchmark-specific setup remains in
[`benchmarks/repositories/README.md`](../../benchmarks/repositories/README.md).
Benchmarks may invoke `repository_analysis`, but they do not define its state or
execution semantics.
