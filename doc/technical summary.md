
# Summary
Semantic Move Detection Research (C++)

Developing a high-performance semantic move detector on top of srcML and srcDiff to identify relocated code across files and refactors. The system uses AST-based analysis, fast hashing, and probabilistic scoring to reconstruct developer intent during large structural changes. Designed for scalability and real-world static analysis workflows. 

## Semantic-Based Move Detection for Source Code Evolution (C++ / srcML / srcDiff)

My master’s research focuses on building a high-performance semantic move detection system for modern source code. Traditional line based diff tools fail during refactors, function extraction, and large reorganizations, reporting moved code as deletions and insertions. Dynamic analysis and compiler based tools can not scale. This limits static analysis, refactoring tools, and software evolution research.

I am developing a C++ move detector on top of srcML and srcDiff that operates on parsed syntax trees rather than raw text. The system identifies Type-1 and Type-2 clones and reconstructs moved constructs across blocks and files using fast hashing, indexed matching, and probability-based scoring.

Rather than expensive full-tree comparisons, the pipeline uses SHA-1 fingerprints and constrained candidate matching to remain performant on large codebases. Each potential move is scored using structural similarity, construct size, locality, and known developer behaviors such as include reordering and extract-method patterns. High-confidence matches are automatically classified as moves, while ambiguous cases can be surfaced for review.

This work enables refactor-aware analysis by preserving developer intent during code evolution. Accurate move detection is essential for clone detection, static analysis, change impact studies, and tooling that operates at scale.

The current implementation includes a full parsing pipeline, move registry, and indexed matching infrastructure in C++, with integration into srcDiff planned.

