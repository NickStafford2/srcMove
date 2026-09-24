# srcMove Architecture

srcMove is a C++ command-line tool that post-processes srcDiff XML and marks
delete/insert regions that represent relocated source code. Its primary research
focus is move detection across file boundaries, where an operation that a
developer understands as one move otherwise appears as an unrelated deletion
and insertion in different files.

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

The production path in
[`src/region_filter.cpp`](../src/region_filter.cpp) makes one streaming pass over
the input. It distinguishes single-file and archive srcDiff shapes, tracks the
file ownership and nesting of each `diff:delete` and `diff:insert`, and builds
move candidates as XML events arrive. That file ownership permits a deletion in
one file to match an insertion in another.

Candidate construction and canonicalization are part of this same pass. A
revision-state stack gives substantive events the ownership of their nearest
`diff:delete`, `diff:insert`, or `diff:common` wrapper. Same-side nesting retains
parents and complete descendants as alternatives. A candidate containing
substantive common or opposite-side material is rejected as an atomic move,
while pure descendants survive. Completed candidates own compact matching
representations; the pipeline does not retain captured srcML trees.

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
ignores empty statements as well as comments and formatting. Other source
tokens and operators remain unchanged. Group keys also include the candidate's
srcML element kind, so lexically identical constructs of different kinds do not
collapse into one group.

Candidates are bucketed with 64-bit FNV-1a hashes of that canonical form. A hash
is only an index: groups are split and confirmed using the full canonical text,
so a hash collision is not accepted as a move.

[`src/move_registry/content_group_builder.cpp`](../src/move_registry/content_group_builder.cpp)
builds all supported evidence before selection. Pure ranking and descendant
bundle policy, including its declared constants, lives in
[`src/move_registry/selection_policy.cpp`](../src/move_registry/selection_policy.cpp):

1. forms exact canonical-text groups
2. groups eligible constructs by exact Type-2 representation
3. generates Type-3 edges for structurally compatible candidates
4. turns unique exact and Type-2 correspondences plus verified Type-3 edges
   into one proposal set
5. ranks proposals by size-aware utility plus an internal structural-coverage
   term, then confidence, evidence class, source-construct preference, and
   deterministic candidate identifiers
6. greedily selects proposals subject to one-use and source/destination span
   overlap constraints
7. emits remaining delete-only and insert-only groups for reporting

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
both `L / |A| >= 0.70` and `L / |B| >= 0.70`. This is equivalent to
`L / max(|A|, |B|) >= 0.70`. A candidate pair qualifies when either the
statement/block view or token view accepts; its stronger similarity orders the
edge.

The comparison first rejects impossible size ratios, then runs a two-row LCS
that exits when the remaining rows cannot reach the required common length.
Candidates are restricted to the same eligible srcML element kind and the 0.70
size window, rather than forming an unrestricted delete-by-insert product.
Type-1, Type-2, and Type-3 proposals compete in the same utility ordering. A
large verified near-match can therefore suppress a small exact descendant.
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
and the selection reason as JSON. With `--results-only`, srcMove materializes
that JSON evidence from candidate-owned XPaths and skips the second XML pass
entirely.

`--diagnostics` is an opt-in results mode for algorithm review. It records the
retained candidates and Type-3 shortlist decisions, including observed line and
token LCS evidence for below-threshold pairs and whether a verified edge was
selected. It requires `--results` and is not emitted during ordinary runs.

## Matching and group semantics

The matcher reports four classification outcomes:

- `exact` (Type 1): identical comment- and formatting-insensitive canonical
  structure and meaningful text
- `type2`: identical identifier- and literal-normalized canonical structure
- `type3`: eligible unmatched candidates satisfy the 0.70 bounded-LCS rule
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

Richer structural similarity, contextual scoring, and ambiguous-group
disambiguation are research directions rather than implemented features.

## Scoped BigCloneBench results

The archived thesis run from 2026-07-30 used srcMove commit `3afbc86` and
BigCloneBench-derived synthetic move cases with `--dedupe raw-text-pair` and
`--limit 1000`. The archived data lives in the separate thesis repository under
`doc/thesis/thesis-data/20260730T215344Z/`.

- Type-1 selected 915 deduplicated cases: 909 passed and 6 failed.
- Type-2 selected 640 deduplicated cases: 286 passed and 354 failed.

These cases are synthesized from known clone pairs: the runner extracts two
Java fragments, places them in before/after source layouts, runs srcDiff and
srcMove, and checks for the expected move. They are not historical edit ground
truth and must not be reported as detector-wide precision or recall.

See [BigCloneBench notes](../bigMoveBench/docs/bigclonebench.md) and
[the conversion methodology](../bigMoveBench/docs/methodology.md) for the
dataset interpretation and test construction details.
