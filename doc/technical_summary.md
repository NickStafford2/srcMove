# Summary
Semantic Move Detection Research (C++)

Developing a high-performance semantic move detector on top of srcML and srcDiff to identify relocated code across files and refactors. The system uses AST-based analysis, fast hashing, and probabilistic scoring to reconstruct developer intent during large structural changes. Designed for scalability and real-world static analysis workflows.

## Semantic-Based Move Detection for Source Code Evolution (C++ / srcML / srcDiff)

My master’s research focuses on building a scalable semantic move detection system for modern codebases. Traditional line-based diff tools break down during refactors, function extraction, and large reorganizations, often misclassifying moved code as deletions and insertions. Compiler-based and dynamic approaches do not scale well to large repositories, which limits static analysis, refactoring tools, and software evolution research.

I am developing a C++ move detector on top of srcML and srcDiff that operates directly on parsed syntax trees rather than raw text. The system identifies Type-1 and Type-2 clones and reconstructs moved constructs across blocks and files using fast hashing, indexed matching, and probability-based scoring.

Instead of expensive full-tree comparisons, the pipeline relies on SHA-1 fingerprints and constrained candidate matching to remain performant on large codebases. Each potential move is evaluated using structural similarity, construct size, locality, and common developer behaviors such as include reordering and extract-method patterns. High-confidence matches are automatically classified as moves, while ambiguous cases are surfaced for review.

This work enables refactor-aware analysis by preserving developer intent during code evolution. Accurate move detection is foundational for clone detection, static analysis, change impact studies, and tooling that must operate at scale.

The current implementation includes a complete parsing pipeline, move registry, and indexed matching infrastructure in C++, with planned integration into srcDiff.

This work is being prepared for peer-reviewed publication.
