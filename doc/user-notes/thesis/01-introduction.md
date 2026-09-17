# Chapter 1: Introduction

Software changes are often described as additions and deletions. That
description is sufficient to reconstruct one revision from another, but it is
not always sufficient to explain the relationship between them. A developer may
move a function to a new file, reorder statements, or relocate a declaration
while changing its names or literals. A differencing system can encode the
corresponding source regions as a deletion and an insertion without explicitly
stating that they belong to the same higher-level change. Recovering that
relationship is the subject of this thesis.

This chapter motivates move-aware source differencing, defines the problem
addressed by srcMove, summarizes the approach, and identifies the thesis's main
research and engineering contributions. The goal is not to replace the edit
script produced by srcDiff. Instead, srcMove adds a deterministic layer of
interpretation to structured regions that srcDiff has already exposed.

## 1.1 Motivation

Program structure changes continuously during maintenance. Functions migrate
between files as responsibilities are redistributed; declarations move closer
to their uses; classes are split; and statement blocks are reorganized during
refactoring. These changes matter to reviewers and researchers because a
relocation conveys a different explanation from independent removal and
addition. The former suggests continuity of a source construct, whereas the
latter suggests disappearance and replacement. Prior work is needed to establish
the effect of this distinction on code review, program comprehension, and
software-evolution analysis. **[CITATION NEEDED: empirical studies of moved-code
comprehension, review, and change-history analysis]**

The presentation problem becomes more pronounced across file boundaries. A
local diff may show the removal in one file and the addition in another, leaving
the reader to discover their relationship manually. Even when a structured
difference format retains both regions in one document, the relevant evidence
may be separated by file units and surrounded by XML representation details.
Machine-readable links between the regions can support downstream inspection,
measurement, and visualization.

Move detection is also an evaluation problem. It is easy to construct a small
example in which two fragments are visibly identical. It is harder to determine
which structural regions should count as candidates, how renamed or partially
changed fragments should be classified, how unavailable input evidence should
be distinguished from detector failure, and how performance should be measured
on repeatable workloads. This thesis therefore treats the detector, benchmark,
history analyzer, visualization, and performance infrastructure as related but
separately motivated artifacts.

### Motivating example

The final thesis should introduce one compact example in which a meaningful
construct is deleted from one file and inserted into another. Four views of the
same case should be retained as a reproducible artifact: the original and
modified source, srcDiff XML before annotation, srcMove XML with its shared
`mv:id` and directional links, and the corresponding srcVisual rendering. The
example should demonstrate explanatory value without being used as evidence of
general detection accuracy.

TODO: Select, freeze, and cite the motivating example artifact.

## 1.2 Problem statement

srcMove addresses the following technical problem: given a srcDiff XML document,
identify eligible deleted and inserted structural fragments that satisfy a
declared syntactic matching rule, group the accepted regions as moves, and
annotate their relationship without discarding the original structured diff.
The input may describe one file or an archive of files. Archive support is
essential because the deletion and insertion associated with a move may belong
to different file units.

This formulation establishes several boundaries. srcMove does not compare
source revisions directly and does not generate the base edit script. It depends
on `diff:delete` and `diff:insert` regions exposed by srcDiff. A relocation that
is not represented as usable input candidates cannot be recovered by the
current pipeline. srcMove also does not prove that a developer intended a
refactoring, that two fragments behave equivalently, or that one fragment
historically originated from the other. It reports a declared structural and
lexical relationship within the available difference document.

The output is an enriched srcDiff document. Accepted regions share an `mv:id`.
A deletion receives an `mv:to` link to its destination XPath or XPath union, and
an insertion receives an `mv:from` link to its source. The output can therefore
remain part of the existing XML toolchain while exposing relationships to
analysis and visualization clients.

## 1.3 Approach

The thesis studies an end-to-end path with four conceptual stages:

```text
source revisions -> srcML/srcDiff XML -> srcMove annotations -> srcVisual
```

srcML supplies the XML representation of source structure, srcDiff records the
structured differences between revisions, srcMove recovers and annotates move
relationships, and srcVisual renders the resulting evidence in synchronized
views. These responsibilities remain separate: srcMove is a command-line
post-processor rather than an extension embedded in srcDiff, and srcVisual
consumes rather than defines the annotation semantics.

Within srcMove, the implemented pipeline performs four main operations. First,
it streams the input and records each deletion and insertion with its file
ownership, nesting, source text, XML nodes, and location. Second, it selects
candidate regions. The default policy starts from leaf diff regions, excludes
whitespace-only and low-information fragments, and prefers complete structural
children such as functions, classes, declarations, conditionals, loops, and
statements. Third, it constructs cached canonical representations and attempts
matching in a fixed order:

- **exact (Type 1)** matches preserve meaningful tokens and srcML structure
  while ignoring comments and formatting-only content;
- **Type 2** matches consistently number direct name tokens by first occurrence
  and replace literals with their categories while retaining other tokens,
  operators, and structure; and
- **Type 3** matches compare bounded statement/block and token sequences using
  a declared longest-common-subsequence rule.

Type-1 and Type-2 matching use hashes only as indexes; full canonical content is
checked before a group is accepted. Type-3 comparison is restricted by element
kind and size, then selects accepted edges deterministically. Finally, a second
streaming pass preserves the input document and adds the move annotations.
Chapter 4 gives the complete implementation account; the canonical technical
description remains `doc/architecture.md` while this thesis is drafted.

The evaluation design mirrors the pipeline boundary. BigMoveBench converts
BigCloneBench pairs into synthetic cross-file before/after cases. It first asks
whether srcDiff exposed the complete intended payloads and only then scores
srcMove's detection and classification. Known-false-positive pairs support a
separate whole-fragment rejection experiment. Real histories and performance
workloads address different questions and therefore are not combined into one
undifferentiated accuracy number.

## 1.4 Contributions

Subject to the final evaluation, this thesis makes the following contributions.

1. **A deterministic move-annotation pipeline for srcDiff XML.** srcMove
   selects meaningful structural candidates and annotates exact, consistently
   normalized Type-2, and bounded Type-3 move relationships, including
   relationships across file units.
2. **A reproducible synthetic evaluation method.** BigMoveBench transforms
   labeled BigCloneBench fragment pairs into controlled cross-file revisions,
   records provenance, verifies srcDiff eligibility, and applies a strict
   whole-fragment detection-and-classification oracle.
3. **Explicit separation of evaluation boundaries.** The evaluation reports
   generated-case outcomes separately from conditional srcMove outcomes,
   treats known-false-positive rejection as narrower than general precision,
   and keeps tuning, publication, and historical exploratory evidence distinct.
4. **A repository-history analysis system.** srcMove History runs the toolchain
   across adjacent Git revisions so detected events can be studied without
   reducing a long interval to a single endpoint comparison. Its findings are
   observational unless an independent ground-truth oracle is supplied.
5. **A synchronized inspection interface.** srcVisual derives XML, tree,
   source, diff, and move views from one normalized annotated payload, making
   cross-file relationships inspectable without treating visualization as
   evidence of detector correctness.
6. **Performance and provenance infrastructure.** Named workloads, stage
   timings, process measurements, history-scaling experiments, and executable
   provenance support repeatable analysis of toolchain cost.

The final contribution list must distinguish evaluated research results from
engineering support. Any item that is not delivered and evaluated at thesis
submission should be narrowed or removed rather than presented as completed.

## 1.5 Thesis organization

Chapter 2 introduces structured source differencing, the srcML ecosystem, move
and clone terminology, related detection systems, benchmark foundations, and
change visualization. Chapter 3 states the research questions and scope limits.
Chapter 4 describes srcMove's design, implementation, annotation model, and
supporting srcReader improvements. Chapter 5 presents BigMoveBench. Chapter 6
describes srcVisual. Chapter 7 presents srcMove History and its observations.
Chapter 8 evaluates runtime, memory, throughput, and scaling. Chapter 9
synthesizes the evidence and discusses validity threats. Chapter 10 concludes
the thesis and identifies future work.

## 1.6 Evidence still required

- **[CITATION NEEDED]** Establish why recognizing relocation matters in code
  review, comprehension, refactoring, or history analysis.
- **[CITATION NEEDED]** Position post-processing and move-aware differencing
  against primary related work.
- TODO: Freeze the motivating example and make every representation
  reproducible.
- TODO: Reconcile the final contribution wording with the completed evaluation
  and remove claims supported only by implementation effort.
- TODO: Update the chapter map if the university template requires background
  and related work, or method and results, to be separated.
