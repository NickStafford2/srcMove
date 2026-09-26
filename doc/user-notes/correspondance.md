# Correspondence before change classification

Status: proposed design direction. This document records the rationale,
semantics, decision points, and implementation path for a possible future
srcMove classifier. It does not describe the full current behavior. The
verified implementation remains documented in
[`doc/architecture.md`](../architecture.md), and the existing candidate and
selection redesign remains documented in
[`doc/plans/move_detection_redesign.md`](../plans/move_detection_redesign.md).

## Central idea

Move detection contains two separate problems:

1. **Correspondence:** do an earlier and later source construct represent the
   same continuing code?
2. **Change classification:** if they correspond, what happened to that code?

The current exact, Type-2, and Type-3 matchers answer the first question. A
match alone does not establish relocation.

```text
OLD foo()  <---------->  NEW foo()
             correspondence
```

A second stage should classify the observed relationship:

```text
                           correspondence
                                 |
                         change classifier
                                 |
        +-------------+----------+----------+-------------+
        |             |          |          |             |
   stationary    relocated    copied   restructured   ambiguous
```

The diagram shows alternative classifications, not a hierarchy. `ambiguous`
is an epistemic result: the available evidence does not justify one of the
other conclusions.

This separation prevents a strong content match from being mistaken for proof
of movement. It also gives candidate generation, matching, classification, and
hierarchical selection one clear responsibility each.

## Why the distinction matters

srcMove consumes srcDiff XML. It does not independently compare two complete
source trees. srcDiff may expose unchanged code as a deletion and insertion
when it chooses a coarse replacement or represents the two sides with
different XML nesting. Exact content inside those regions is strong
correspondence evidence, but the code may still occupy the same logical place.

Real Notepad++ comparisons demonstrated several distinct situations that a
binary `move`/`not move` decision obscures:

- unchanged statements retained their order while nearby edits shifted their
  line numbers;
- exact statements appeared under incompatible srcDiff XML paths even though
  they looked stationary in the source view;
- existing statements became wrapped in a newly inserted conditional;
- one earlier statement appeared to correspond to more than one later
  occurrence; and
- genuine cross-function and cross-file relocations remained straightforward.

These are not all matching failures. They are different interpretations of
valid or plausible correspondences.

## Terminology

### Correspondence evidence

Correspondence evidence describes why two endpoints may represent continuing
code:

- **Exact (Type 1):** identical under srcMove's comment- and
  formatting-insensitive exact representation.
- **Type 2:** identical under consistent identifier and literal normalization.
- **Type 3:** sufficiently similar under the declared structural sequence
  model.

These are evidence classes, not proof that a move occurred. For example, a
Type-2 correspondence in the same structural slot is naturally interpreted as
an in-place modification.

### Proposed change classifications

#### Stationary

The construct corresponds across revisions and its logical location remains
stable. “Stationary” refers to location, not text: an exact correspondence may
be unchanged, while a Type-2 stationary correspondence may have been renamed
or edited in place.

Evidence may include the same semantic container, the same surrounding common
anchors, and unchanged order relative to stable siblings. Line-number changes
alone do not imply relocation.

#### Relocated

The source occurrence disappears and the corresponding destination occurrence
occupies a meaningfully different structural location. Strong evidence
includes a changed file, a changed semantic container, or crossing a stable
sibling within one container.

`relocated` is the classification that should normally become a user-visible
srcMove move.

#### Copied

The source occurrence survives while a corresponding occurrence appears at a
new location. Copy classification therefore requires evidence about surviving
source content, not just a deletion/insertion pair.

The current candidate pool is primarily built from deleted and inserted
regions. Reliable copy detection may require a compact inventory of common
constructs or another way to establish that the source occurrence remains.
Repeated exact delete/insert groups alone do not prove copying.

#### Restructured

The construct remains in the same logical source interval, but its ancestor
structure changes. Wrapping existing statements in a new `if`, adding a
`try`, or removing a redundant block are representative cases.

This category avoids calling every parent change a relocation. A future policy
must explicitly decide which ancestor changes are merely restructuring and
which move code into a genuinely different semantic container.

#### Ambiguous

The system finds correspondence evidence but cannot justify a unique or
reliable change classification. Causes include repeated code, conflicting
endpoints, missing anchors, inconsistent srcDiff structure, and insufficient
context.

Ambiguity must not be resolved merely to force an output. It should remain
available in diagnostics and evaluation even if normal annotated XML reports
only accepted relocations.

### Possible future extensions

The five initial outcomes are deliberately small. One-to-many and many-to-one
histories may later justify explicit `split`, `merged`, or `extracted`
classifications. Until those semantics are defined and tested, such cases
should remain copied or ambiguous rather than being forced into `relocated`.

## Orthogonal dimensions

Each correspondence has dimensions that should remain separate from its final
classification:

| Dimension | Representative values |
| --- | --- |
| Evidence | exact, Type 2, Type 3 |
| Cardinality | one-to-one, one-to-many, many-to-one, many-to-many |
| Scope | same block, same function, different function, different class, different file |
| Order | unchanged, crossed stable sibling, unknown |
| Ancestors | unchanged, wrapped, unwrapped, incompatible, unknown |
| Source survival | disappeared, remained, unknown |
| Granularity | statement, declaration, function, type, file |
| Certainty | supported, conflicting, insufficient |

Keeping these axes explicit makes results explainable and permits later policy
changes without redefining correspondence.

## Operational definition of a move

A conservative initial definition is:

> A reported move is a one-to-one correspondence for which the source
> occurrence disappears and positive evidence shows that the destination
> occupies a different structural location.

This definition intentionally does not claim to reconstruct the developer's
historical cut-and-paste action. Two snapshots usually support claims about
observable structural change, not private intent.

Positive relocation evidence is preferable to treating the absence of
stationary evidence as movement. When context is insufficient, the result
should be `ambiguous` rather than automatically `relocated`.

## Context evidence

A future classifier should prefer durable structural evidence in roughly this
order:

1. **File identity.** A unique correspondence across files is strong
   relocation evidence.
2. **Semantic container.** A changed function, method, class, or namespace is
   strong evidence when those containers themselves can be mapped reliably.
3. **Common anchors.** The nearest reliable unchanged construct before and
   after an endpoint identifies a stable interval despite line displacement or
   inconsistent inner XML.
4. **Relative sibling order.** Crossing a mapped sibling establishes
   same-parent reordering.
5. **Ancestor-chain change.** A changed wrapper inside an otherwise stable
   anchor interval supports `restructured` rather than necessarily
   `relocated`.
6. **Line or byte distance.** Distance may break ties but should not establish
   movement by itself.

No single signal is universally sufficient. In particular, implementations
must not assume that:

- a delete/insert pair is automatically a move;
- different line numbers establish relocation;
- equal raw XPaths establish stationarity;
- different raw XPaths establish relocation;
- an immediate-parent change is always a move; or
- exact text uniquely identifies an endpoint when the text repeats.

## Proposed classification policy

The first classifier should use ordered, explainable rules rather than another
opaque score:

```text
if correspondence is not uniquely resolvable:
    ambiguous
else if source demonstrably survives at its original location:
    copied
else if same stable anchor interval and meaningful ancestor chain changed:
    restructured
else if same semantic container and same stable anchor interval:
    stationary
else if file or semantic container changed:
    relocated
else if candidate crossed a stable sibling:
    relocated
else:
    ambiguous
```

The order is policy and must be tested. For example, source survival should
prevent an additional occurrence from being mislabeled as a simple move, while
wrapping should be recognized before a changed immediate parent triggers a
relocation decision.

The current implementation contains a much narrower safeguard: a unique exact
pair in adjacent delete/insert regions is rejected when both endpoints have the
same nested structural-parent key. That rule is useful evidence but is not a
complete classifier. Real srcDiff output can encode stationary endpoints under
incompatible paths, so a future implementation should convert the safeguard
into one classification rule rather than continually adding special-case move
rejections.

## Proposed pipeline

```text
srcDiff XML
    |
    v
candidate extraction
    |
    v
correspondence construction
  exact / Type 2 / Type 3
    |
    v
cardinality and conflict analysis
    |
    v
change classification
  stationary / relocated / copied / restructured / ambiguous
    |
    v
hierarchical explanation selection
  parent versus descendants; non-overlap
    |
    v
report accepted relocations
  retain other classifications in diagnostics
```

The classification stage should not change canonicalization or manufacture new
content matches. Correspondence asks *what continues*; classification asks
*what happened*; hierarchy selection asks *which granularity best explains the
change*.

## Suggested data model

Names are illustrative and should be reconciled with existing repository
types before implementation.

```cpp
enum class correspondence_kind {
  exact,
  type2,
  type3,
};

enum class change_kind {
  stationary,
  relocated,
  copied,
  restructured,
  ambiguous,
};

struct location_context {
  file_id file;
  optional_id semantic_container;
  optional_id previous_common_anchor;
  optional_id next_common_anchor;
  ancestor_summary ancestors;
  sibling_order_summary order;
};

struct correspondence {
  endpoint_set before;
  endpoint_set after;
  correspondence_kind evidence;
  cardinality_kind cardinality;
  change_kind change;
  location_context before_context;
  location_context after_context;
  classification_reason reason;
};
```

Classification reasons should be machine-readable and stable enough for tests,
for example `different_file`, `different_container`, `same_anchor_interval`,
`ancestor_wrapped`, `source_survives`, and `insufficient_context`.

## Mapping onto the current implementation

A future implementation should preserve the existing phase boundaries where
possible:

- [`src/region_filter.cpp`](../../src/region_filter.cpp) can collect lightweight
  container, anchor, and ancestor summaries while it already streams the
  document. It should not retain the full XML tree solely for classification.
- [`src/move_registry/content_group_builder.cpp`](../../src/move_registry/content_group_builder.cpp)
  can stop treating every accepted evidence proposal as an already interpreted
  move. Its exact, Type-2, and Type-3 construction remains useful.
- A dedicated classifier module should consume correspondences and context and
  produce `change_kind` plus a reason. Keeping this separate prevents location
  policy from leaking into canonicalization and similarity code.
- Existing hierarchy and overlap selection should operate on classified
  correspondences. Normally only `relocated` correspondences compete for move
  annotations, while restructuring may affect parent/child explanation.
- [`src/summary.hpp`](../../src/summary.hpp) and the JSON writer can expose
  classifications incrementally. Existing `moves` output can remain compatible
  while an opt-in `correspondences` diagnostics section is evaluated.
- The annotation writer should continue to annotate only relationships that
  the declared output policy accepts as moves.

## Incremental implementation plan

This redesign should be delivered as a sequence of small, independently
testable changes. Do not replace production output in one step, and do not make
later phases prerequisites for learning from earlier ones.

### Phase 0: define the vocabulary and test oracle

Write reviewer-owned examples for each classification before implementing the
classifier. For every fixture, record separately:

- which regions correspond;
- why that correspondence is credible;
- which structural dimensions changed; and
- which final label is expected.

Resolve the highest-impact boundary cases, especially wrapping, copying,
repeated content, and same-parent reordering. This gives later work a stable
oracle and prevents the implementation from defining the semantics by
accident.

### Phase 1: capture context without changing decisions

Introduce the smallest context representation needed for classification, such
as enclosing construct, structural parent, nearby stable anchors, sibling
position, branch or role, and file identity. Populate it for existing Type-1
and Type-2 candidates, but leave current selection and output unchanged.

This phase is complete when context can be inspected and tested independently
of move classification.

### Phase 2: run an observation-only classifier

Build correspondence records and proposed classifications beside the current
algorithm. Diagnostics should make disagreements explicit, for example:

```json
{
  "current_result": "move",
  "proposed_classification": "stationary",
  "classification_reason": "same_anchor_interval"
}
```

The existing `moves` output remains authoritative. Use the shadow results to
measure disagreement on small fixtures and real history pairs before changing
behavior.

The current narrow stationary filter should become the first explicit rule in
this classifier rather than remain a silent rejection. Conceptually, its
record would state:

- correspondence evidence: `exact`;
- change classification: `stationary`; and
- reason: `adjacent_same_structural_parent`.

### Phase 3: adopt classification for Type-1 only

Let the new classifier control output for unique exact correspondences first.
Type-1 offers the clearest correspondence evidence, so failures in this phase
mostly expose classification-policy problems rather than matching problems.

Initially support only:

- `stationary` when structural location is effectively unchanged;
- `relocated` when the location change is clear; and
- `ambiguous` when evidence is insufficient or contradictory.

Require positive relocation evidence and prefer `ambiguous` to a weak move
claim. Keep Type-2 behavior on the existing path until Type-1 results are
understood and stable.

### Phase 4: extend the same classifier to Type-2

Reuse the Type-1 context and classification model for strong non-exact
correspondences. Do not invent a separate definition of movement for Type-2;
only its correspondence evidence and confidence should differ.

Adopt Type-2 output conservatively, with explicit confidence thresholds and
diagnostics for cases that fall back to `ambiguous`. Evaluate correspondence
quality separately from classification quality so a poor match is not mistaken
for a poor definition of movement.

### Phase 5: add restructuring dimensions

Add ancestor summaries and explicit wrap/unwrap contracts only after the basic
stationary-versus-relocated decision is reliable. Classify structural parent,
branch, ordering, and control-flow changes as restructuring where the evidence
and policy are clear. Otherwise preserve the dimension values and classify the
case as `ambiguous`.

### Phase 6: add copies and relationship cardinality

Handle `copied` last. Add the minimum common-construct inventory needed to
establish source survival, then represent one-to-many and many-to-one
correspondence explicitly. Define provenance and tie-breaking policy before
distinguishing true copies from repeated or unresolved exact groups. Consider
`split` and `merged` only if reviewed examples justify expanding the taxonomy.

### Delivery milestones

Each milestone should be reviewable and releasable on its own:

1. Context and shadow diagnostics exist; public output is unchanged.
2. The classifier controls Type-1 results.
3. The classifier controls sufficiently confident Type-2 results.
4. Restructuring dimensions and labels are available.
5. Copy detection and non-one-to-one correspondence are represented.

At every milestone, preserve previous behavior behind a temporary comparison
path until the new behavior has been evaluated. Remove that path once it no
longer provides diagnostic value; it should not become a permanent second
algorithm. Emit only accepted relocations as normal moves. Preserve other
correspondence classes in results JSON or diagnostics, and update srcVisual
deliberately rather than relying on old move annotations to encode new
meanings.

## Test strategy

The semantic tests should cross correspondence evidence with change outcome:

| Evidence | Scenario | Expected classification |
| --- | --- | --- |
| exact | lines inserted above otherwise stable statement | stationary |
| exact | same statement moved to another function | relocated |
| exact | statement reordered past stable sibling | relocated |
| exact | statements wrapped by a new conditional | restructured |
| exact | source remains and another occurrence appears | copied |
| Type 2 | identifier or literal changed in the same slot | stationary |
| Type 2 | renamed statement moved to another function | relocated |
| exact | repeated endpoints without unique pairing | ambiguous |

Every contextual test intended to exercise srcMove must assert its precondition.
For example, a missed-common regression should verify that srcDiff actually
exposed the target as deleted and inserted; otherwise an upstream srcDiff
improvement could make the test pass without exercising the classifier.

Tests should include counterexamples that constrain overbroad rules:

- a true short-distance reorder;
- a cross-file move with no useful local anchors;
- a moved parent whose children must not become separate stationary results;
- identical repeated statements in different contexts;
- a wrapper insertion that retains the child's stable anchor interval; and
- incompatible srcDiff XML paths for visually stationary source.

The move-selection semantic benchmark is the natural home for small handcrafted
contracts. Source-generated policy cases should validate end-to-end behavior,
and reviewed Notepad++ history pairs should remain evaluation evidence rather
than being the only oracle.

## Invariants for future implementers

- Matching quality and change classification must remain independently
  observable.
- Location classification must not feed back into canonical identity and make
  otherwise unrelated code correspond.
- A lack of stationary evidence is not positive relocation evidence.
- Ambiguous relationships must not be paired by document order merely to
  produce a result.
- Line distance is never sufficient by itself.
- Cross-file moves must remain detectable when local context is absent.
- Parent/child selection must avoid reporting both an enclosing explanation and
  descendants for the same evidence.
- Results must remain deterministic.
- Context capture must preserve the streaming memory model unless measurements
  justify a larger representation.
- Policy thresholds and classification reasons must be declared and tested,
  not tuned silently against one repository.

## Decisions that require human review

Before production behavior changes, answer these questions explicitly:

1. Does wrapping otherwise stationary code in `if`, `try`, or a new block count
   as restructuring in all cases, or can some wrapper changes constitute a
   relocation?
2. Should normal srcMove output include copies, or should copies exist only in
   JSON diagnostics and srcVisual?
3. Should ambiguous correspondences be visible by default, available only on
   request, or omitted from normal output?
4. Is a changed semantic container always sufficient relocation evidence when
   the surrounding source order is stable?
5. Which constructs are reliable common anchors: statements, declarations,
   functions, or only named semantic containers?
6. How should a moved parent affect the classification of its children?
7. Should `restructured` be one result or should wrapping, unwrapping,
   extraction, and inlining be separate classifications?
8. When Type-2 evidence is stationary, should the display call it “stationary
   Type 2,” “modified in place,” or expose both labels?

Record answers here before coding them so future agents do not infer policy
from incidental regression output.

## Effort and risk

A three-way prototype (`stationary`, `relocated`, `ambiguous`) for unique Type-1
and Type-2 correspondences is likely a small multi-day change. A robust
classifier with anchors, restructuring, copy detection, output evolution, and
real-history evaluation is closer to a one- or two-week focused effort.

The main risk is not implementation cost. It is encoding an unclear definition
of movement and then treating generated outputs as ground truth. Phase 0 and an
observation-only classifier reduce that risk.

## Relationship to prior work

The broad pattern—establish mappings, then derive edit actions—is consistent
with remembered tree-differencing, refactoring-detection, version-control
rename/copy, and clone-evolution approaches. The explicit five-way taxonomy and
its application to srcDiff output should not be claimed as novel without a
literature review. Thesis prose must replace this recollection with verified
primary citations.

The potentially distinctive contribution is not merely adding another matcher.
It is making correspondence evidence, structural change classification,
cardinality, ambiguity, and hierarchical explanation separately observable and
testable.
