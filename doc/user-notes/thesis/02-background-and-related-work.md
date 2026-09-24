# Chapter 2: Background and Related Work

srcMove lies at the intersection of source-code differencing, structured source
representations, clone classification, refactoring analysis, and change
visualization. This chapter establishes the vocabulary needed by the remainder
of the thesis and defines the dimensions on which related systems should be
compared. It postpones implementation details to Chapter 4 and benchmark
procedure to Chapter 5.

## 2.1 Source-code differencing

A source-code differencing system must identify how two program revisions
relate. A line-oriented diff treats each file as a sequence of lines and reports
an edit script over that sequence. This representation is broadly applicable
and familiar, but source syntax does not necessarily align with physical lines.
A construct may span many lines, several constructs may share a line, and
formatting edits may dominate a textual comparison. **[CITATION NEEDED:
foundational line-differencing source and empirical limitations for source
code]**

Syntax-aware and tree-oriented approaches compare representations that retain
program structure. Their edit operations may refer to declarations, statements,
expressions, or names rather than only to lines. Structure can improve the
correspondence between an edit script and a programmer's conceptual change, but
it introduces choices about parsing, node identity, candidate granularity,
matching, ambiguity, and cost. **[CITATION NEEDED: primary tree-differencing and
syntax-aware differencing literature]**

An edit script should also be distinguished from an explanation. More than one
valid sequence of operations can transform an old representation into a new
one, and an edit script optimized for a formal cost need not produce the most
useful account for a human reader. A deletion and insertion reconstruct the
result even when the corresponding construct was relocated. A move operation
adds a relationship between those regions; depending on the system, that
relationship may mean identical content, structural similarity, inferred node
continuity, copying, or a recognized refactoring. Comparisons between tools must
therefore state what their move operation actually asserts.

This thesis uses *move* in a bounded sense. srcMove accepts a deleted and
inserted candidate when they satisfy one of its declared syntactic matching
rules. It does not infer semantic equivalence or developer intent.

## 2.2 The srcML ecosystem

### 2.2.1 srcML

srcML represents source code as XML by placing markup around syntactic
constructs while retaining source text. This combination provides a useful
middle ground for srcMove: lexical content, operators, and formatting remain
available, while elements identify constructs such as names, declarations,
functions, and statements. **[CITATION NEEDED: primary srcML paper and official
project documentation]**

The thesis should avoid calling every srcML document an abstract syntax tree
without qualification. srcMove operates on XML events and source text embedded
in srcDiff, not on a compiler AST with semantic bindings or type information.
Its canonicalization and similarity rules are therefore structural and lexical.

### 2.2.2 srcDiff

srcDiff compares source revisions and emits XML containing srcML structure and
difference markup. Deleted and inserted regions appear as `diff:delete` and
`diff:insert` elements. Inputs may describe a single file or an archive with
multiple file units. The archive shape makes it possible for one document to
contain a deletion in one file and an insertion in another.

srcMove treats this document as its input contract. It neither recreates the
source comparison nor assumes that well-formed XML contains every region needed
for move detection. srcDiff may align revisions in a way that does not expose a
complete intended payload as usable deletion and insertion regions. This is why
BigMoveBench reports end-to-end outcomes separately from outcomes conditional on
srcDiff eligibility.

TODO: Add the primary srcDiff citation and a small, schema-accurate example.

### 2.2.3 srcReader

srcReader supplies streaming reader and writer infrastructure for processing
srcML-derived XML. srcMove uses streaming passes to discover regions and to
preserve the original document while patching selected start tags. Supporting
srcReader improvements belong to the implementation account in Chapter 4
because they enabled the srcMove pipeline; they are not an independent research
question. **[CITATION NEEDED: official srcReader source/documentation if cited
as a published artifact]**

## 2.3 Proposed General Taxonomy of Source-Code Moves

This thesis proposes Type-1 through Type-4 as a general taxonomy of
**source-code moves**, not merely as names for srcMove's implementation stages.
The labels resemble familiar clone categories, but the object being classified
is different. Clone classification describes similarity between two fragments.
Move classification describes the transformation and continuity of a source
fragment as it changes location between revisions. A similar pair is not
necessarily a move, and a move can remain the same conceptual program entity
even after it is no longer a syntactic clone.

The taxonomy is intended to give researchers, differencing tools, refactoring
systems, benchmarks, and visualization tools a shared vocabulary. Its novelty
claim must be established through a dedicated literature review. Until that
review is complete, the thesis should say that the taxonomy is **proposed by
this work** rather than claiming that no prior move taxonomy exists.
**[LITERATURE REVIEW NEEDED: search specifically for taxonomies of moved code,
move-aware differencing, origin analysis, refactoring classification, and code
lineage—not only clone taxonomies.]**

### 2.3.1 What constitutes a move

Let a source fragment `A` occur at location `L_old` in revision `R_old`, and let
a related fragment `B` occur at location `L_new` in a later revision `R_new`.
A move claim asserts all of the following:

1. `L_old` and `L_new` are meaningfully different locations under a declared
   location model;
2. `A` and `B` represent continuity of one source entity, implementation unit,
   or developer action under a declared evidence model; and
3. the relationship is directional from the earlier occurrence to the later
   occurrence.

The location model may distinguish positions within one block, containers
within one file, files within one revision, or repositories. The evidence model
may use exact content, normalized syntax, structural similarity, history,
symbol identity, commit metadata, tests, or human judgment. A rigorous report
must state both models because neither similarity nor changed coordinates alone
proves continuity.

The **move type** describes how the fragment changed while relocating. It does
not describe distance, size, multiplicity, detector confidence, or whether the
source copy survived. Those properties are orthogonal dimensions defined
below.

### 2.3.2 Type-1 move: presentation-preserving relocation

A **Type-1 move** relocates a source fragment while preserving its program text
up to a declared set of presentation changes. At the strictest level, the old
and new fragments are byte-for-byte identical. A practical language-aware
definition may also ignore whitespace, layout, and comments when those features
do not change the fragment's syntactic content.

Examples include moving an unchanged function to another file, reordering an
unchanged declaration within a class, or relocating a statement block while
reformatting indentation. The reporting system must state which presentation
features are ignored; otherwise “Type-1” is ambiguous between byte equality and
formatting-insensitive equality.

Type-1 is the strongest syntactic move category. When more than one category
applies, a detector or annotated dataset should select the strongest applicable
type rather than relabel an exact relocation as a weaker approximate move.

### 2.3.3 Type-2 move: systematically rewritten relocation

A **Type-2 move** preserves the fragment's syntactic organization while making
lexical substitutions in addition to the presentation differences permitted by
Type-1. Typical substitutions include identifier renaming and replacement of
literals by other values of the same category.

Clone research uses both blind and consistent forms of Type-2 normalization.
Blind normalization replaces identifiers without preserving a one-to-one
correspondence between distinct names. Under that rule, `x + x` and `y + z`
can share the same normalized form. Consistent normalization assigns a stable
placeholder to each distinct name, so `x + x` can match `y + y` but not
`y + z`. BigCloneEval reports the union as its most generous Type-2 category
and distinguishes blind and consistent subsets. **[CITATION NEEDED: primary
clone-taxonomy source and BigCloneEval definitions of all, blind, and
consistent Type-2]**

This thesis adopts the consistent form for Type-2 moves. A move asserts
continuity across revisions, not similarity alone, so preserving the pattern of
repeated and distinct names provides stronger evidence and reduces matches
between unrelated fragments that merely share a token skeleton. Generous or
blind Type-2 remains a useful clone category, but srcMove does not treat it as
sufficient evidence for a Type-2 move.

Examples include moving a function while renaming its parameters to match a new
module's conventions, or relocating a configuration statement while changing
one string or numeric constant. Arbitrary token replacement is not sufficient.
The defining property is preservation of syntactic organization under a
declared, consistently mapped substitution model.

Type-2 is still a syntactic category. It does not prove that renamed identifiers
bind to equivalent declarations, that replacement literals preserve behavior,
or that the relocation is semantics preserving. A semantic analysis may add
such evidence, but it is not part of the minimum Type-2 definition.

### 2.3.4 Type-3 move: structurally modified relocation

A **Type-3 move** relocates a fragment while adding, deleting, or modifying
syntactic material, yet retains enough recognizable structure to support a
continuity claim. The retained core may consist of ordered statements,
expressions, tokens, control-flow shape, or another declared structural
representation.

Examples include moving a function and adding validation, extracting a block
while deleting statements that are no longer relevant, or moving a method while
both renaming variables and modifying several expressions. Unlike Type-2, the
relationship cannot be established through systematic lexical substitution
alone.

The taxonomy intentionally does not prescribe one universal similarity
threshold. A threshold is an operational decision made by a detector or
benchmark and must identify its representation, similarity function,
normalization, minimum granularity, and acceptance rule. One system may use
tree edit distance, another a token sequence, and another a combination of
structural features. They can all report Type-3 moves if they expose those
choices and evaluate the resulting boundary.

### 2.3.5 Type-4 move: continuity without sufficient syntactic similarity

A **Type-4 move** preserves conceptual, behavioral, or historical continuity
despite insufficient lexical or structural similarity for Type-1 through
Type-3. This category covers cases where a source entity is relocated and
substantially rewritten, translated into another representation, or replaced
by a behaviorally corresponding implementation.

Type-4 requires evidence beyond ordinary syntax similarity. Possible evidence
includes explicit refactoring provenance, symbol or lineage tracking, commit
metadata, dependency correspondence, equivalent tests, semantic analysis, or
human annotation. Two unrelated fragments that happen to implement similar
behavior are not a move merely because they could be described by the same
requirement. The evidence must support continuity from the earlier occurrence
to the later one.

This is the most difficult category to operationalize and validate. A detector
should not report Type-4 solely because a Type-3 comparison failed. It must name
the additional evidence that justifies the relationship. srcMove does not
currently attempt Type-4 detection.

### 2.3.6 Orthogonal move dimensions

The four types describe transformation strength. They should be combined with
orthogonal dimensions rather than stretched to encode every property of a
move:

- **Granularity:** expression, statement, block, declaration, function, class,
  file, or another declared unit.
- **Spatial scope:** within one container, within one file, across files, across
  modules, or across repositories.
- **Cardinality:** one-to-one, one-to-many, many-to-one, or many-to-many.
- **Operation:** pure relocation when the original disappears; copy or
  propagation when it remains; split, merge, or redistribution when
  cardinalities differ.
- **Temporal scope:** direct when observed between adjacent revisions, or
  composite when inferred across a longer history interval.
- **Evidence:** text, normalized syntax, structural similarity, semantic
  analysis, historical provenance, or human judgment.
- **Confidence and ambiguity:** unique, ranked, threshold-accepted, grouped but
  unpaired, or manually confirmed.

For example, “a cross-file, one-to-many Type-2 copy of a function observed
between adjacent revisions” communicates substantially more than “a moved
clone.” Keeping these axes separate also permits tools with different goals to
share the core taxonomy without adopting one detector's data model.

### 2.3.7 Candidate, pair, and group

A **move candidate** is a source fragment considered as one possible endpoint
of a move. A **move pair** is one accepted directional relationship between an
earlier and later candidate. A **move group** contains candidates that share one
move identity when the evidence supports multiple sources, multiple
destinations, or an unresolved set of possible pairings.

These definitions are general. In srcMove specifically, a candidate is selected
from a `diff:delete` or `diff:insert` region; a pair connects deleted and
inserted candidates; and a group shares an `mv:id`. A many-to-many group does
not imply that srcMove recovered a unique historical pairing for every member.

### 2.3.8 General uses of the taxonomy

The taxonomy can support several activities beyond this implementation:

1. **Dataset construction.** Ground-truth datasets can label transformation
   type separately from granularity, scope, cardinality, and evidence source.
2. **Detector evaluation.** Studies can report detection and classification by
   type instead of pooling exact relocations with substantial rewrites.
3. **Tool interoperability.** Differencing and refactoring tools can exchange a
   shared type while retaining detector-specific scores and evidence.
4. **History mining.** Empirical studies can compare the frequency and location
   of different move forms without treating every deletion/insertion pair as
   equivalent.
5. **Visualization and review.** Interfaces can display why a relationship was
   classified, distinguish moves from copies, and expose ambiguous groups.
6. **Research comparison.** New algorithms can state which move categories and
   orthogonal dimensions they support, making scope differences explicit.

A standalone paper could formalize this taxonomy, compare it systematically
with clone and refactoring classifications, validate whether independent
reviewers can apply it consistently, and publish a curated example set.
**[PAPER TODO: define annotation guidance, boundary cases, reviewer study,
agreement measure, and representative examples for all types and dimensions.]**

### 2.3.9 Mapping the taxonomy to srcMove

srcMove provides one operationalization of the proposed taxonomy. Its exact
canonical representation approximates Type-1; its consistent name and literal
normalization approximates Type-2; and its bounded statement/block and token
sequence comparison approximates Type-3. For either Type-3 representation, the
longest common subsequence must cover at least 70 percent of both sequences,
subject to element-kind and size constraints. Chapter 4 defines these rules in
full.

An implementation label is evidence under one declared model, not a universal
truth about the move. A pair rejected by srcMove may still be a Type-3 move
under another defensible representation or a Type-4 move supported by history
or semantic evidence. Conversely, a syntactically accepted pair is not proven
to be one historical entity without a suitable provenance oracle.

### 2.3.10 Relationship to clone classification

A clone relationship states that two fragments are sufficiently similar under
a dataset or detector's definition. It does not state that one fragment moved,
that either historically preceded the other, or that a developer intended a
relocation. Move classification adds direction, changed location, and a
continuity claim.

Clone categories remain useful evidence for controlled experiments because
their similarity strata resemble parts of the proposed transformation
taxonomy. BigMoveBench makes that use explicit by constructing a synthetic
before/after relocation from two independently existing fragments. The
construction supplies the move relationship for the experiment; the original
clone label alone does not.

## 2.4 Related differencing and move-detection systems

The final review should organize systems by their evidence and assertions
rather than present only a chronological list.

### 2.4.1 Text and token differencing

Textual systems compare characters or lines; token systems remove some
formatting sensitivity while retaining a sequential representation. Their
advantages often include language independence, simple inputs, and familiar
output. Their limitations for this thesis concern structural boundaries and
relationships across separated regions. **[CITATION NEEDED: selected primary
systems and evaluations]**

### 2.4.2 Tree and structured differencing

Tree-oriented systems match nodes and produce operations such as insertion,
deletion, update, and move. They are the closest algorithmic comparison to
srcMove, but a fundamental boundary differs: srcMove post-processes regions
produced by another differencing engine instead of constructing a complete tree
mapping between revisions. Relevant comparisons include node granularity,
mapping constraints, move semantics, cross-file behavior, ambiguous matches,
and cost. **[CITATION NEEDED: primary papers for each selected tree
differencer]**

Tree-based clone detection provides a related but distinct comparison.
Deckard represents syntax subtrees with characteristic vectors and uses
approximate vector clustering to retrieve structurally similar fragments
efficiently. That approach is relevant to srcMove's Type-3 representation and
candidate-retrieval problem, particularly as an alternative to exhaustive
pairwise tree comparison. It does not by itself establish temporal direction,
disappearance at a source, appearance at a destination, or whether a similar
fragment is a move rather than a surviving copy. Those claims require revision
evidence and selection rules around the clone detector. **[CITATION: Jiang,
Misherghi, Su, and Glondu, “DECKARD: Scalable and Accurate Tree-Based Detection
of Code Clones,” ICSE 2007; primary paper:
https://web.cs.ucdavis.edu/~su/publications/icse07.pdf]**

### 2.4.3 Refactoring detection

Refactoring detectors identify transformations such as moving or renaming
methods and classes. Their output can encode stronger domain concepts than
srcMove's syntactic relationships, often using declarations, signatures, or
repository context. srcMove can annotate smaller structural fragments and does
not assert behavior preservation or refactoring intent. **[CITATION NEEDED:
primary refactoring-detection systems and evaluations]**

### 2.4.4 Origin and history analysis

History-aware systems trace entities or lines across revisions and may use
multiple commits, repository metadata, or change context. srcMove History also
analyzes adjacent revisions, but its observations derive from srcDiff and
srcMove outputs rather than a complete independent origin model. Related work
should compare the unit of continuity, use of intermediate revisions, oracle,
and treatment of copies and ambiguity. **[CITATION NEEDED: origin-analysis and
history-aware differencing literature]**

### Comparison framework

| Dimension | Question |
| --- | --- |
| Input representation | Lines, tokens, XML structure, AST, graph, or history? |
| Candidate granularity | Which fragments or entities can be related? |
| Move semantics | Syntactic similarity, node continuity, copy, or refactoring? |
| Cross-file support | Can source and destination belong to different files? |
| Matching method | Equality, normalization, similarity, optimization, or learned score? |
| Ambiguity policy | How are repeated or many-to-many candidates handled? |
| Evaluation | Which dataset, oracle, metrics, and denominators are used? |
| Cost | What time, memory, or scaling tradeoffs are reported? |

TODO: Build this matrix from primary sources before making comparative novelty
or superiority claims. Feature absence must be verified against the evaluated
version of each tool.

## 2.5 Clone benchmarks and BigCloneBench

BigCloneBench provides labeled pairs of Java fragments drawn from IJaDataset,
with clone categories and metadata. BigCloneEval uses these reference pairs to
evaluate clone detectors, and the database also includes a known-false-positive
population. **[CITATION NEEDED: primary BigCloneBench, IJaDataset, and
BigCloneEval publications plus official documentation]**

The dataset is useful here because it offers concrete Java fragments at scale,
declared strata related to srcMove's matching goals, and stable identifiers and
source ranges for auditable selection. It does not natively contain before/after
move edits. BigMoveBench therefore extracts both fragments in a pair, places
the first in an old source layout and the second in a new destination layout,
then runs srcDiff and srcMove. This measures whether a complete synthetic
payload is exposed, detected, and classified under a strict oracle. It cannot
establish the prevalence of moves, developer intent, or detector-wide precision.

Known-false-positive pairs require similarly narrow interpretation. Testing
whether srcMove avoids linking each complete pair yields a whole-fragment
rejection rate for that population. It does not prove the fragments share no
legitimate moved child constructs. Chapter 5 defines selection, deduplication,
direction, eligibility, scoring, and provenance. Final dataset counts must come
from frozen manifests rather than being treated as timeless constants.

## 2.6 Visualization of structured changes

Raw structured differences are designed for machine processing but can be hard
to inspect directly. Relevant systems include side-by-side text diffs, syntax-
or AST-aware views, refactoring summaries, provenance views, and coordinated
multi-view interfaces. The final review should ask what each view makes visible,
how selections are synchronized, how cross-file relationships are represented,
and whether usability claims were tested with users. **[CITATION NEEDED: primary
research on structured change and refactoring visualization]**

srcVisual addresses a concrete need in this toolchain. Its backend constructs
one normalized payload from final annotated XML, and its frontend derives
synchronized XML, tree, source, diff, and move views from that payload. File
ownership and directional links are especially important for cross-file moves.
This is an engineering contribution. Screenshots and feature demonstrations do
not establish improved comprehension or usability without a suitable study.

## 2.7 Chapter synthesis and open evidence

The literature review should locate srcMove along three axes: it uses structured
source evidence but post-processes an existing diff; it reports operational
syntactic categories rather than semantic intent; and it preserves an XML
document for downstream inspection. Whether this combination is novel, and
relative to which systems, must be established from the completed literature
matrix rather than asserted from implementation alone.

- TODO: Complete the literature matrix using primary papers and official tool
  or dataset documentation.
- TODO: Decide whether university formatting warrants separate background and
  related-work chapters.
- TODO: Verify that final move-group terminology matches result schemas and
  Chapter 4.
- TODO: Add a concise ecosystem figure without duplicating internal
  architectures.
