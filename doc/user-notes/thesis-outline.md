# Introduction

- Problem: traditional diffs often represent moved code as unrelated deletes/inserts.
- Why move detection matters:
  - refactoring comprehension
  - change impact analysis
  - code review readability
  - software evolution research

- Research goal: improve srcDiff XML by annotating likely moved code.
- Research questions:
  - Can moved code be detected from srcDiff delete/insert regions?
  - How accurately does the approach detect exact and renamed/modified moves?
  - How does the approach scale on generated and large real-world diffs?
  - How frequent are moves in large real world repositories?

# 2. Background

- srcML overview.
- srcDiff overview.
- XML-based source differencing.
- Code clones and clone types.
- Relationship between clone detection and move detection.
- Why BigCloneBench is useful but imperfect for this work.

# 3. Definitions

- Move: a source fragment deleted from one location and inserted at another location.
- Type-1 move:
  - moved code is textually identical or differs only in whitespace/comments/formatting, depending on benchmark definition.
  - In current srcMove implementation, exact raw inner-text matching is the main detection mechanism.

- Type-2 move:
  - moved code preserves structure but identifiers, literals, or names may change.
  - Example: moving a method while renaming variables or constants.

- Type-3 / Type-4 moves:
  - define briefly for context.
  - State they are not supported in this implementation.

- Synthetic move case:
  - a generated before/after edit made from a known BigCloneBench clone pair.

- Move annotation:
  - adding move="<id>" and xpath="<path>" to matched diff:delete / diff:insert regions.

- Move Group
  - Add better definition here.
  - Moves can be:
    - One to One - One single section of code is moved from one location to another
    - One to Many - One single section of code is removed in one location, and added in more than one different locations
    - Many to Many - Many copies of the same section of code is removed from several locations, and added in several locations.

# 4. Related Work

- Text differencing.
- AST differencing.
- srcML / srcDiff ecosystem.
- Clone detection literature.
- BigCloneBench / BigCloneEval.
- Refactoring detection tools.
- Discussion of subjectivity in clone/move judgment.

# 5. System Design

- Input: srcDiff XML.
- Output: annotated srcDiff XML.
- Pipeline:
  - collect diff regions
  - filter candidate move units
  - hash candidate contents
  - group deletes/inserts
  - assign move ids
  - rewrite XML with move annotations

- Design constraints:
  - preserve valid XML
  - avoid full tree materialization
  - keep memory predictable
  - avoid delete/insert pair explosion

- Current limitations:
  - primarily content-based
  - Type-3/Type-4 unsupported
  - Type-2 support is partial/strict

# 6. Implementation

- C++17 implementation.
- srcReader / srcML integration.
- Region collection.
- Candidate filtering:
  - leaf-only regions
  - skip whitespace-only regions
  - skip pre-existing move annotations

- Hashing and exact equality check.
- Type-2 matching path.
- Annotation writer.
- JSON result summaries.
- Profiling instrumentation.

# 7. Benchmark Construction

- BigCloneBench is clone data, not historical move data.
- Conversion process:
  - select clone pairs
  - extract Java fragments from IJaDataset
  - synthesize original/modified files
  - run srcdiff
  - run srcMove
  - validate expected move

- Dedupe policy:
  - raw-text-pair
  - explain why row counts and distinct text-pair counts differ

- Validation oracle:
  - expected one delete/insert move
  - position overlap
  - text validation
  - match kind: exact or type2

- Caveats:
  - synthetic moves do not prove real-world precision
  - malformed or partial fragments can affect results
  - BigCloneBench similarity does not equal srcMove raw-text equality

# 8. Results

- Dataset summary:
  - Type-1 requested 1000, selected 915 deduped cases
  - Type-2 requested 1000, selected 640 deduped cases

- Correctness results:
  - Type-1: 909 / 915 passed
  - Type-2: 286 / 640 passed

- Failure-class table:
  - Type-1:
    - pass_strict: 905
    - pass_encoding_tolerant: 4
    - no_move_raw_different: 3
    - validation_failure: 2
    - text_mismatch: 1

  - Type-2:
    - pass_strict: 286
    - no_move_raw_different: 354

- Performance results:
  - Type-1 median pipeline.total_ms: 13.868
  - Type-2 median pipeline.total_ms: 8.909
  - OpenCV median pipeline.total_ms: 18983.937

- Phase breakdown:
  - parsing
  - filtering
  - content grouping
  - annotation

- Important result interpretation:
  - content grouping is very cheap
  - parsing and annotation dominate runtime
  - Type-2 is the main accuracy limitation

# 9. Discussion

- What the Type-1 results show.
- Why Type-2 is harder.
- Why BigCloneBench raw-different failures matter.
- Difference between clone similarity and move detection.
- Tradeoff between false positives and recall.
- Developer expectation: moves should correspond to meaningful refactoring/change comprehension.

# 10. Threats To Validity

- Synthetic benchmark construction.
- BigCloneBench clone labels are not historical moves.
- Dedupe choice affects counts.
- Java-only benchmark source.
- srcDiff behavior affects exposed delete/insert regions.
- Current oracle expects one move, but some cases may naturally expose child moves.
- Performance measured on one machine/environment.

# 11. Future Work

- Improve Type-2 matching.
- Add structural similarity scoring.
- Add Type-3 support.
- Better failure categorization.
- Cross-file and multi-file move cases.
- Real-world manually reviewed refactoring dataset.
- Precision/negative benchmark.
- Visualization integration.
- Reduce annotation overhead.

# 12. Conclusion

- Restate contribution:
  - srcMove post-processes srcDiff XML to recover move annotations.
  - Works well for exact Type-1 synthetic moves.
  - Provides measurable partial Type-2 support.
  - Scales with low matching overhead; XML parsing/annotation dominate.

- Summarize research value and path toward publication.
