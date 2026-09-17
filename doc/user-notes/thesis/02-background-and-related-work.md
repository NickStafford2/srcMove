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

## 2.3 Move and clone terminology

The following definitions support the implementation and evaluation. They must
not be silently substituted for definitions used by other tools or datasets.

### 2.3.1 Candidate, pair, and group

A **diff region** is a `diff:delete` or `diff:insert` region in srcDiff input. A
**move candidate** is an eligible deleted or inserted structural fragment
selected from such a region. Under the default policy, candidates are
statement-sized or larger and meet structural and lexical evidence floors; raw
fragments are available only through a non-default option.

A **move pair** is one accepted relationship between a deleted and an inserted
candidate. A **move group** is the output grouping identified by one move
identifier. Its cardinality may be one-to-one, one-to-many, many-to-one, or
many-to-many. In ambiguous groups, shared identity and partner XPath sets do not
imply that srcMove recovered a unique historical pairing for every member.
Repeated content may also produce unequal multiplicities without proving which
occurrence was copied from which source.

### 2.3.2 srcMove match categories

An **exact (Type-1) match** is equality under srcMove's comment- and
formatting-insensitive canonical representation. It ignores the outer diff
wrapper, comments, `diff:ws` elements, and formatting-only text while retaining
meaningful tokens and srcML structure. “Exact” therefore means exact under this
representation, not byte-for-byte identity.

A **Type-2 match** is equality under srcMove's consistent lexical
normalization. Direct srcML name tokens are numbered by first occurrence,
literals are replaced by categories, and comments, formatting, and empty
statements are ignored. Other tokens, operators, structure, and the pattern of
name reuse remain evidence. This does not establish variable binding,
behavioral equivalence, or a semantics-preserving rename.

A **Type-3 match** is an eligible unmatched pair accepted by srcMove's bounded
sequence-similarity rule. The implementation compares a statement/block
sequence and a finer token sequence. For either representation, the longest
common subsequence must cover at least 70 percent of both sequences; equivalently,
it must cover at least 70 percent of the longer sequence. Element-kind and size
constraints bound the comparison, and deterministic greedy selection chooses
one-to-one edges after Type-1 and Type-2 matching. This is srcMove's classifier,
not an invocation of an external detector.

**Type-4** denotes semantic similarity without sufficient syntactic similarity
in common clone taxonomies. It is outside srcMove's implemented scope.
**[CITATION NEEDED: primary clone taxonomy sources; compare their definitions
with the operational definitions above]**

### 2.3.3 Clones are not historical moves

A clone relationship states that two fragments are sufficiently similar under
a dataset or detector's definition. It does not state that one fragment was
deleted and reinserted at the other's location, that either historically
preceded the other, or that a developer intended a move. Clone categories still
provide useful controlled strata for exercising srcMove's matching categories.
BigMoveBench makes that use explicit by constructing a synthetic before/after
edit from two independently existing fragments. Results are therefore synthetic
detection-and-classification results, not historical-move recall.

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
