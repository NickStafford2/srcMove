# Chapter 10: Conclusion and Future Work

## 10.1 Conclusion

This thesis investigates whether the structured information already present in
srcDiff XML can support an additional, explicit layer of source-code move
analysis. The resulting system, srcMove, treats move detection as a deterministic
post-processing problem. It selects structurally meaningful deletion and
insertion candidates, compares them through exact, consistently normalized, and
bounded-similarity representations, and writes directional move relationships
back into the original XML format.

That core detector is accompanied by four substantial supporting contributions.
BigMoveBench transforms a large clone corpus into controlled cross-file move
experiments while preserving selection, eligibility, failure, and provenance
boundaries. srcVisual turns the resulting XML and source relationships into a
synchronized inspection interface. srcMove History applies the toolchain across
adjacent repository revisions so that moves can be observed near the point at
which they occur. Finally, the performance infrastructure measures both the
core pipeline and the scaling behavior of history analysis on frozen workloads.

Together, these artifacts address more than the implementation of one matching
algorithm. They provide a way to construct move evidence, test it under a
declared oracle, inspect it, apply it longitudinally, and measure its cost.

## 10.2 Answers to the research questions

The final version of this section should answer each research question in one
short paragraph. Each answer must contain the relevant population and
denominator and must point back to the detailed result rather than introducing
new evidence.

### RQ1: Detection and classification

`[FINAL RESULT NEEDED: state the Type-1, Type-2, and Type-3 conclusions using
both generated-case and srcDiff-eligible denominators. Identify the evaluated
selection and program revision.]`

The conclusion should distinguish exact matching, normalization-based matching,
and bounded similarity instead of compressing them into one overall accuracy
number.

### RQ2: Rejection behavior

`[FINAL RESULT NEEDED: state the whole-fragment rejection conclusion for the
declared known-false-positive population, including incidental child matches
and exclusions.]`

This answer must not be labeled general detector precision unless the thesis
adds a representative precision study with an appropriate oracle.

### RQ3: Performance and scaling

`[FINAL RESULT NEEDED: state the observed core pipeline costs, dominant stages,
and history-scaling result with its workload and environment.]`

The conclusion should report measured behavior rather than claim a universal
complexity bound or worker configuration.

### RQ4: Repository-history observations

`[FINAL RESULT NEEDED: state what was observed in the selected repositories and
what the endpoint-versus-history contrast demonstrated.]`

This answer should remain observational unless independent historical ground
truth was introduced.

### Supporting artifact: srcVisual

`[FINAL EVALUATION NEEDED: state what the chosen srcVisual evaluation
demonstrated. If no user study was performed, limit the conclusion to the
implemented and tested inspection requirements.]`

## 10.3 Contributions

Subject to the final evaluation, the thesis contributions are:

1. **srcMove:** a deterministic C++ move-annotation pipeline for single-file
   and archive srcDiff XML, including cross-file matches and explicit Type-1,
   Type-2, and bounded Type-3 classifications.
2. **srcReader integration improvements:** general reader/writer capabilities
   required by the srcMove pipeline, documented with their exact APIs, tests,
   commits, and upstream status. `[DETAILS NEEDED]`
3. **BigMoveBench:** a reproducible system for compiling, selecting,
   materializing, validating, executing, and reporting synthetic move
   experiments derived from BigCloneBench evidence.
4. **srcVisual:** a companion application that derives synchronized XML, tree,
   source, diff, and move views from one final annotated dataset.
5. **srcMove History:** a resumable repository-history analyzer that records
   normalized move evidence across adjacent revisions and explicit endpoint
   comparisons.
6. **Performance and provenance infrastructure:** controlled workload,
   measurement, scaling, process-supervision, and build-identification support
   for evaluating the toolchain.

Before submission, this list must be reconciled with the evaluated revisions.
Anything planned but not implemented or evaluated should move to the future-work
section.

## 10.4 Future work

### 10.4.1 Contextual and ambiguous matching

The current pipeline identifies many-to-many and unequal-cardinality groups but
does not fully reconstruct a unique relationship among every member. Future
work could incorporate file context, neighboring constructs, relative position,
dependency information, or history evidence to rank possible pairings. Such a
model should preserve the current deterministic evidence and expose its added
assumptions rather than replacing interpretable match kinds with an unexplained
score.

### 10.4.2 Richer structural and behavioral evidence

The Type-3 matcher uses bounded syntactic sequence similarity. Further work
could study tree-edit features, data-flow context, symbol resolution, or learned
representations. These extensions should not be called semantic equivalence
unless the evaluation provides an oracle that measures behavior rather than
surface structure.

Type-4 moves remain outside the implemented scope. A defensible Type-4 study
would require a suitable dataset, a clear behavioral definition, and negative
examples capable of distinguishing shared purpose from coincidental similarity.

### 10.4.3 Historical ground truth

The largest limitation of repository-history analysis is the absence of a
complete oracle. A manually reviewed dataset of real moves could sample
commits, preserve reviewer decisions and disagreements, and record whether each
event is a move, copy, extraction, merge, or ambiguous transformation. Multiple
reviewers and a published adjudication protocol would make this evidence more
valuable than retrospective labels created solely from srcMove output.

### 10.4.4 Broader language and project coverage

BigMoveBench's controlled corpus is Java-based. Future evaluations should add
declared populations for other srcML-supported languages and move granularities,
including declarations, classes, and statement blocks. Repository selection
should be designed before observing results so that language, scale, domain,
and commit practices do not become accidental sampling criteria.

### 10.4.5 Precision-oriented evaluation

The known-false-positive experiment tests rejection of complete labeled pairs,
not general precision. A precision study could sample reported moves from real
histories, blind reviewers to match kind where possible, and estimate the
proportion judged to represent meaningful relocations under a written rubric.
The unit of analysis, sampling probabilities, ambiguity policy, and confidence
intervals would need to be declared in advance.

### 10.4.6 Scaling and operational robustness

Performance work can extend to larger histories, more varied repositories,
controlled storage configurations, and longer-running interruption tests.
Potential optimizations should be justified by measured bottlenecks. In
particular, archive-level parallelism, repository materialization, XML I/O, and
Type-3 candidate comparisons should be optimized only when their contribution
is visible in representative profiles.

### 10.4.7 srcVisual evaluation and deployment

A developer study could compare raw XML, conventional diff presentation, and
srcVisual on tasks involving cross-file moves and ambiguous groups. Possible
measures include task completion, correctness, time, navigation behavior, and
qualitative confidence. This requires a proper study design rather than
informal demonstrations.

Public hosting is a separate engineering problem. Before processing untrusted
repositories or XML, srcVisual would require threat modeling, process and
filesystem isolation, resource limits, input-size constraints, dependency
hardening, and operational monitoring.

## 10.5 Closing statement

The durable contribution of this work is an explicit, inspectable layer of move
analysis built on structured source differences. srcMove demonstrates how that
layer can be implemented; BigMoveBench, srcMove History, srcVisual, and the
performance infrastructure demonstrate how it can be evaluated, observed, and
communicated. The final strength of this conclusion must remain proportional to
the frozen evidence inserted into the placeholders above.

## Remaining writing tasks

- Replace every result placeholder with a reference to a final table, figure,
  or manifest.
- Insert the exact srcReader contribution details or remove that contribution
  from the final list.
- Ensure terminology matches Chapter 2 and match semantics match the evaluated
  srcMove revision.
- Remove any future-work item already implemented before submission.
- Condense this chapter after results are final; the submitted conclusion should
  emphasize findings rather than repeat implementation detail.

