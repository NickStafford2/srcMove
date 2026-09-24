# Chapter 4: srcMove

## 4.1 Chapter purpose

srcMove is the primary software contribution of this thesis. It is a C++
post-processor that consumes the structured XML produced by srcDiff, identifies
deletion and insertion regions that plausibly represent the same relocated
source construct, and writes those relationships back into the original XML.
The central design decision is therefore one of composition: srcMove does not
replace srcDiff or compute a second source-code difference. It adds a move
interpretation to evidence that srcDiff has already exposed.

This distinction defines both the contribution and its boundary. srcMove can
associate regions across different files because an archive-form srcDiff
document contains all participating file units in one structured input. At the
same time, srcMove cannot recover a move whose deletion or insertion is absent
from that input. The implementation is best understood as a deterministic
classification and annotation pipeline over srcDiff regions, not as a general
purpose differencer or a reconstruction of developer intent.

Chapter 2 proposes Type-1 through Type-4 as a general taxonomy of moves. This
chapter describes srcMove's particular operationalization of Types 1 through 3.
The implementation thresholds and canonical forms make those concepts
executable, but they do not define the only valid detector for each type.

## 4.2 Requirements and design goals

The design grew from several requirements that are difficult to satisfy with a
raw-text search alone. First, the tool must preserve the srcDiff document so
that existing consumers can continue to inspect its source structure and diff
markup. Second, it must treat archive inputs as a single search space, because a
move can begin in one file and end in another. Third, it must distinguish
literal equality from similarity introduced by consistent renaming or bounded
editing. A consumer should be able to tell which kind of evidence justified a
reported move.

These requirements lead to the following goals:

- retain srcML structure and unmodified srcDiff content in the output;
- support both single-file units and multi-file archives;
- choose meaningful source constructs, with statements as the default minimum
  granularity;
- report exact, Type-2, and Type-3 relationships as different match kinds;
- use hashes for efficient lookup without treating a hash collision as proof of
  equality;
- make selection and output deterministic for a fixed input and program
  revision; and
- retain enough evidence for testing, BigMoveBench, repository-history
  analysis, performance experiments, and srcVisual.

The implementation deliberately does not promise semantic equivalence.
Normalized names and literals are lexical abstractions, and the Type-3 matcher
measures similarity between srcML-derived sequences. Neither establishes that
two fragments have identical runtime behavior. The output is evidence for a
move, not proof of the developer's intention.

## 4.3 Input and output model

A srcDiff document represents changes using `diff:delete` and `diff:insert`
elements embedded in srcML. A single-file input has one source unit, while an
archive has an outer unit containing file units. In the archive form, the
`filename` associated with each inner unit supplies the ownership needed to
connect a deletion in one file to an insertion in another. During the first
pass, srcMove tracks this file identity together with each region's nesting
relationship while incrementally building candidate spans, XPaths, raw text,
and matching forms. Once a candidate is complete, the production pipeline
retains those derived values rather than a captured copy of its srcML event
sequence.

The output remains a srcDiff document. srcMove adds the namespace
`http://www.srcML.org/srcMove` and places three attributes on selected source
elements:

- `mv:id` identifies the move group shared by related deletions and insertions;
- `mv:to` gives a deletion's destination XPath or XPath union; and
- `mv:from` gives an insertion's source XPath or XPath union.

The following abbreviated example illustrates a one-to-one exact match. It is
illustrative rather than a complete srcDiff document.

```xml
<unit xmlns="http://www.srcML.org/srcML/src"
      xmlns:diff="http://www.srcML.org/srcDiff"
      xmlns:mv="http://www.srcML.org/srcMove">
  <diff:delete mv:id="97b1dcdaf"
               mv:to="/src:unit[1]/diff:insert[1]">int a;</diff:delete>
  <diff:insert mv:id="97b1dcdaf"
               mv:from="/src:unit[1]/diff:delete[1]">int a;</diff:insert>
</unit>
```

An annotation need not be placed on the diff wrapper. When a wrapper contains a
more precise structural candidate, such as a function or declaration statement,
srcMove annotates that child. This preserves the distinction between the
changed region supplied by srcDiff and the source construct selected as the
move unit.

## 4.4 Pipeline overview

For a normal annotated-XML run, srcMove makes two streaming passes with an
in-memory matching phase between them. Results-only execution uses the first
pass and the matching phase but omits the output pass.

1. **Stream regions and construct candidates.** As XML events arrive, srcMove
   tracks deletion and insertion nesting and archive-file ownership. It applies
   the leaf-region policy, rejects unsuitable fragments, recognizes preferred
   structural children, and incrementally builds the exact, Type-2, and Type-3
   representations. Completed candidates retain their spans, XPaths, raw text,
   and cached matching forms, not captured XML subtrees.
2. **Build groups in evidence order.** Exact matches are selected first,
   followed by Type-2 identities and then Type-3 similarities among candidates
   not already consumed.
3. **Resolve overlap and ambiguity.** Selection prevents a broad parent and its
   nested child from both describing the same evidence, and applies explicit
   rules to repeated candidates.
4. **Produce output.** In normal mode, the writer performs a second pass,
   preserves unmodified nodes, and inserts move attributes. With
   `--results-only`, srcMove materializes the JSON result from candidate-owned
   evidence without rereading and rewriting the XML.

This ordering is part of the algorithm rather than a presentation convenience.
A candidate supported by exact evidence should not be relabeled by a weaker
normalization or similarity rule. Likewise, an ambiguous Type-2 identity is not
silently converted into Type-3 merely because approximate pairing would force
a result.

**TODO (figure):** Draw the end-to-end pipeline and label the implementation
boundaries in `src/parse/diff_region.cpp`, `src/region_filter.cpp`,
`src/parse/canonical_subtree.cpp`,
`src/move_registry/content_group_builder.cpp`, and the annotation writer.

## 4.5 Candidate selection and granularity

A diff wrapper is not automatically a useful move unit. It may contain only
whitespace, a token fragment, several independent constructs, or a larger
region around the source element that a reader would actually describe as
moved. srcMove therefore starts from leaf diff regions and applies a candidate
policy before matching.

The default policy excludes whitespace-only payloads and fragments smaller than
a complete statement or declaration. For an eligible wrapper, the filter can
select preferred structural descendants such as functions, classes,
declarations, conditionals, and loops. This expansion is what allows a moved
function inside a broad deletion to be annotated as the function itself.
Statement-sized candidates must contain at least four srcML lexical text events,
and an eligible wrapper must contain a complete construct meeting the same
evidence floor. The threshold suppresses very low-information statements such
as `break;`, `return;`, or a short call whose recurrence is weak evidence of a
meaningful move.

Candidate expansion creates a hierarchy in which a parent and child may encode
overlapping evidence. Exact-group selection suppresses overlapping parent/child
candidates rather than reporting both as independent moves. The resulting
policy favors the most useful structural unit available without discarding the
ability to inspect the original diff wrapper.

The command-line option `--min-granularity fragment` restores raw diff fragments
for specialized investigations. Fragment mode is intentionally not the default:
matching punctuation or small token sequences would increase the number of
technically equal but substantively unhelpful relationships.

**TODO (figure):** Show one diff wrapper, its eligible structural children, and
the candidate retained after overlap suppression.

## 4.6 Type-1 and Type-2 canonicalization

### 4.6.1 Type-1 representation

The Type-1 representation asks whether two candidates retain the same
meaningful structure and text after presentation-only differences are removed.
It ignores the outer diff wrapper, comments, `diff:ws` nodes, and
formatting-only text. It retains identifiers, literals, keywords, operators,
and srcML element structure. Thus layout or comment changes do not prevent an
exact classification, while a changed identifier or literal still does.

Candidates are first indexed by a 64-bit FNV-1a hash of their canonical form.
That hash narrows the search but is not the equality predicate. Every bucket is
partitioned and confirmed using the complete canonical text. A collision can
therefore affect lookup cost but cannot by itself produce a reported move. The
candidate's srcML element kind also forms part of grouping, preventing
lexically similar constructs of different kinds from being conflated.

### 4.6.2 Type-2 representation

Type-2 matching represents consistent lexical variation without claiming full
semantic equivalence. Direct srcML `<name>` tokens are numbered by first
occurrence within each candidate. Repeated uses of the same name receive the
same number, so correspondence patterns remain visible even when the original
spelling changes. Literals are replaced by categories—integer, floating,
string, character, boolean, or null—while keywords, operators, and other source
tokens remain significant. Comments, formatting, and empty statements are
ignored. The resulting identity is a compact lexical form keyed by the
candidate's outer srcML element kind; it does not retain the complete nested
srcML structure.

For example, functions that consistently replace a parameter `count` with `n`
can receive the same normalized name pattern. Two functions whose uses do not
preserve that pattern should not become equal merely because both contain names.
This is the consistent Type-2 variant described in Section 2.3.3. It is stricter
than blind normalization, which replaces identifiers without preserving their
one-to-one correspondence. srcMove uses the consistent variant because a
reported move makes a continuity claim across revisions; retaining the pattern
of repeated and distinct names supplies stronger evidence than a shared token
skeleton alone.

Exact matches are removed before Type-2 grouping. An unambiguous normalized
delete/insert pair is selected directly. When both sides contain the same
multiplicity, srcMove can pair them deterministically by position. Other
ambiguous normalized groups are preserved as ambiguity rather than assigned
arbitrary relationships.

**TODO (figure):** Add a worked source/srcML example showing the exact form, the
first-occurrence name mapping, literal categories, and the resulting Type-2
identity.

## 4.7 Type-3 similarity

Type-3 matching considers eligible structural candidates left unmatched by the
stronger stages. It uses two cached sequence views derived from the Type-2
normalization. The coarser view divides normalized code at statement and block
boundaries (`;`, `{`, and `}`); the finer view retains a token sequence. Both
views preserve the consistent first-occurrence mapping of names. This keeps
identifier correspondence as evidence while permitting bounded additions,
deletions, or replacements within a moved construct.

Before computing sequence similarity, srcMove rejects candidates with
incompatible srcML element kinds or lengths outside the acceptance window. For
the remaining pair, let `A` and `B` be either corresponding sequence view and
let `L` be the length of their longest common subsequence. The view is accepted
when

```text
L / |A| >= 0.70  and  L / |B| >= 0.70,
```

which is equivalent to

```text
L / max(|A|, |B|) >= 0.70.
```

A candidate pair qualifies if either its statement/block view or token view
passes; the stronger of the two similarity scores orders the edge. Sequence
units are represented by 64-bit hashes, and the LCS implementation stores two
rows rather than a complete matrix. It also exits when the remaining rows
cannot reach the required common length. These choices reduce memory and avoid
work on pairs that cannot satisfy the threshold, but they do not establish a
general asymptotic or project-scale performance claim.

Accepted edges are sorted by similarity and then by size and candidate
identifier. A deterministic greedy pass selects one-to-one relationships. This
rule makes repeated execution stable, although it is not a claim that the
greedy pairing reconstructs the only possible developer intent. Threshold
selection must likewise be treated as an empirical design decision.

**TODO (evaluation):** Identify the tuning cases used to select the `0.70`
threshold and keep them separate from the frozen evaluation selection.

**TODO (figure):** Give one statement/block and token-sequence example, show its
LCS calculation, and distinguish an accepted pair from a size-window rejection.

## 4.8 Move groups, cardinality, and ambiguity

A candidate is one eligible deleted or inserted construct. A pair is a selected
one-to-one relationship. A move group is the reported collection of candidates
that share the same evidence identity. These distinctions matter when source
text is repeated. One deletion can correspond to several identical insertions,
several deletions can correspond to one insertion, and equal content can occur
many times on both sides.

srcMove classifies group cardinalities including one-to-one, many-to-many,
copy-or-repeat, delete-only, and insert-only cases. A reported group containing
both directions receives one `mv:id`. Each deletion lists the group's
destination XPath set in `mv:to`, and each insertion lists its source XPath set
in `mv:from`. For an ambiguous many-to-many exact group, these sets communicate
the supported relationship without inventing a unique pairing that the
available evidence does not justify.

Delete-only and insert-only groups remain useful to the JSON summary and to
diagnostics, but they are not annotated as moves because they do not connect
both sides. Type-3 differs by selecting deterministic one-to-one edges among
remaining candidates. This difference should be made explicit when downstream
analyses count groups, candidates, or pairs; those units are not
interchangeable.

**TODO (figure):** Diagram one-to-one, one-to-many, many-to-one, many-to-many,
and unmatched cardinalities, including their directional XPath sets.

## 4.9 Streaming implementation and performance model

srcMove is implemented in C++17 and uses libxml2 through srcReader's streaming
reader/writer facilities. The production input path fuses region recognition,
candidate selection, raw-text collection, and canonicalization into one XML
stream. It retains completed candidates, their canonical forms, lightweight
region bookkeeping, and group membership for global matching, but not captured
candidate event sequences or a complete in-memory XML tree. Under the default
leaf-only policy, the stream also releases a parent region's
candidate-construction state when a nested diff region makes that parent
ineligible.

For exact and Type-2 matching, hash indexes and full-representation partitioning
avoid an unrestricted delete-by-insert Cartesian product. Type-3 is inherently
more comparative, so the implementation reduces its search with element-kind
partitions, representation-specific size windows, cached normalized views, and
an early-exit two-row LCS. The `--profile` option exposes coarse stage timings
for repeatable measurement. Chapter 8 evaluates those costs on independent
workloads; this chapter limits itself to mechanisms intended to constrain them.

For annotated output, the two-pass design separates matching from
serialization. Selection can refer to stable candidate identifiers and XPath
evidence during the in-memory phase, while the writer can reproduce the
original stream and add only the attributes in the annotation plan. This
separation supports inspectability and reduces the risk that matching logic
accidentally rewrites unrelated XML. Consumers that need only machine-readable
results can use `--results-only` to skip serialization while preserving the
same matching phase.

## 4.10 Supporting srcReader improvements

Implementing srcMove required capabilities at the boundary between streaming
XML recognition and faithful rewriting. Those changes belong in this chapter
because they support the main system, but they should not be presented as an
independent research question. Their significance is architectural: general
reader/writer behavior should remain in srcReader rather than being recreated
as move-specific parsing code.

The final thesis must identify each limitation encountered, the exact srcReader
API or behavior added, and the srcMove path that depends on it. It must also
distinguish work merged into the srcReader repository from local workspace
patches, and explain any lifetime, ownership, compatibility, namespace, or
serialization constraints that shaped the integration.

**TODO (source audit):** Inventory the authored srcReader commits and record for
each one: commit identifier, API or behavior changed, motivating srcMove use,
focused srcReader test, corresponding srcMove integration test, and upstream or
local status. Do not replace this audit with a generic statement that srcReader
was improved.

**TODO (figure):** Draw the srcMove/srcReader/libxml2 boundary after the API
inventory is verified.

## 4.11 Annotation and result reporting

The annotation writer applies a plan during the second XML pass. It adds the
srcMove namespace at the root and decorates the selected start tags with the
group identifier and directional links. Because the selected candidate can be
a structural child, the output XPath may identify an element nested within a
diff wrapper. Existing attributes and unmodified nodes are preserved.

With `--results`, srcMove also emits JSON describing the run and its groups.
The result includes group match kinds, source and destination XPaths, raw texts,
candidate counts, and cardinality classifications. This machine-readable output
is the principal boundary used by BigMoveBench and repository-history analysis;
the annotated XML provides the corresponding structural evidence consumed by
inspection tools such as srcVisual. The two outputs are complementary: the JSON
supports aggregation, while the XML keeps the relationship attached to the
source representation from which it was derived.

**TODO (artifact):** Freeze the evaluated JSON schema and include a small,
version-matched example rather than copying a development artifact whose fields
may have changed.

## 4.12 Correctness testing

The test strategy separates algorithmic behavior from end-to-end research
evaluation. Canonicalization unit tests exercise which srcML events contribute
to exact and normalized identities. XML regression fixtures cover group
cardinalities, nesting, archive ownership, whitespace and comments, structural
child selection, Type-2 guards, Type-3 behavior, namespace output, and
directional annotations. Source-pair regression cases invoke srcDiff and
srcMove together on small before/after examples, including cross-file and
file-creation or deletion scenarios. Supporting Python tests cover benchmark
contracts, process handling, identity, provenance, and runners.

These tests establish that local rules behave as specified and remain stable
across changes. They do not estimate detection performance on a population of
moves. BigMoveBench supplies the controlled synthetic evaluation in Chapter 5,
and srcMove History supplies an observational view of repository revisions in
Chapter 7.

**TODO (evidence):** At the evaluated revision, record the test command, test
inventory, pass/fail outcome, platform, and srcReader revision. Cite a focused
test for every srcReader claim in Section 4.10.

## 4.13 Design implications and proposed successor

The implemented pipeline exposes a deeper distinction between move-candidate
validity, pair similarity, and final selection. A similarity method answers
whether two fragments resemble one another. It does not establish that the
first fragment disappeared, that the second newly appeared, or that the pair
should be preferred over overlapping parent or child pairs. These concerns are
especially visible in nested srcDiff markup.

srcDiff diff elements form revision-membership states. Content nearest to
`diff:delete` belongs only to the original revision, content nearest to
`diff:insert` belongs only to the modified revision, and content nearest to
`diff:common` belongs to both. An outer deleted structure can consequently
contain a common child that survives after the parent is removed, or an
inserted descendant that switches the combined XML into a new structural form.
The current leaf policy tracks nested insertions and deletions but does not
model `diff:common` as an ownership boundary. It can therefore include surviving
common text in an outer deletion or insertion candidate. This is an
implementation limitation, not a property that a stronger similarity function
can correct after candidate construction.

A proposed successor separates three stages. First, revision-aware candidate
construction would admit only complete, substantively deleted or inserted
constructs while retaining legitimate parents and children as alternatives.
Same-side nesting would not automatically discard a parent; common or
opposite-side material would instead mark a mixed boundary. Second, exact,
normalized, sequence, or tree-vector methods would emit evidence edges between
eligible deletions and insertions without immediately consuming overlapping
candidates. Third, hierarchical selection would choose a non-overlapping set
of edges. A strong parent match could replace several child matches, while the
children would remain available when the parent was mixed or lacked a coherent
destination.

This design also separates pair confidence from selection utility. Confidence
describes the credibility of one correspondence using similarity, structural
agreement, uniqueness, and ambiguity. Utility describes how well selecting
that edge explains the change, including substantive coverage and a penalty for
fragmenting one coherent move into several reports. The distinction prevents a
small exact child from automatically precluding a much larger, strongly
similar parent: exactness is stronger correspondence evidence, but it does not
determine the intended move boundary by itself.

The scalable form of this design must keep the candidate graph sparse. Exact
and normalized hashes, structural-kind partitions, size windows, and
fingerprint or approximate-neighbor indexes should precede expensive Type-3
verification. Deckard-style characteristic vectors are one candidate for this
retrieval and similarity stage, not a replacement for revision ownership or
move selection. Parent and child representations should share token ranges or
compositional summaries rather than copy every XML event into every open
ancestor.

These ideas are proposed work and must not be presented as behavior of the
evaluated implementation. Their canonical engineering plan, performance
constraints, and test gates are maintained in
[`doc/plans/move_detection_redesign.md`](../../plans/move_detection_redesign.md).

## 4.14 Limitations

srcMove inherits a hard candidate boundary from srcDiff. If srcDiff does not
represent the complete deletion and insertion in usable regions, srcMove cannot
match them. Its default granularity also excludes tiny fragments by design, so
the absence of a reported token-level move is not necessarily a detector
failure.

The three implemented match kinds are structural and lexical approximations.
Type-4 move continuity is outside srcMove's current scope. Type-3 uses a fixed
bounded-LCS rule rather than a
probabilistic confidence model, behavioral equivalence analysis, or learned
similarity function. Context such as locality, repository history, and call
relationships does not presently influence selection. Exact groups can express
ambiguous partner sets, while unequal or otherwise ambiguous normalized groups
are not fully disambiguated.

These limits are useful boundaries for the thesis claim. The contribution is a
deterministic method for recovering inspectable move relationships from
structured diff evidence, including cross-file relationships; it is not a
complete account of all refactorings or developer intent.

## 4.15 Evidence still required for the final chapter

- **TODO (citations):** Cite primary work on source-code differencing, move
  detection, clone categories, tree/sequence similarity, and srcML/srcDiff.
- **TODO (revision):** Record the exact srcMove, srcDiff, srcReader, and srcML
  revisions used for the thesis evaluation.
- **TODO (figures):** Produce the pipeline, candidate hierarchy,
  canonicalization, Type-3, cardinality, and integration figures listed above.
- **TODO (design history):** Link each important algorithmic choice to a test,
  failure mode, experiment, or implementation constraint rather than presenting
  it as self-evident.
- **TODO (results boundary):** Keep publication results in Chapters 5, 7, and 8;
  this chapter should describe the evaluated algorithm, not silently mix in
  exploratory measurements.

Final technical wording must be checked against
[`doc/architecture.md`](../../architecture.md) and the frozen source revision.
