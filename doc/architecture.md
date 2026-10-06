# srcMove Architecture

srcMove is a C++ command-line tool that post-processes srcDiff XML and marks
regions that its matching and selection policy identifies as relocated source
code. Its primary research focus is move detection across file and structural
boundaries, with Type-1, Type-2c, and Type-3 correspondence evidence.

## Terminology

srcDiff represents source present only in the original revision with
`diff:delete` and source present only in the modified revision with
`diff:insert`. A *reported move* is a selected pair or group of deleted and inserted
candidates. It is an operational detector result, not proof of a historical
move, developer intent, or semantic equivalence. A content match supports a
proposed correspondence; it does not establish continuing identity by itself.
Type-1, Type-2c, and Type-3 describe content evidence; group kind separately
describes endpoint cardinality and ambiguity. Reported moves are broader than
classifier-confirmed relocation: individual Type-1, Type-2c, and Type-3 pairs
require positive location evidence, while unresolved repeated exact groups
require evidence of possible displacement without claiming individual partners.
Explicit copies from an independently continuing origin are also reported;
their additional destinations do not imply that the origin relocated.

## Implementation

The current implementation is a deterministic structural matcher with an
interpretable, uncalibrated selection utility. It uses the srcML structure
embedded in srcDiff XML, but it does not claim probabilistic confidence,
general semantic equivalence, or an AST-similarity model.

## Input and repository role

srcMove consumes srcDiff XML rather than comparing source revisions itself. It
supports both:

- a single file unit whose `filename` identifies the original and modified file
- an archive containing multiple file units, including deletions and insertions
  in different files

srcML provides the structured source representation, srcDiff produces the input
XML, and srcReader supplies the streaming XML reader/writer infrastructure.
srcMove remains a separate CLI and does not require integration into srcDiff.

## Implemented pipeline

The pipeline is coordinated by [`src/pipeline.cpp`](../src/pipeline.cpp).

### 1. Stream the input and construct candidates

[`src/region_filter.cpp`](../src/region_filter.cpp) makes one streaming pass
over the input. It:

- distinguishes single-file and archive srcDiff shapes
- tracks the file ownership and nesting of each `diff:delete` and `diff:insert`
- builds move candidates as the reader encounters element starts, element ends,
  and text in document order

Each candidate retains both the srcDiff unit filename used by existing
selection and an owned endpoint-location context. The context resolves
`old|new`, `old|`, `|new`, and shared archive filenames to the path belonging
to that candidate's revision. The code and diagnostic fields use
`semantic_container` for a mapped named enclosing construct; this is structural
context, not analysis of program behavior or name binding. The collector records
the nearest qualifying construct only when srcDiff represents that function, constructor, type, or
namespace as one physical construct belonging to both revisions. Exclusive or
unnamed containers are not paired by name or XPath; the candidate falls back
to a mapped enclosing container or remains unmapped. Anchor and ancestor
fields stay explicitly unreliable until the streaming parser has positive
structural evidence. For a mapped endpoint, the parser records its
revision-filtered meaningful **strict ancestor** chain as a deterministic integer
ID. A structural candidate's own start frame is excluded from both container
lookup and ancestry; diff wrappers are absent from the source-element stack, so
their context retains the whole enclosing stack. Thus an `if_stmt` wrapped in a
`while` changes `[block]` to `[block, while, block]`, preserving the classifier's
existing prefix interpretation without deleting real enclosing ancestors.
The parser emits a document-local intern table; the candidate registry rebases
incoming IDs into registry-owned storage so they remain resolvable throughout
grouping and classification, including incremental multi-file use. Common
elements and elements belonging only to the endpoint revision are included;
elements exclusive to the opposite revision are not. Removing an incremental
file compacts this side table to summaries still referenced by active
candidates. After the streaming pass, complete common declarations, expressions,
and control statements with substantive text and unique exact canonical identity
in a mapped source region become stable anchors. Complete common control
statements and unchanged common control headers can establish sibling boundaries;
the latter remain usable when the body is edited. Mixed headers and repeated
identities cannot provide that evidence. Bounded collectors retain inner and
outer control statements without capturing every nested subtree independently.
Anchors are scoped to their physical common block or control region, so a call
inside another branch is not an outer sibling. Each mapped candidate receives
nearest nonoverlapping anchors, plus prefix/suffix ranks of eligible common
siblings. Matching anchor scopes and opposite-side rank overlap establish a
crossing; different nearest-anchor names alone do not. Crossing context may
extend through an added exclusive wrapper to its common outer region, while
immediate structural identity remains separate. This preserves real movement
into wrappers and past edited conditionals without flattening branch contents.
Unmapped candidates retain unreliable anchor intervals. Production selection
consumes this context for individual Type-1, Type-2c, and Type-3 correspondences.

This distinction permits a deletion in one archive unit to match an insertion
in another without mistaking a combined srcDiff filename for one revision's
file identity.

### Location classification vocabulary

[`src/movement_classifier.cpp`](../src/movement_classifier.cpp) contains a pure,
ordered location classifier. Its outcomes describe the implemented location
model, not universal categories of source-code changes.

| Implementation label | Meaning under the current policy |
| --- | --- |
| `relocated` | Different revision-specific file paths, different mapped enclosing constructs or immediate common structural regions, or crossing a shared common sibling provide relocation evidence. |
| `stationary` | Within the same file and mapped container, reliable anchor intervals and interpretable ancestor summaries agree. A later carrying check also uses this label for a child stable relative to a relocated parent. |
| `restructured` | Within the same file and mapped container, an interpretable ancestor summary is a strict prefix of the other. Reliable equal intervals or overlapping shared-region ranks involving containment in a common control establish the supported wrapping or unwrapping pattern; actual crossing retains precedence. |
| `ambiguous` | Evidence required by the reached classification rule is missing, or the ancestry cannot be interpreted as one of the supported relationships. This is location uncertainty, not uncertainty about which candidates correspond. |

The rules are ordered: a changed file path establishes `relocated` before
container or ancestry checks. Missing parent context therefore does not make
every cross-file pair ambiguous. File comparison uses paths, not inferred
continuing file identity, so a file rename can supply this evidence.

`restructured` is a policy choice for wrapping within a stable interval. An
AST-parent model can describe the same change as a move. Similarly, `stationary`
does not rule out historical moves away and back between the compared revisions.
The classifier does not reconstruct editing actions.

Matching ambiguity is separate: repeated content or competing partners can leave
pairing unresolved even when a particular pair has clear location evidence.
The legacy diagnostic field `shadow_change` exposes the location outcome;
`cardinality` and partner counts describe separate matching relationships.

The refined group builder harvests unique exact Type-1 pairs before hierarchy
selection and classifies them once. Only positively classified independent
relocations remain eligible as unique Type-1 proposals; stationary, restructured, ambiguous, and
parent-carried correspondences remain diagnostic-only. The same compact
decision records materialize the opt-in diagnostics, so production eligibility
and diagnostic interpretation cannot diverge.
Unique Type-2c groups are classified once after exact grouping has removed Type-1
correspondences. The same decisions control eligibility and diagnostics: only
`relocated` pairs that pass the continuing-name identity checks enter selection.
Each non-tentative, non-contradicted unique Type-2c correspondence reserves its
endpoint IDs before Type-3 retrieval, regardless of location outcome or final
selection. Tentative pairs do not reserve endpoints, so stronger alternatives
can compete.
Reservation prevents weaker alternate partners without reserving spans, so
distinct enclosing and descendant proposals still compete normally.
Type-2c decisions do not participate in exact-parent carrying, since containment
inside an edited parent does not establish stable relative position.

Before selecting normalized correspondences, the streaming collector projects
continuing `decl_stmt`, `expr_stmt`, and `return` shells into their original and
modified revisions. Only pairs with identical structure, literals, and other
non-name content supply concrete name substitutions. Wholly deleted/inserted
statements cannot supply evidence for their own proposed matches. Unknown diff
elements, preprocessor content, nested semantic containers, and unsupported local
scope boundaries exclude local-name evidence. Fragmented identifier text cannot
supply replacement evidence. Conflicting substitutions remain ambiguous.
Local-name evidence stays within the mapped lexical block; qualified member
paths can supply evidence across blocks of the same mapped container only when
the access prefix is unchanged. Built-in type keywords provide no rename support.

Normalized pairs that contradict this independent evidence are suppressed.
Standalone Type-2c and edited Type-3 declarations with unsupported changed
names remain eligible as `tentative` when location evidence is positive. They
are not rejected merely for lacking continuing-use corroboration. Their selection
utility is multiplied by 650/1000 with integer truncation, and their evidence
tie-break strength is lowered. The structural coverage bonus is unchanged. The
named constant lives in `selection_policy.hpp`; it is a ranking heuristic, not an accuracy
estimate. Content-based `confidence_milli` and matched-unit counts stay unchanged.
Proposals are ranked again after this adjustment and before descendant-bundle
selection. With no stronger competitor, a tentative pair may be reported.
Larger isolated constructs retain the existing policy when there is no
contradictory evidence. This is lexical corroboration, not resolved
binding or behavioral analysis, and cannot recover whole endpoints absent from
srcDiff. It is not a general proof of identity.
Every verified Type-3 edge is likewise classified before selection in every
output mode. Only positive relocation decisions enter production selection;
stationary, restructured, and ambiguous edges remain available in diagnostics.
Missing context is not proof of stationary identity. Edited-parent carrying is
not inferred for Type-3 edges.
The Phase 0 contract adapter resolves endpoints by the reviewed construct and
exact text rather than using current classifications as its oracle. With
fragment granularity, all twelve contracts match, including
the source-generated `[[nodiscard]]` unwrap. Macro ancestry is explicitly
marked non-interpretable; when classification reaches the ancestry comparison,
it yields `ambiguous` with `incompatible_context` rather than supporting
stationarity. A child is marked parent-carried only when
a unique exact structural-parent correspondence strictly contains it on both
revisions and that parent is independently classified as relocated. The
nearest such structural parent is recorded by candidate ID; diff wrappers and
document-order pairing are not accepted as evidence. The carrying check sets
`stationary` with reason `stable_relative_to_relocated_parent` and the separate
`carried_by_parent` flag. Here stationary means relative to that parent, not
unchanged file location. This check precedes selection and does not require
the parent to be selected for output.

For performance reasons, candidate construction and canonicalization are part
of this same pass.

While streaming, srcMove tracks the nearest enclosing srcDiff revision state.
Source under `diff:delete` belongs to the original revision, source under
`diff:insert` belongs to the modified revision, and source under `diff:common`
belongs to both. A nested wrapper changes the state inherited from its parent.

Nested wrappers for the same revision can produce both an enclosing candidate
and complete descendant candidates. An enclosing candidate is rejected when it
also contains substantive common content or content owned by the other
revision; independently complete descendants may remain eligible.

Completed candidates own compact matching representations; the pipeline does
not retain captured srcML trees.

[`src/parse/diff_region.cpp`](../src/parse/diff_region.cpp) retains the older
captured-region path for focused tests and callers that explicitly need region
objects. It is not used by the production pipeline.

### 2. Apply the candidate policy during the stream

The streaming path applies the default revision-aware policy while regions and
structural constructs are completed:

- retain pure complete constructs at multiple nested scales
- reject substantively mixed wrappers without discarding pure descendants
- exclude whitespace-only payloads and fragments smaller than a complete
  statement or declaration
- expand eligible diff regions into preferred structural children and
  statements, such as functions, classes, declarations, conditionals, and loops

This expansion lets srcMove annotate the moved source construct instead of an
overly broad surrounding diff wrapper when the structure supports it.
Statement-sized candidates must also contain at least four srcML lexical text
events, which suppresses low-information statements such as `break;`,
`return;`, and `f();`. A diff wrapper is eligible only when it contains a
complete construct meeting the same evidence floor. The CLI option
`--min-granularity fragment` restores raw diff-fragment candidates for
specialized analysis; it is not the default.

### 3. Build matching representations and groups

The incremental builder in
[`src/parse/canonical_subtree.cpp`](../src/parse/canonical_subtree.cpp) feeds
each candidate's XML events through coordinated builders for all cached
matching representations. The Type-1 form ignores all diff wrappers,
comments, `diff:ws` elements, and formatting-only text while retaining
identifiers, literals, keywords, operators, and srcML structure. The Type-2c
identity is a compact lexical form: it consistently numbers direct srcML
`<name>` tokens by first occurrence, replaces literals with their category
(`integer`, `floating`, `string`, `character`, `boolean`, or `null`), and
ignores comments and formatting. Empty statements remain in the lexical form:
adding or removing one requires Type-3 similarity assessment rather than Type-2c
equality. Other source tokens and operators remain unchanged. Group keys also
include the candidate's srcML element kind, so lexically identical constructs of different kinds do not
collapse into one group.

Candidates are bucketed with 64-bit FNV-1a hashes of that canonical form. A hash
is only an index: groups are split and confirmed using the full canonical text,
so a hash collision is not accepted as a move.

Type-2c eligibility is narrower than general candidate eligibility. The stream
admits structural constructs (including functions and declarations of functions,
types, and namespaces) plus `decl_stmt`, `if_stmt`, `for`, `while`, `do`,
`switch`, and `try` statements. Standalone `expr_stmt` and `return` candidates
can participate in exact Type-1 matching but are excluded from Type-2c grouping.
The [historical study](../moveSelectionBench/historical_study/README.md) contains
a source-reviewed renamed call reorder that reaches candidate construction but
misses at this eligibility boundary. This is a limitation, not a negative move
oracle or a lack of source evidence for relocation.

[`src/move_registry/content_group_builder.cpp`](../src/move_registry/content_group_builder.cpp)
builds all supported evidence before selection. Pure ranking and descendant
bundle policy, including its declared constants, lives in
[`src/move_registry/selection_policy.cpp`](../src/move_registry/selection_policy.cpp):

1. forms exact canonical-text groups and refines independently supported portions
   of repeated groups using original exact sibling and region correspondences
2. classifies unique one-to-one exact correspondences and admits only supported
   relocations to production proposal selection; non-1x1 exact groups require
   positive evidence for at least one possible relocated pairing, except explicit
   additional copies from an independently continuing origin
3. groups eligible constructs by exact Type-2c representation, classifies unique
   pairs, and reserves their endpoint identities
4. generates Type-3 edges for remaining structurally compatible candidates and
   classifies their location
5. turns eligible exact and Type-2c correspondences plus verified Type-3 edges
   into one proposal set
6. disables individual Type-1, Type-2c, and Type-3 proposals without positive relocation
   decisions before hierarchy selection
7. ranks proposals by size-aware utility plus an internal structural-coverage
   term, then confidence, evidence class, source-construct preference, and
   deterministic candidate identifiers
8. greedily selects proposals subject to one-use and source/destination span
   overlap constraints
9. emits remaining delete-only and insert-only groups for reporting

Repeated exact equivalence classes with supported possible displacement are
retained as multi-endpoint move/copy groups with ambiguity-aware confidence;
they do not claim an individual pairing. The gate compares actual proposal
endpoints for differing known files, differing mapped containers or immediate
common regions, or an actual shared-sibling crossing. It aggregates sibling
ranks by scope rather than expanding a pair product. Groups without any such
evidence remain unmatched. A group can still
be eligible when a stationary assignment is also possible: existential location
evidence does not resolve identity or prove that every endpoint relocated.
Repeated Type-2c classes remain unresolved because normalization has
already removed distinguishing content, and document order alone is not
correspondence evidence.

Repeated Type-1 classes can become partial individual pairs through mutually
unique original sibling evidence. A local parent correspondence requires at least
two original unique exact siblings to agree on one parent partner, preserve their
order, and have compatible file, container, and ancestor context. This can
resolve repeated statements within an edited loop or block. It never overrides
independently established displacement of that region. Newly inferred pairs do
not seed further matches, and elimination alone does not assign residual partners.
Single-child wrapper aliases inherit established child pairs individually, so
incomplete wrapper coverage cannot reopen a continuing child as a move.

Unresolved endpoints retain equivalence meaning. When all original origins have
independently continuing partners, additional exact destinations retain explicit
copy provenance from those origins, excluding the continuing destinations.
These reports use `selection_reason: continuing_source_copy` and the
`copy_or_repeat` group kind even for one additional destination. Copies do not
require displacement of their continuing origin. When unmatched original origins
remain, the residual group does not assert copying from a known continuing origin.
Ordinary resolved moved pairs use `selection_reason: exact_neighbor_correspondence`.

A one-to-one residual is still unresolved when it arose solely by subtracting
supported partners. It retains `copy_or_repeat` group kind and
`selection_reason: unresolved_exact_residual`; it cannot enter the unique
correspondence classifier or an ordered sequence. Region-relative continuation
is recorded as `stable_in_corresponding_region` in location diagnostics.

Region correspondence and common-source anchors do not completely assign which
region moved when code is hoisted across another continuing region. In the
reviewed OpenCV accumulation change, the universal prelude is hoisted while the
AVX prelude is wrapped; the remaining AVX prelude reports still attribute the
crossing to that code. Resolving this conservatively requires additional region
evidence. Different nearest-anchor names no longer suffice to report a move,
but trustworthy crossing evidence does not by itself settle that attribution.

The neighbor-evidence idea is adapted from RefactoringMiner's
[`CustomTopDownMatcher`](https://github.com/tsantalis/RefactoringMiner/blob/4d08e547cfe572ed8e58993b7c1303253142d4ac/src/main/java/org/refactoringminer/astDiff/matchers/vanilla/CustomTopDownMatcher.java#L462).
This implementation requires independent mutual support and preserves separate
location eligibility; it does not import RefactoringMiner's AST framework.

Type-3 uses a NiCad-inspired sequence rule implemented directly in srcMove; no
NiCad executable or runtime dependency is involved. Canonicalization caches two
compact views: normalized code divided at statement and block boundaries (`;`,
`{`, and `}`), and a finer token sequence. Both similarity views retain the
Type-2c representation's consistent first-occurrence name mapping. This keeps
identifier-correspondence patterns as evidence rather than making similarly
shaped but unrelated functions identical through blind name replacement.

Each unit is hashed to 64 bits. For either pair of sequences `A` and `B`, with
longest common subsequence length `L`, the representation accepts exactly when
both `L / |A| >= 0.90` and `L / |B| >= 0.90`. This is equivalent to
`L / max(|A|, |B|) >= 0.90`. A candidate pair qualifies when either the
statement/block view or token view accepts; its stronger similarity orders the
edge.

The comparison first rejects impossible size ratios, then runs a two-row LCS
that exits when the remaining rows cannot reach the required common length.
Candidates are restricted to the same eligible srcML element kind and the 0.90
size window, rather than forming an unrestricted delete-by-insert product.
Eligible Type-1, Type-2c, and Type-3 proposals compete in the same utility
ordering. A large verified near-match can therefore suppress a small exact
descendant.
Correlated evidence is represented by its strongest applicable match class
rather than summed. Deterministic IDs break otherwise equal proposal ranks.

The local hierarchy pass compares an enclosing one-to-one proposal with a
non-overlapping descendant bundle before greedy selection. Descendants replace
the parent only when they cover a substantial but non-partitioning share on
both sides, improve weighted confidence materially, and remain stronger after
a proportional fragmentation cost. The pass evaluates larger parents first so
an intermediate decision cannot hide evidence from its enclosing construct.

### 4. Produce annotations or results

For a normal annotated-XML run, the writer makes a second XML pass and preserves
unmodified input nodes. For each group containing both deletes and inserts, it
adds the srcMove namespace and annotates matched start tags with:

- `mv:id`: the shared move-group identifier
- `mv:to`: destination XPath or XPath union on a deletion
- `mv:from`: source XPath or XPath union on an insertion

Annotations may be placed on a structural child inside a diff wrapper rather
than on the wrapper itself. The optional `--results` output records move groups,
predicted content relationships, source/destination XPaths, raw texts, candidate counts, group
classifications, confidence in thousandths, matched units, selection utility,
and the selection reason as JSON. The top-level `results_schema_version`
identifies this contract and is currently `2`. With `--results-only`, srcMove
materializes that JSON evidence from candidate-owned XPaths and skips the
second XML pass entirely.

### Ordered move sequences

After selection, [`move_sequences.cpp`](../src/move_sequences.cpp) aggregates
selected unique one-to-one Type-1 structural-child reports into maximal ordered
runs. Each run requires a fixed source file/parent and destination file/parent,
immediate sibling adjacency in both revisions, and disjoint endpoint spans.
The streaming collector counts all meaningful direct children, including common
and filtered children. Diff wrappers, comments, and whitespace are transparent;
preprocessor constructs, unknown diff tags, unstructured substantive text,
and unreliable nested revision ownership prevent grouping. The metadata does not supply new
relocation evidence.

Results schema 2 adds `move_sequences` alongside `moves`. Each sequence records
`policy: ordered_adjacent_v1`, `content_relationship: type1`, ordered
`member_move_ids`, and `from`/`to` endpoint objects. Endpoints record
`revision_file`, comparison-local `parent_id`, first/last child ordinals, and
ordered `member_xpaths`. Sequence IDs use `sequence:` followed by the first
member's move ID and have the same comparison-local scope as those IDs.
The original move records, XML annotations, and summary count meanings are
unchanged. `sequence_cluster_count` counts runs with at least two members;
`sequence_reporting_unit_count` is the original group count minus
the sum of `(member count - 1)` over those runs. Residual ambiguous groups each
remain one reporting unit, without resolving their pairings. Neither count
establishes the number of developer editing actions.

The primary reporting projection is `reported_moves`, with
`reported_move_count` and `reported_content_relationships`. Every selected
atomic group belongs to exactly one report. An ungrouped report has
`report_kind: atomic`, its original `move_id`, and a singleton
`member_move_ids`. A grouped report has `report_kind: ordered_sequence`, its
sequence ID as `move_id`, `content_relationship: type1`, and ordered member
IDs. Both kinds provide `from_xpaths`, `to_xpaths`, `from_raw_texts`, and
`to_raw_texts`. For a sequence those arrays concatenate each member's single
endpoint in member order: index i on the source matches index i on the
destination. They are not Cartesian partner sets. Atomic repeated groups
retain their existing equivalence/ambiguity semantics.

One qualifying run is therefore one Type-1 reported move, even when it has no
enclosing AST construct. XML continues to annotate the original member
endpoints and their exact partner links. No synthetic block or enclosing
method detection is implied. Legacy `moves`, group/pair/annotation counts,
and `content_relationships` retain their meanings for existing consumers and
benchmark scoring. `reported_move_count` equals
`sequence_reporting_unit_count`; category counts in
`reported_content_relationships` count primary reports, rather than members.

Whole-run Type-1 equality follows from ordered equality of complete sibling
canonical streams and the absence of intervening meaningful content. Exact
canonicalization has no cross-member identifier mapping; whitespace-only text
and comments are ignored, while each member's source structure remains.
Substantive content inside a purported `diff:ws` wrapper is a conservative sequence
barrier because canonicalization still consumes that content. This is
reporting aggregation of existing selected evidence, without new matching
search or similarity checks.

Aggregation sorts and scans eligible selected links, with expected
O(G + M log M) extra work for G result groups and M selected links, and O(M)
index/output storage. It adds no similarity comparisons. The collector adds
per-revision counters to its existing source stack and context to retained
candidates. Key-string storage/comparison costs also depend on their lengths.
This reporting stage cannot recover an unmatched edited statement or detect
an entire method from a run of its interior statements. The primary reporting
projection adds expected linear indexing/copying work in selected member
references and their serialized endpoint/text sizes. See the
[sequence plan](plans/adjacent_move_sequences.md) for proposed changed-sequence
matching and the [semantic tests](../tests/behavior/test_move_sequences.py) for
implemented boundary checks.

### Diagnostics

`--diagnostics` is an opt-in results mode for algorithm review. Diagnostics
schema version `4` records unique Type-1/Type-2c and verified Type-3 edge classifications,
endpoint context independent of selection, retained candidates, and Type-3 shortlist
decisions, including observed line and token LCS evidence for below-threshold
pairs and whether a verified edge was selected. Each correspondence also says
whether current selection emitted it as a move. The legacy `shadow_change` field
names the location outcome for all three evidence types. File, mapped-container,
anchor-interval, relative-order, and ancestor observations are explicit.
Endpoint contexts also expose immediate `structural_region_id` and mapping
status, outer `anchor_region_id`, and common-sibling prefix/suffix ranks used
for crossing decisions.
An optional `identity_reason` separately records continuing-name corroboration,
contradiction, or an unsupported changed-name declaration. `identity_status`
is explicit in correspondence diagnostics, selected atomic moves, and primary
reported moves: `exact` describes Type-1 content equality (not resolved repeated
pairing), `corroborated` records independent replacement support, `tentative`
marks unsupported changed-name declarations, and `unassessed` marks other
normalized matches without independent corroboration. `contradicted` occurs
only in diagnostics. These states describe evidence, not semantic proof or
probabilities. Positive location remains required even for tentative matches;
contradictions remain a reporting veto.
Container-local anchor intervals are `different`, not crossed, when their
mapped containers differ. Diagnostics require `--results` and are not emitted
during ordinary runs.

### Observation-only Type-2b retrieval

Only `--diagnostics` enables a second lexical identity for Type-2b review.
Eligible structural candidates use the same literal categories, candidate kind,
comment/formatting exclusions, operators, and retained empty statements as
Type-2c, but every direct srcML `<name>` token becomes the same `$name` token.
Repeated-name patterns therefore need not agree. This is srcMove's blind
identifier normalization, not a claim of full BigCloneBench equivalence.
Ordinary runs do not construct this identity or retrieve blind groups.

`diagnostics.type2b_groups` is an additive array in diagnostics schema `4`:

- `correspondence_kind`: `"type2b"`
- `observation_only`: `true`
- `delete_candidate_ids` and `insert_candidate_ids`: sorted references to
  `diagnostics.candidates`, which retain each endpoint's XPath and raw text
- `cardinality`: `"one_to_one"` for a unique blind group, otherwise `"ambiguous"`
- `blind_only_pair_count`: the number of delete/insert combinations in the group
  whose Type-2c identities differ; it is not a selected-move count
- `location_change` and `location_reason`: existing location-classifier output
  for unique blind-only pairs; omitted for ambiguous groups

Only groups with a nonzero blind-only pair count are retained. A mixed group
can include endpoints that also form exact or Type-2c pairs; its count excludes
those stronger pairs. Retrieval observes all active Type-2c-eligible structural
candidates, including endpoints already selected or reserved by production.
It does not choose partners, reserve endpoints, build selection proposals, or
change Type-3 retrieval. Grouping and counting avoid expanding the full pair
product, and groups are sorted deterministically by endpoint IDs. With
`--profile`, diagnostic runs additionally emit
`profile.content_groups.type2b_diagnostics_ms` and
`profile.content_groups.type2b_groups_observed`.

Type-2b is absent from production `moves[].content_relationship`, `content_relationships`, and XML
annotations. Existing correspondence records remain unchanged; the new groups
live in their own array. Diagnostic and results-only modes preserve ordinary
results and selected XML annotations.

### Type-3 correspondence diagnostics

Type-3 location decisions are computed once per verified edge before production
selection, regardless of output mode. Selected and rejected
edges are both retained; below-threshold pairs remain shortlist observations and
do not become correspondence records. The shared classifier does not infer
parent carrying for edited Type-3 parents. Production proposals require positive
relocation evidence under the same predicate used for Type-1 and Type-2c pairs.

Type-3 records add `delete_verified_partner_count` and
`insert_verified_partner_count`, counting incident verified edges before
selection. Their `cardinality` is `competing_edges` if either endpoint has more
than one verified partner; otherwise it is `one_to_one`. These are local edge
degrees, not equivalence groups or proof of identity. Location and matching
ambiguity are separate: a competing edge can have `shadow_change: relocated`
without establishing a unique continuing construct. Connectivity never creates
additional edges. `current_result` records actual Type-3 selection after location
eligibility and hierarchy policy. A `current_result` of `not_move` means the edge was
not selected, not that it was established as stationary.

### Results terminology

Results schema `2` reports `moves[].content_relationship` and the top-level
`content_relationships` group counts. The values remain `type1`, `type2c`, and
`type3`. These are srcMove's predicted classifications of the reported
endpoints' contents under the thesis's Type-1, Type-2c, Type-2b, and Type-3
terminology. A classification does not establish continuity, relocation, or
computational equivalence. Each reported group contributes one count,
including groups with repeated endpoints.

The matching passes currently supply these predictions. Their rules do not
always identify the thesis's lowest applicable content type. In particular,
a blind-only Type-2b pair can be detected through Type-3 matching and receive
an incorrect `type3` classification. That is a classification disagreement,
separate from a detection miss. Type-1 canonicalization and Type-2c lexical
normalization also disregard different formatting details, and neither
identifier normalization nor literal normalization resolves bindings or tests
computation. This reporting change improves neither classification nor move
selection; no selected Type-2b category is manufactured.

Internal `match_kind` describes the matching pass and retains its name.
Diagnostic `correspondence_kind` identifies the comparison evidence for a
candidate correspondence, including unselected edges and observation-only
blind groups. It is not a reported endpoint content classification and remains
separate. `classification_reason` and `shadow_change` describe location
judgments. Type-3 shortlist `outcome` records retrieval or selection decisions.
Diagnostics schema remains `4`. Profiling names describe implementation stages.
XML has no content classification attribute: `mv:id`, `mv:from`, and `mv:to`
identify groups and partners and remain unchanged.

#### Incompatible stored output

Current consumers reject results schema `1`, the superseded `match_kind` and
`match_kinds` fields, and the legacy reported `type2` label. Retained results,
historical reviews, and frozen snapshots keep their original fields and labels;
they were not produced by schema `2` and must not be relabeled as new evidence.
`VERSION` is unchanged.

Regenerate detector JSON and benchmark runs with the rebuilt executable. Publish
new BigMoveBench benchmark-case collections (manifest and SQLite schema `2`)
from existing compiled data and selections, and create new execution journals
(schema/user version `2`, scoring oracle `9`, summary schema `3`). Existing compiled source data, selection populations,
and source inputs do not need to be reselected for this reporting change.
Current label correction snapshots use
`bigMoveBench/content_relationship_corrections.json` (schema `2`); the original
`reviewed_label_corrections.json` remains historical evidence. The current copy
retains the reviewed judgments and fragment hashes, with the historical
consistent `type2` expectations explicitly recorded as `type2c`.

Start fresh history analyses: database schema is `7`, compact-pair schema is `3`,
and results validator version is `3`. Older databases and cached outcomes are
incompatible. Preserve old state directories for evidence and create new ones;
do not resume an old analysis against the new binary. Current move-selection
benchmark catalogs use schema `3` and runs use schema `2`. Regenerate their output in a new directory.

#### srcDiffVisual follow-up (separate repository)

The companion application must adopt the new contract before using these runs:

- `srcdiffvisual/srcmove/srcmove_results.py` and
  `srcdiffvisual/srcmove/validate_results.py`: admit results schema `2`, require
  the new classification fields, reject legacy fields/labels, and preserve the
  new producer metadata. Audit projections and result enrichment, which copy
  producer data.
- `srcdiffvisual/artifacts/store.py`: emit `content_relationship` in move
  manifests; regenerate saved artifacts or explicitly version their contracts.
- `srcdiffvisual/bigmovebench/_browser.py`: expect browser response schema `2`.
  Update bundles/routes for `expected_content_relationship`,
  `reviewed_expected_content_relationship`, `observed_content_relationship`,
  `reviewed_content_relationship`, and `content_relationships`.
- `frontend/src/types.ts`, `frontend/src/history/types.ts`, and
  `frontend/src/bigmovebench/browserTypes.ts`: rename classification properties.
  Update artifact navigation, filtering, popups, summaries, HistoryInput, and
  SavedBenchmarkBrowser, plus their fixtures and tests. Remove `type2` label
  compatibility and present mismatches as classification disagreements.
- History status uses schema `3` with `moves.by_content_relationship`; pair list, pair detail, and comparison
  responses use schema `2`. Update `srcdiffvisual/history/client.py`
  expectations and route/tests accordingly. Rebuild the application's bundled srcMove/history
  code and refresh analyses and artifacts after the coordinated update.

No sibling code is changed by this task.


The JSON contract distinguishes evidence, endpoint cardinality, and counts:

- `content_relationship` (`type1`, `type2c`, or `type3`) predicts the
  contents' classification; `content_relationships` counts groups by prediction.
- `group_kinds` classifies endpoint cardinality: `move_1_to_1` is one deletion
  and one insertion, `moves_many` has equal counts greater than one, and
  `copy_or_repeat` normally has unequal nonzero counts; explicit continuing-source
  copies and unresolved residuals also use this kind, including one-to-one
  cardinality. `delete_only` and `insert_only`
  describe one-sided groups. The count classifier uses `ambiguous` for zero
  endpoints on both sides; this label is distinct from location ambiguity.
- `move_group_count` counts selected groups. The legacy `move_count` field is an
  alias for the same value; it does not count endpoint pairs.
- `move_pair_count` sums `min(deletions, insertions)` over selected groups. For
  repeated-content groups this is a capacity estimate, not a claimed pairing.
- `annotated_region_count` counts selected endpoints. The legacy
  `annotated_regions` field is an alias for the same value.

`confidence_milli` is an internal ranking value on a 0–1000 scale. It is not a
calibrated probability.

## Matching and group semantics

The matching passes currently supply these classifications:

- `type1`: identical comment- and formatting-insensitive canonical
  structure and meaningful text
- `type2c`: identical consistent-identifier- and literal-category-normalized
  lexical form, with the same candidate element kind
- `type3`: eligible unmatched candidates satisfy the 0.90 bounded-LCS rule
- none: no accepted pair is emitted; candidates remain unmatched

Selected groups are either one-to-one correspondences or exact multi-endpoint
equivalence classes. Multi-endpoint groups describe move/copy or repeated
content without claiming a particular pairing. Ambiguous normalized Type-2c
classes are not selected.

## Performance model

Parsing, candidate selection, and canonicalization share one streaming input
pass. The pipeline retains completed candidates, their cached representations,
lightweight region bookkeeping, and compact candidate-id groups, but not a full
XML tree or captured node subtrees. Normal annotation uses a second streaming
pass; `--results-only` omits it. Hash indexing and exact-text partitioning avoid
constructing the full delete-by-insert Cartesian product for Type 1 and Type 2.
Cached normalized segment and token hashes, element-kind partitioning,
per-representation size windows, and early-exit LCS constrain Type-3 work. The
implementation exposes coarse `--profile` timings for repeatable pipeline
measurements.

This design is intended to scale more predictably than exhaustive pairwise tree
comparison, but the repository does not currently claim a general complexity or
performance result for arbitrary projects.

## Current limitations

- The selector uses deterministic greedy utility selection plus a local
  parent-versus-descendant bundle comparison. It is not a general hierarchy or
  graph optimizer.
- Exact repeats retain group-level correspondence for portions lacking
  independent sibling or local-region evidence. Partial and unequal classes may
  contain both supported individual correspondences and unresolved residuals.
  Residual move groups require possible displacement evidence; explicit copies
  retain a proven continuing origin. Ambiguous Type-2c repeats remain unresolved.
- Type-3 retrieval uses kind and size windows but not an approximate-neighbor
  index or configurable top-`k` shortlist.
- Type-4 moves are not supported.
- Exact, Type-2c, and Type-3 matching use statement-or-larger candidates by
  default. Tiny fragments can be enabled explicitly but are not useful as the
  default move unit.
- Confidence is an interpretable ranking value, not a calibrated probability.
  There is no locality model, behavioral model, or developer-intent
  reconstruction.
- srcMove depends on the regions exposed by srcDiff; it is not a general diff
  engine and does not recover changes that srcDiff does not represent as usable
  candidates.
- Individual Type-1, Type-2c, and Type-3 output requires positive relocation evidence from
  revision files, mapped semantic containers, or crossed stable anchors. Missing
  context remains ambiguous, not proven stationary. This policy does not
  reconstruct developer intent. Genuine same-file edited moves with insufficient
  mapped context can remain unreported; content similarity alone is insufficient.

Richer structural similarity and broader ambiguous-group disambiguation remain
research directions.
