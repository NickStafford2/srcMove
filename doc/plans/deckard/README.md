# Deckard-based move detection

This plan evaluates an adaptation of Deckard's tree-similarity algorithm as a
structural representation, approximate-retrieval strategy, and comparison
baseline for srcMove. It does not replace srcDiff revision ownership,
candidate eligibility, move-versus-copy reasoning, hierarchical selection, or
the annotation boundary.

The goal is to determine whether Deckard-style characteristic vectors improve
Type-3 retrieval or verification while preserving srcMove's role as a
post-processor of srcDiff output. See [plan.md](plan.md) for the experimental
outline, the canonical
[move-detection redesign](../move_detection_redesign.md) for the surrounding
algorithm, and
[`doc/architecture.md`](../../architecture.md) for the current architecture.

The original Deckard paper is stored in this directory, and
[`reference-implementation`](reference-implementation) links to the local,
ignored Deckard clone registered under `reference-repositories/`.
