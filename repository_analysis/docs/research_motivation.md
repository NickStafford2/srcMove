# Research Motivation

srcMove can compare widely separated repository revisions, but distant
comparisons may hide moves that were visible when they happened.

Consider this sequence:

1. A developer writes `foo()` in file A.
2. The developer moves `foo()` to file B.
3. The developer changes `foo()` enough that its earlier form no longer
   matches.

Comparing the first and third commits may report no move even though the
repository history contains one. Analyzing each adjacent commit pair preserves
the opportunity to observe the relocation before later edits obscure it.

`repository_analysis` therefore freezes a starting revision, walks backward
through adjacent commits, materializes the changed files on both sides of each
pair, runs srcDiff and srcMove, and records normalized evidence. This supports
longitudinal questions about when, where, and how moves occur over a
repository's lifetime.

The current operational contract is documented in [Runtime behavior](runtime.md).
