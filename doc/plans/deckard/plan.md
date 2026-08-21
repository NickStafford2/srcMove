# Implementation plan

Status: proposed; none of the behavior below is implemented yet.

## Objective

Adapt Deckard's characteristic-vector and similarity-clustering approach to
match srcDiff delete regions with insert regions. Use the srcML AST already
embedded in srcDiff output rather than introducing a separate source parser.

Development will take place in a new `src2/` directory alongside `src/`.
Relevant code will initially be copied from `src/` so the current and
Deckard-based implementations remain easy to compare. The existing `src/`
implementation will remain the baseline until `src2/` has been validated.

The replacement should recognize:

- Type-1 moves with structurally identical code
- Type-2 moves with renamed identifiers or changed literals
- Type-3 moves with limited statement additions, deletions, or modifications

## Work

1. Create `src2/` from the reusable parts of `src/`, preserving a clear mapping
   between corresponding files and avoiding unrelated redesign during the
   initial copy.
2. Define the AST node vocabulary, ignored nodes, candidate boundaries, and
   minimum region size used to construct characteristic vectors.
3. Generate vectors for every eligible srcDiff delete and insert region by
   traversing its srcML AST. Add vector merging only where a diff region needs
   to represent adjacent AST fragments rather than one complete subtree.
4. Compare only delete vectors against insert vectors. Begin with exact
   Euclidean-distance search for a simple, testable baseline; introduce
   size-sensitive grouping and LSH only if benchmark scale requires them.
5. Convert vector distance into explicit Type-1, Type-2, and Type-3 acceptance
   rules, including deterministic tie-breaking when several regions match.
6. Feed accepted pairs into the existing move-annotation output stage, then
   remove the superseded canonical-text matching path.
7. Validate each move type independently with focused fixtures and benchmark
   the result against the current detector for accuracy, runtime, and memory.

## Constraints

- srcDiff remains responsible for identifying insert and delete regions.
- srcML remains the only source of syntax-tree structure.
- `src/` remains unchanged as the comparison baseline during `src2/`
  development, except for separately approved shared fixes.
- Detection must work across files in archive-form srcDiff documents.
- Approximate matching must be deterministic at the srcMove output boundary,
  even if an approximate-neighbor index is introduced internally.
- Existing output annotations and command-line behavior should remain stable
  unless a separate compatibility change is approved.
