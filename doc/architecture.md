# srcMove Architecture

srcMove is a C++ command-line tool that post-processes srcDiff XML and marks
regions that its matching and selection policy identifies as relocated source
code. Its primary research focus is move detection across file and structural
boundaries, with Type-1, Type-2, and Type-3 correspondence evidence.

## Terminology

srcDiff represents source present only in the original revision with
`diff:delete` and source present only in the modified revision with
`diff:insert`. A *reported move* is a selected pair or group of deleted and inserted
candidates. It is an operational detector result, not proof of a historical
move, developer intent, or semantic equivalence. A content match supports a
proposed correspondence; it does not establish continuing identity by itself.
Type-1, Type-2, and Type-3 describe content evidence; group kind separately
describes endpoint cardinality and ambiguity. Reported moves are broader than
classifier-confirmed relocation: unique Type-1 and Type-2 pairs require positive
location evidence, whereas Type-3 selection and repeated exact groups follow
their separate policies described below.

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
candidates. After the streaming pass, complete common declarations and
conditionals (`decl_stmt` and `if_stmt`) with substantive text and unique exact
canonical identity in a mapped container become stable anchors. Mixed or
repeated constructs are excluded. Independent declaration and conditional
collectors preserve declarations inside mixed conditionals. Conditional capture
restarts at each nested common `if_stmt`, retaining innermost conditionals even
inside an edited outer conditional, with at most two canonicalizers active. Each mapped candidate receives the
nearest nonoverlapping anchors by their end/start positions, independent of
collection order, falling back to container-begin and container-end sentinels.
This exposes crossings of unchanged conditionals without tree rematching.
Enclosing conditionals are not also retained as anchors; repeated innermost
conditionals can therefore still leave order unresolved.
Unmapped candidates retain unreliable anchor intervals. Production selection
consumes this context for unique one-to-one Type-1 and Type-2 correspondences.

This distinction permits a deletion in one archive unit to match an insertion
in another without mistaking a combined srcDiff filename for one revision's
file identity.

### Location classification vocabulary

[`src/movement_classifier.cpp`](../src/movement_classifier.cpp) contains a pure,
ordered location classifier. Its outcomes describe the implemented location
model, not universal categories of source-code changes.

| Implementation label | Meaning under the current policy |
| --- | --- |
| `relocated` | Different revision-specific file paths, different mapped enclosing constructs, or a crossed reliable anchor interval provide relocation evidence. |
| `stationary` | Within the same file and mapped container, reliable anchor intervals and interpretable ancestor summaries agree. A later carrying check also uses this label for a child stable relative to a relocated parent. |
| `restructured` | Within the same file, mapped container, and reliable anchor interval, an interpretable ancestor summary is a strict prefix of the other, indicating the supported wrapping or unwrapping pattern. |
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
Unique Type-2 groups are classified once after exact grouping has removed Type-1
correspondences. The same decisions control eligibility and diagnostics: only
`relocated` pairs enter selection. Each unique Type-2 pair reserves its endpoint
IDs before Type-3 retrieval, regardless of location outcome or final selection.
Reservation prevents weaker alternate partners without reserving spans, so
distinct enclosing and descendant proposals still compete normally.
Type-2 decisions do not participate in exact-parent carrying, since containment
inside an edited parent does not establish stable relative position.
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
identifiers, literals, keywords, operators, and srcML structure. The Type-2
identity is a compact lexical form: it consistently numbers direct srcML
`<name>` tokens by first occurrence, replaces literals with their category
(`integer`, `floating`, `string`, `character`, `boolean`, or `null`), and
ignores comments and formatting. Empty statements remain in the lexical form:
adding or removing one requires Type-3 similarity assessment rather than Type-2
equality. Other source tokens and operators remain unchanged. Group keys also
include the candidate's srcML element kind, so lexically identical constructs of different kinds do not
collapse into one group.

Candidates are bucketed with 64-bit FNV-1a hashes of that canonical form. A hash
is only an index: groups are split and confirmed using the full canonical text,
so a hash collision is not accepted as a move.

Type-2 eligibility is narrower than general candidate eligibility. The stream
admits structural constructs (including functions and declarations of functions,
types, and namespaces) plus `decl_stmt`, `if_stmt`, `for`, `while`, `do`,
`switch`, and `try` statements. Standalone `expr_stmt` and `return` candidates
can participate in exact Type-1 matching but are excluded from Type-2 grouping.
The [historical study](../moveSelectionBench/historical_study/README.md) contains
a source-reviewed renamed call reorder that reaches candidate construction but
misses at this eligibility boundary. This is a limitation, not a negative move
oracle or a lack of source evidence for relocation.

[`src/move_registry/content_group_builder.cpp`](../src/move_registry/content_group_builder.cpp)
builds all supported evidence before selection. Pure ranking and descendant
bundle policy, including its declared constants, lives in
[`src/move_registry/selection_policy.cpp`](../src/move_registry/selection_policy.cpp):

1. forms exact canonical-text groups
2. classifies unique one-to-one exact correspondences and admits only supported
   relocations to production proposal selection; non-1x1 exact groups retain
   existing group policy
3. groups eligible constructs by exact Type-2 representation, classifies unique
   pairs, and reserves their endpoint identities
4. generates Type-3 edges for remaining structurally compatible candidates
5. turns eligible exact and Type-2 correspondences plus verified Type-3 edges
   into one proposal set
6. disables unique Type-1 and Type-2 proposals without positive relocation
   decisions before hierarchy selection
7. ranks proposals by size-aware utility plus an internal structural-coverage
   term, then confidence, evidence class, source-construct preference, and
   deterministic candidate identifiers
8. greedily selects proposals subject to one-use and source/destination span
   overlap constraints
9. emits remaining delete-only and insert-only groups for reporting

Repeated exact equivalence classes are retained as multi-endpoint move/copy
groups with ambiguity-aware confidence; they do not claim an individual
pairing. Repeated Type-2 classes remain unresolved because normalization has
already removed distinguishing content, and document order alone is not
correspondence evidence.

Type-3 uses a NiCad-inspired sequence rule implemented directly in srcMove; no
NiCad executable or runtime dependency is involved. Canonicalization caches two
compact views: normalized code divided at statement and block boundaries (`;`,
`{`, and `}`), and a finer token sequence. Both similarity views retain the
Type-2 representation's consistent first-occurrence name mapping. This keeps
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
Eligible Type-1, Type-2, and Type-3 proposals compete in the same utility
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
match kinds, source/destination XPaths, raw texts, candidate counts, group
classifications, confidence in thousandths, matched units, selection utility,
and the selection reason as JSON. The top-level `results_schema_version`
identifies this contract and is currently `1`. With `--results-only`, srcMove
materializes that JSON evidence from candidate-owned XPaths and skips the
second XML pass entirely.

`--diagnostics` is an opt-in results mode for algorithm review. Diagnostics
schema version `4` records unique Type-1/Type-2 and verified Type-3 edge classifications,
endpoint context independent of selection, retained candidates, and Type-3 shortlist
decisions, including observed line and token LCS evidence for below-threshold
pairs and whether a verified edge was selected. Each correspondence also says
whether current selection emitted it as a move. The legacy `shadow_change` field
names the location outcome for all three evidence types. File, mapped-container,
anchor-interval, relative-order, and ancestor observations are explicit.
Container-local anchor intervals are `different`, not crossed, when their
mapped containers differ. Diagnostics require `--results` and are not emitted
during ordinary runs.

Type-3 location decisions are observation-only, computed once per verified edge
when diagnostics are requested, after production selection. Selected and rejected
edges are both retained; below-threshold pairs remain shortlist observations and
do not become correspondence records. The shared classifier does not infer
parent carrying for edited Type-3 parents. Ordinary eligibility is unchanged.

Type-3 records add `delete_verified_partner_count` and
`insert_verified_partner_count`, counting incident verified edges before
selection. Their `cardinality` is `competing_edges` if either endpoint has more
than one verified partner; otherwise it is `one_to_one`. These are local edge
degrees, not equivalence groups or proof of identity. Location and matching
ambiguity are separate: a competing edge can have `shadow_change: relocated`
without establishing a unique continuing construct. Connectivity never creates
additional edges. `current_result` records actual Type-3 selection, independently
of these observations. A `current_result` of `not_move` means the edge was
not selected, not that it was established as stationary.

### Results terminology

The JSON contract distinguishes evidence, endpoint cardinality, and counts:

- `match_kind` (`type1`, `type2`, or `type3`) states why candidate content
  corresponds.
- `group_kinds` classifies endpoint cardinality: `move_1_to_1` is one deletion
  and one insertion, `moves_many` has equal counts greater than one, and
  `copy_or_repeat` has unequal nonzero counts. `delete_only` and `insert_only`
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

The matcher reports four classification outcomes:

- `type1`: identical comment- and formatting-insensitive canonical
  structure and meaningful text
- `type2`: identical identifier- and literal-normalized canonical structure
- `type3`: eligible unmatched candidates satisfy the 0.90 bounded-LCS rule
- none: no accepted pair is emitted; candidates remain unmatched

Selected groups are either one-to-one correspondences or exact multi-endpoint
equivalence classes. Multi-endpoint groups describe move/copy or repeated
content without claiming a particular pairing. Ambiguous normalized Type-2
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
- Exact repeats retain group-level correspondence, but contextual evidence for
  disambiguating individual repeated moves is not implemented. Ambiguous
  Type-2 repeats remain unresolved.
- Type-3 retrieval uses kind and size windows but not an approximate-neighbor
  index or configurable top-`k` shortlist.
- Type-4 moves are not supported.
- Exact, Type-2, and Type-3 matching use statement-or-larger candidates by
  default. Tiny fragments can be enabled explicitly but are not useful as the
  default move unit.
- Confidence is an interpretable ranking value, not a calibrated probability.
  There is no locality model, behavioral model, or developer-intent
  reconstruction.
- srcMove depends on the regions exposed by srcDiff; it is not a general diff
  engine and does not recover changes that srcDiff does not represent as usable
  candidates.
- Unique Type-1 and Type-2 output requires positive relocation evidence from
  revision files, mapped semantic containers, or crossed stable anchors. Missing
  context remains ambiguous, not proven stationary. This policy does not
  reconstruct developer intent or resolve repeated NxM groups. Type-3 movement
  classification is observation-only; its existing similarity and selection policy
  remains active for endpoints without stronger correspondence identity.

Richer structural similarity, contextual scoring, and ambiguous-group
disambiguation are research directions rather than implemented features.
