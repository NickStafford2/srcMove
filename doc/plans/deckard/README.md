# Deckard-based move detection

This plan will replace srcMove's current move-matching algorithm with an
adaptation of the Deckard tree-similarity algorithm. The detector will operate
on the delete and insert regions supplied by srcDiff and will derive structural
vectors from the srcML-generated AST contained in those regions.

The goal is to improve detection of Type-1, Type-2, and Type-3 moves while
preserving srcMove's role as a post-processor of srcDiff output. See
[plan.md](plan.md) for the implementation outline and
[`doc/architecture.md`](../../architecture.md) for the current architecture.

The original Deckard paper is stored in this directory, and
[`reference-implementation`](reference-implementation) links to the bundled
Deckard source repository.
