# Correspondence before change classification

Status: active roadmap. Delivery milestone 1 (context and shadow diagnostics)
is complete in srcMove 0.4.0, and Phase 3 unique Type-1 production adoption is
complete in srcMove 0.5.0, including source-input normalization (3.2) and
retained real-history evaluation (3.3). Phase 4 unifies Type-1/2/3 movement
classification; Phase 5 addresses repeated groups; Phase 6 evaluates and
consolidates the system. Phase 4.1 production Type-2 adoption is complete after
repairing common conditional anchors and reviewing normalization fixtures.
Matching coverage remains separate from move output. Historical improvement is
not yet established. Phases 4.2, 5, and 6 are not implemented. This
document records rationale, semantics, decision points, and future
implementation phases rather than the full current behavior. The verified
implementation remains documented in
[`doc/architecture.md`](../architecture.md), and the existing candidate and
selection redesign remains documented in
[`doc/plans/move_detection_redesign.md`](move_detection_redesign.md).

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
        +-------------+----------------+-------------+
        |             |                |             |
   stationary    relocated       restructured    ambiguous
```

The diagram shows alternative classifications, not a hierarchy. `ambiguous`
is an epistemic result: the available evidence does not justify one of the
other conclusions.

This separation prevents a strong content match from being mistaken for proof
of movement. It also gives candidate generation, matching, classification, and
hierarchical selection one clear responsibility each.

## Historical-analysis objective

The purpose is more useful historical analysis: distinguish real relocations
from edits in place without unnecessarily losing genuine moves. Fewer reported
moves, more `ambiguous` results, passing revised goldens, or a cleaner pipeline
alone do not establish improvement. Evaluate false moves and missed real moves
together, using reviewed source revisions independently of detector output.

Positive relocation evidence remains the output rule, but conservatism is not
the optimization target. When real moves become ambiguous, first investigate
missing context, correspondence quality, and selection conflicts. Add only
small, justified evidence improvements with positive and negative contracts;
do not silently relabel known moves as non-moves to make tests pass. If a
tradeoff remains, document which historical queries lose useful results and
review that tradeoff before adopting the change.

Use the acceptance criteria in [Phase 6](#phase-6-evaluate-and-consolidate)
throughout Phases 4 and 5, not only after implementation. Preserve unresolved
correspondences in opt-in diagnostics; `ambiguous` means unknown, not evidence
that nothing moved.

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

#### Copied (deferred)

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

The active movement outcomes are stationary, relocated, restructured, and
ambiguous, with parent carrying recorded separately. Copy detection is deferred
because it needs source-survival evidence. One-to-many and many-to-one
histories may later justify explicit `split`, `merged`, or `extracted`
classifications. Until those semantics are defined and tested, such cases
should remain unresolved unless movement is independently supported.

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

## Groups and NxM correspondence

Move groups should not be discarded, but their meaning must be narrowed. Two
different concepts are easy to conflate:

1. A **correspondence group** is a set of before and after endpoints that share
   identity evidence. It records what may continue across the snapshots.
2. A **change-event group** is a set of established correspondences that
   collectively explain one larger edit. It records which changes belong
   together.

The current `content_group` is primarily a correspondence group. Shared exact
or normalized content establishes an equivalence set; it does not by itself
prove that all endpoints moved together. Change-event grouping is a separate,
later concern and should not be inferred merely because endpoints share text.

Cardinality describes the topology and uncertainty of a correspondence group:

| Cardinality | Safe interpretation |
| --- | --- |
| 1x1 | One potentially unique correspondence |
| 1xN | One source and several possible destinations; copying is not yet proved |
| Nx1 | Several possible sources and one destination; merging is not yet proved |
| NxM | The endpoint sets correspond collectively, but individual pairings may be unknown |

An NxM group is therefore useful even when it cannot produce individual move
pairs. Its change classification can still be `stationary`, `relocated`,
`restructured`, or `ambiguous` at the set level. For example, every endpoint
may clearly move to another function even though repeated text prevents a
unique pairing. Conversely, an exact NxN content group may remain ambiguous if
neither pairing nor structural displacement is supported.

Context may resolve a correspondence group into smaller groups or unique 1x1
correspondences. Stable containers, anchors, sibling order, and compatible
ancestor paths are legitimate disambiguating evidence. Document order alone is
not. Resolution must preserve its evidence and confidence so the result does
not appear more certain than the observations justify.

The implementation must never expand an NxM group into the Cartesian product
of every possible endpoint pair. That would manufacture `N * M` moves from an
equivalence relation. `min(before_count, after_count)` is a useful upper bound
on non-reusing pair count, but it does not identify any particular pairing.

Unequal cardinality also does not establish copying, splitting, or merging.
For example, a 1x2 deleted/inserted group could be one move plus an unrelated
repeat. `copied` requires evidence that the original source occurrence
survived, normally from common-source context or a separate inventory of
unchanged constructs.

This framing preserves the useful NxM model while removing premature semantic
claims. Names such as `moves_many` and `copy_or_repeat` describe current policy,
not facts established by content grouping. They may eventually be replaced by
neutral cardinality plus an independently computed change classification.

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

The shared classifier should use durable structural evidence in roughly this
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

Retain ordered, explainable rules rather than adding another score. For a pair
whose correspondence is sufficiently established, the active location policy is:

```text
if revision file changed:
    relocated
else if file identity or mapped container evidence is missing:
    ambiguous
else if mapped semantic container changed:
    relocated
else if candidate crossed a stable sibling:
    relocated
else if same stable anchor interval and meaningful ancestry is unchanged:
    stationary
else if same stable anchor interval and ancestry supports wrapping/unwrapping:
    restructured
else:
    ambiguous
```

The order is policy and must be tested. A changed immediate parent alone does
not establish relocation; wrapping inside a stable interval is restructuring.
Matching ambiguity and parent carrying remain explicit checks outside these
pair-only location rules. Copy detection needs additional evidence and remains
outside the active phases.

Unique Type-1 and Type-2 production output now uses the shared classifier.
The adjacent-region Type-2 heuristic was removed in Phase 4.1; adjacency alone
is not evidence of stationarity. See the [architecture](../architecture.md)
for the verified decision and endpoint-reservation pipeline.

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
shared location classification
  stationary / relocated / restructured / ambiguous
    |
    v
common eligibility and conflict selection
  correspondence ambiguity; parent carrying; parent versus descendants; non-overlap
    |
    v
report accepted relocations
  retain other classifications in diagnostics
```

The classification stage should not change canonicalization or manufacture new
content matches. Correspondence asks *what continues*; classification asks
*what happened*; hierarchy selection asks *which granularity best explains the
change*.

The location classifier can assess a proposed pair without proving that it is
the unique correspondence. Matching uncertainty remains explicit through
eligibility and selection. Parent carrying depends on relationships among
correspondences, so it is a shared relationship check rather than an additional
pair-only location rule. Reuse the existing classifier, decision record, and
selector; do not add a generic framework or a second ranking system.

## Suggested data model

This early sketch is illustrative, not a requirement to add new types. Phase 4
should generalize the existing compact decision record and classifier types.
Keep parent carrying as an explicit relationship; do not introduce a copied
outcome before source-survival evidence is in scope.

```cpp
enum class correspondence_kind {
  exact,
  type2,
  type3,
};

enum class change_kind {
  stationary,
  relocated,
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

Here, `endpoint_set` allows the correspondence to remain NxM without inventing
member pairings. A future `change_event` type, if needed, should refer to one or
more already classified correspondences. It should not replace or overload the
correspondence group itself.

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

The original adjacency-filter migration sketch is superseded: location evidence,
not event adjacency, determines stationary, restructured, or ambiguous outcomes.
The legacy Type-2 helper was removed in Phase 4.1.

### Phase 3: adopt classification for Type-1 only

Status: complete in srcMove 0.5.0. Unique Type-1 output now requires positive
`relocated` classification; normalized source regressions and the retained
Notepad++ comparison validate the adopted policy. Non-1x1 exact groups retain
their earlier group policy.

Let the new classifier control output for unique exact correspondences first.
Type-1 offers the clearest correspondence evidence, so failures in this phase
mostly expose classification-policy problems rather than matching problems.
Existing non-1x1 groups retain their earlier production policy until Phase 5;
they are not expanded into speculative pairs.

The initial adoption targeted:

- `stationary` when structural location is effectively unchanged;
- `relocated` when the location change is clear; and
- `ambiguous` when evidence is insufficient or contradictory.

The completed implementation also classifies basic wrapping/unwrapping as
`restructured` and records exact-parent carrying; both remain non-move outcomes.

Require positive relocation evidence and prefer `ambiguous` to a weak move
claim. Keep Type-2 behavior on the existing path until Type-1 results are
understood and stable.

### Phase 4: unify movement classification across Type-1/2/3

Status: Phases 4.0 and 4.1 complete; Phase 4.2 has not started. The reviewed
SQLite reorder survives production adoption after common-conditional context
repair. See the [adoption evidence](../../moveSelectionBench/README.md#type-2-production-adoption).
Keep the existing matching representations, hierarchy selection, repeated-group
policy, and Type-3 verification rule.

#### Phase 4.0: consolidate the decision path and establish contracts

Generalize the existing Type-1/shadow names and compact decision record only
where needed. Production and diagnostics must consume the same decision.
Preserve Type-1 behavior and normal output while collecting observation-only
Type-2 results. Record matching evidence separately from location classification
and final selection; ranking confidence is not a probability of movement.

Define reviewed contracts for movement, edits in place, wrapping, missing
context, competing endpoints, and parent carrying. Use current exact-parent
carrying only within its supported scope. Containment inside a normalized or
edited parent does not prove a child's relative position stayed unchanged.
Do not suppress a child merely because an unselected parent could carry it;
the selected explanation must account for the child's movement.

#### Phase 4.1: migrate Type-2

Status: complete. Verification and retained comparison results are recorded in
the [adoption evidence](../../moveSelectionBench/README.md#type-2-production-adoption).

Classify unique complete constructs with equal Type-2 identity using the shared
classifier. Audit existing expectations and historical gains/losses before
adopting the production gate. Remove the adjacent-local-replacement heuristic
once its contracts are covered. Preserve unresolved normalized groups and
prevent rejected correspondences from being relabeled as weaker Type-3 matches.
Do not invent a confidence threshold from the fixed Type-2 ranking weight.
Reserve unique Type-2 endpoint IDs before alternate Type-3 retrieval, regardless
of eligibility; do not reserve enclosing or descendant spans. Preserve missing
context as ambiguous and retain normalized correspondence assertions when
revising move-output expectations. Stop and investigate any lost reviewed real
move rather than relabeling it as a negative.

#### Phase 4.2: migrate verified Type-3 correspondences

Begin with independent contracts and observation-only classification of verified
Type-3 edges, then evaluate before changing output. Type-3 similarity may yield
several competing edges for an endpoint and is not transitive; do not convert
connected similar pairs into an exact-style equivalence group or treat passing
the similarity threshold as proof of a unique correspondence.

Reuse the same location rules and existing conflict selector. Establish when
competing correspondence evidence must remain ambiguous; a deterministic rank
alone is not evidence of identity. Keep correspondence acceptance separate from
location evidence so cross-file displacement cannot validate a poor match.
Test edits in place, genuine edited moves, competing endpoints, and independently
moved children inside edited parents. Extend parent carrying only when stable
relative position is supported; otherwise let existing overlap selection avoid
duplicate output. Do not add an optimizer, new retrieval model, or generalized
matching framework to accomplish this migration.

### Phase 5: consistent treatment of repeated correspondence groups

Close the remaining repeated Type-1 exception to positive relocation evidence.
Start with the normalized wrapper cases documented in the
[Phase 3 inventory](../../moveSelectionBench/README.md#phase-32-normalized-source-inventory),
where repeated groups can emit moves despite stationary or ambiguous unique
child decisions. Establish positive repeated-move and negative repeat/wrapper
contracts before changing group eligibility.

Require supported movement for any emitted group. Preserve set-level evidence
without asserting unknown individual pairings. A single displaced endpoint must
not justify annotating an entire mixed stationary/moved group. If context does
not establish the group's movement, retain it as ambiguous; measure the real
moves lost by that choice rather than counting suppression as success.

Do not pair by document order, expand Cartesian products, or interpret unequal
counts as copies. Keep normalized repeats unresolved unless reviewed context
justifies a small, explicit resolution rule. Group decomposition is not required
for completion; add it only if evaluated historical cases justify it. Reuse the
same movement evidence and common selector rather than introducing another
movement definition or change-event system.

### Phase 6: evaluate and consolidate

Use this acceptance process for each production adoption, then perform a final
integrated evaluation. Freeze the baseline, evaluated inputs, executable/build
provenance, and independently reviewed expectations. Include both small semantic
contracts and a bounded sample of real history across repositories and languages
supported by the tool. Include same-file reorders, cross-container/file moves,
edited moves, wrapping, repeated code, and weak srcDiff context. Select history
samples before inspecting detector outcomes and retain a held-out portion for
final evaluation; do not tune only against the retained Notepad++ example.

Review source revisions to label real moves and non-moves independently of both
versions' outputs. Include missed cases, not just the union of reported moves.
Separate uncertain human judgments from confirmed labels. Report:

- correspondence errors separately from location-classification errors;
- false moves, missed reviewed moves, precision and recall where the labeled
  sample supports them, with explicit counts and denominators;
- results by evidence type and scenario, plus ambiguity counts and known real
  moves withheld as ambiguous; Type-3 remains an observational recall stratum;
- baseline-to-candidate gains and losses, identifying extraction, matching,
  missing context, classification, or selection as the limiting stage; and
- runtime and peak memory on the same inputs and execution environment.

Use compatible counting units: repeated groups are not verified individual
pairs, and parent-carried descendants must not inflate recall or duplicate
errors. Synthetic transfers establish controlled capability, not representative
historical accuracy. Zero reported moves on the retained Notepad++ input proves
conservative fallback only; it does not prove improved precision or recall.

Acceptance requires evidence of improved historical usefulness with reviewed
precision/recall tradeoffs, not merely fewer outputs or passing tests. Investigate
every lost reviewed positive in the bounded evaluation. Restore detection through
justified evidence where feasible; otherwise make the remaining loss and its
impact explicit for review before adoption. Do not invent numeric targets or
claim general accuracy from a small sample. If results do not support improvement,
revise or narrow the policy before calling the milestone complete.

Finally remove obsolete comparison paths, consolidate decision/diagnostic code,
and reconcile architecture and research documentation with verified behavior.
Retain reproducible baseline evidence. No permanent dual algorithm, new scoring
framework, or automatic release/version change is required.

### Deferred work

Basic ancestor summaries and wrap/unwrap classification already exist; validate
them across evidence types in Phase 4 rather than scheduling them as a new
Phase 5 feature. Richer branch/control-flow restructuring, copy detection,
source-survival inventories, split/merge/extraction labels, and change-event
grouping remain future work. Reconsider them only when concrete historical
analysis needs and reviewed examples justify the added concepts.

### Delivery milestones

1. Context and shadow diagnostics exist (complete).
2. Unique Type-1 output uses classification, with normalized regressions and
   retained history evaluation (complete).
3. Type-2 and verified Type-3 use shared classification and selection (Phase 4).
4. Repeated groups obey a consistent movement policy (Phase 5).
5. Historical usefulness and costs are evaluated, and the pipeline is
   consolidated (Phase 6).

Each adoption uses a temporary comparison path until evaluated; remove it when
it no longer provides diagnostic value. Only accepted relocations enter normal
move output. Preserve other observations in opt-in diagnostics and update
srcDiffVisual deliberately if its interpretation must change. Milestones do not
authorize a version bump; follow the repository versioning policy.

## Test strategy

The semantic tests should cross correspondence evidence with change outcome:

| Evidence | Scenario | Expected classification |
| --- | --- | --- |
| exact | lines inserted above otherwise stable statement | stationary |
| exact | same statement moved to another function | relocated |
| exact | statement reordered past stable sibling | relocated |
| exact | statements wrapped by a new conditional | restructured |
| exact (deferred copy work) | source remains and another occurrence appears | copied, only with source-survival evidence |
| Type 2 | identifier or literal changed in the same slot | stationary |
| Type 2 | renamed statement moved to another function | relocated |
| exact | repeated endpoints without unique pairing | ambiguous |

Group-focused tests should assert more than the final label:

- a repeated NxM case remains one correspondence group with the correct
  endpoint counts;
- reported or potential non-reusing pairs never exceed
  `min(before_count, after_count)`;
- the system never emits the full Cartesian product as established moves;
- any decomposition into 1x1 correspondences cites structural evidence rather
  than document order alone;
- a set-level relocation does not claim unknown member pairings; and
- an unequal group is not classified as `copied` without source-survival
  evidence.

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

## Decisions for the first implementation milestone

The initial context-capture and shadow-classifier milestone uses the following
reviewed policy. These decisions constrain observation-only results; they do
not yet change normal move annotations.

1. Reliable anchors begin with uniquely mapped named semantic containers and
   complete constructs that belong to both revisions, preferably through
   explicit `diff:common` membership. Unique common declarations and
   substantial structural siblings may serve as local anchors inside a mapped
   container. Punctuation, braces, short low-information statements, line
   numbers, raw XPath equality, and document order alone are not anchors.
2. A literal name or raw-path change in a semantic container is not sufficient
   relocation evidence. Different files are strong relocation evidence. Two
   genuinely distinct, reliably mapped semantic containers are relocation
   evidence. When container correspondence is unavailable, the result remains
   ambiguous.
3. A relocated parent carries descendants whose location relative to that
   parent remains stable. Normal output should report the coherent parent, not
   duplicate moves for every child. A child may be independently relocated only
   when it has positive displacement evidence relative to the mapped parent.
   Shadow diagnostics may record a stable child as `carried_by_parent`.
4. Pure wrapping or unwrapping inside the same mapped container and stable
   anchor interval is `restructured`, unless independent displacement evidence
   exists. `restructured` remains diagnostic-only for the thesis milestone;
   only accepted `relocated` results are candidates for normal move output.
5. The anchor layer interprets srcDiff revision membership and common context;
   it does not independently rediff or rematch the complete program. Missing or
   contradictory context produces `ambiguous` rather than an inferred move.
6. Deckard-style vectors are deferred. They may later be evaluated as Type-3
   correspondence retrieval evidence, but they do not provide location
   classification or anchor evidence.

## Decisions deferred beyond the first milestone

Before production behavior changes beyond unique Type-1 correspondence,
review these questions explicitly:

1. Should normal srcMove output include copies, or should copies exist only in
   JSON diagnostics and srcDiffVisual?
2. Should ambiguous correspondences be visible by default, available only on
   request, or omitted from normal output?
3. Should `restructured` remain one result or should wrapping, unwrapping,
   extraction, and inlining become separate classifications?
4. When Type-2 evidence is stationary, should the display call it “stationary
   Type 2,” “modified in place,” or expose both labels?
5. Which additional common constructs are reliable enough to become anchors
   after the conservative first implementation is evaluated?

Record later answers here before coding them so future agents do not infer
policy from incidental regression output.

## Effort and risk

The classifier and streaming context already exist. The remaining work is
migration, repeated-group policy, and evaluation. Keep each adoption small;
do not make deferred copy detection or richer restructuring prerequisites for
the thesis milestone.

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
