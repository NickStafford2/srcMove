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

The first milestone is a reasonably faithful reproduction of Deckard's core
algorithm, not immediate tuning toward srcMove's existing expected results.
Once that baseline produces results, its clone and move classifications can be
reviewed and the similarity policy tuned separately.

The replacement should recognize:

- Type-1 moves with structurally identical code
- Type-2 moves with renamed identifiers or changed literals
- Type-3 moves with limited statement additions, deletions, or modifications

## Work

1. Create `src2/` from the reusable parts of `src/`, preserving a clear mapping
   between corresponding files and avoiding unrelated redesign during the
   initial copy. Add a separate `srcMove2` CMake target while leaving the
   existing `srcMove` target bound to `src/`.
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

## Implementation strategy

Before reimplementing a component, check whether a well-isolated part of the
bundled Deckard implementation can be reused directly or whether its executable
pipeline can serve as a comparison oracle. Direct reuse is expected to be
limited by Deckard's parser, data formats, dependencies, and process boundaries.
The likely approach is therefore to reproduce its functionality in `src2/`,
adapted to srcDiff regions and srcML ASTs, while keeping the reference source
close at hand for comparison. Any copied source must retain its required
license and attribution.

## Working map

- [`src/pipeline.cpp`](../../../src/pipeline.cpp): current pipeline orchestration
- [`src/parse/diff_region.hpp`](../../../src/parse/diff_region.hpp): captured
  srcDiff regions and their embedded srcML nodes
- [`src/writer/annotation_writer.hpp`](../../../src/writer/annotation_writer.hpp):
  move-annotation output boundary to preserve
- [`CMakeLists.txt`](../../../CMakeLists.txt): current `srcMove` build target and
  location for the parallel `srcMove2` target
- [`tests/README.md`](../../../tests/README.md): test commands and binary-path
  override used for side-by-side runs
- [`reference-implementation`](reference-implementation): bundled Deckard source
- [Deckard paper](<DECKARD_ Scalable and accurate tree-based detection of code clone.pdf>)
  is the canonical algorithm description

## First milestone

The initial Deckard-style baseline is ready for evaluation when:

- `srcMove` still builds from `src/`, while `srcMove2` builds independently from
  `src2/`.
- `srcMove2` accepts the same command-line inputs and srcDiff document forms as
  `srcMove`.
- `srcMove2` constructs Deckard-style characteristic vectors from the captured
  srcML nodes and uses them to compare delete regions only with insert regions.
- It emits compatible move annotations and completes representative cases
  without crashes or malformed output.
- The test runner can execute the same cases against either binary through its
  `--srcmove` option, and the resulting reports can be retained for comparison.
- No similarity thresholds or classification rules have been tuned merely to
  reproduce the previous implementation's expected results. Later tuning
  decisions are recorded separately from this baseline.

## Evaluation policy

Clone and move detection are similarity judgments rather than an exact oracle.
The current test corpus is incomplete and its expected classifications may
change, particularly at the boundary between a clone and a non-clone. The
previous srcMove implementation did not pass every test and produced false
positives, so neither its output nor every current fixture is authoritative for
the new detector.

During the initial implementation, tests should expose behavioral differences,
regressions, crashes, and output-format problems. A disagreement with an
expected clone classification should be recorded and inspected, but should not
automatically drive algorithm changes. First obtain results from a faithful
Deckard-style baseline; evaluate and tune its clone thresholds and policies in
a later phase.

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
