# srcMove Architecture

srcMove is a C++ command-line tool that post-processes srcDiff XML and marks
delete/insert regions that represent relocated source code. Its primary research
focus is move detection across file boundaries, where an operation that a
developer understands as one move otherwise appears as an unrelated deletion
and insertion in different files.

The current implementation is a deterministic structural matcher. It uses the
srcML structure embedded in srcDiff XML, but it does not yet use probabilistic
scoring, general semantic equivalence, or an AST-similarity model.

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

### 1. Parse diff regions

[`src/parse/diff_region.cpp`](../src/parse/diff_region.cpp) makes one pass over
the input and records every `diff:delete` and `diff:insert` region. Each record
includes its file, nesting relationship, node span, XPath, raw text, captured
srcML nodes, and canonical representations.

The parser explicitly distinguishes single-file and archive srcDiff shapes.
That file ownership is what permits a delete in one file to match an insert in
another.

### 2. Select move candidates

[`src/region_filter.cpp`](../src/region_filter.cpp) applies the default candidate
policy:

- start from leaf diff regions
- exclude whitespace-only and very small payloads
- expand eligible diff regions into preferred structural children and
  statements, such as functions, classes, declarations, conditionals, and loops

This expansion lets srcMove annotate the moved source construct instead of an
overly broad surrounding diff wrapper when the structure supports it.

### 3. Canonicalize and group

[`src/parse/canonical_subtree.cpp`](../src/parse/canonical_subtree.cpp) converts
captured srcML events into cached canonical representations. The Type-1 form
ignores the outer diff wrapper, comments, `diff:ws` elements, and formatting-only
text while retaining identifiers, literals, keywords, operators, and srcML
structure. The Type-2 form additionally renames identifiers consistently by
first occurrence and replaces literals with their category (`integer`,
`floating`, `string`, `character`, `boolean`, or `null`). Language keywords,
operators, and structural distinctions remain unchanged.

Candidates are bucketed with 64-bit FNV-1a hashes of that canonical form. A hash
is only an index: groups are split and confirmed using the full canonical text,
so a hash collision is not accepted as a move.

[`src/move_registry/content_group_builder.cpp`](../src/move_registry/content_group_builder.cpp)
then:

1. forms exact canonical-text groups
2. selects exact groups while suppressing overlapping parent/child candidates
3. groups unmatched eligible constructs by exact Type-2 representation
4. selects unambiguous Type-2 pairs, including deterministic positional pairing
   when both sides have the same multiplicity
5. compares the remaining eligible structural candidates for Type-3 similarity
6. emits remaining delete-only and insert-only groups for reporting

Type-3 uses a NiCad-inspired sequence rule implemented directly in srcMove; no
NiCad executable or runtime dependency is involved. During canonicalization,
the Type-2-normalized token stream is divided at statement and block boundaries
(`;`, `{`, and `}`), and each resulting segment is hashed to a 64-bit integer.
For sequences `A` and `B` with longest common subsequence length `L`, a pair is
accepted exactly when both `L / |A| >= 0.70` and `L / |B| >= 0.70`. This is
equivalent to `L / max(|A|, |B|) >= 0.70`.

The comparison first rejects impossible size ratios, then runs a two-row LCS
that exits when the remaining rows cannot reach the required common length.
Candidates are restricted to the same eligible srcML element kind and the 0.70
size window, rather than forming an unrestricted delete-by-insert product.
Accepted edges are ordered by similarity, then size and candidate ID, and are
selected greedily one-to-one. This makes output deterministic. Type-1 and
Type-2 selection always precede Type-3, and an ambiguous exact Type-2 identity
is never relabeled as the weaker Type-3 kind.

### 4. Annotate the XML

The writer makes a second XML pass and preserves unmodified input nodes. For
each group containing both deletes and inserts, it adds the srcMove namespace
and annotates matched start tags with:

- `mv:id`: the shared move-group identifier
- `mv:to`: destination XPath or XPath union on a deletion
- `mv:from`: source XPath or XPath union on an insertion

Annotations may be placed on a structural child inside a diff wrapper rather
than on the wrapper itself. The optional `--results` output records move groups,
match kinds, source/destination XPaths, raw texts, candidate counts, and group
classifications as JSON.

## Matching and group semantics

The matcher reports four classification outcomes:

- `exact` (Type 1): identical comment- and formatting-insensitive canonical
  structure and meaningful text
- `type2`: identical identifier- and literal-normalized canonical structure
- `type3`: eligible unmatched candidates satisfy the 0.70 bounded-LCS rule
- none: no accepted pair is emitted; candidates remain unmatched

Groups are classified by their delete/insert counts, including one-to-one,
many-to-many, copy-or-repeat, delete-only, and insert-only cases. Groups with
multiple candidates share one move identifier and partner XPath set; srcMove
does not yet infer a unique pairing within an ambiguous many-to-many group.

## Performance model

Parsing and writing are streaming passes, while collected regions, candidates,
and compact candidate-id groups remain in memory. Hash indexing and exact-text
partitioning avoid constructing the full delete-by-insert Cartesian product for
Type 1 and Type 2. Cached normalized segment hashes, element-kind partitioning,
the size-ratio bound, and early-exit LCS constrain Type-3 work. The
implementation exposes coarse `--profile` timings for repeatable pipeline
measurements.

This design is intended to scale more predictably than exhaustive pairwise tree
comparison, but the repository does not currently claim a general complexity or
performance result for arbitrary projects.

## Current limitations

- Type-4 moves are not supported.
- Type-2 and Type-3 are limited to eligible structural constructs and selected
  statement kinds; tiny fragments are not promoted into near-miss matches.
- There is no probabilistic confidence score, locality model, behavioral model,
  or developer-intent reconstruction.
- Many-to-many and unequal-count groups are classified but not fully paired or
  disambiguated.
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

See [BigCloneBench notes](bigclonebench_notes.md) and
[the conversion methodology](bigclonebench_srcmove_conversion.md) for the
dataset interpretation and test construction details.
