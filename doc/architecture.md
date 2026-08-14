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
captured srcML events into a canonical structural string. The default form
ignores the outer diff wrapper, `diff:ws` elements, and whitespace-only text
while retaining element structure and meaningful text.

Candidates are bucketed with 64-bit FNV-1a hashes of that canonical form. A hash
is only an index: groups are split and confirmed using the full canonical text,
so a hash collision is not accepted as a move.

[`src/move_registry/content_group_builder.cpp`](../src/move_registry/content_group_builder.cpp)
then:

1. forms exact canonical-text groups
2. selects exact groups while suppressing overlapping parent/child candidates
3. considers unmatched eligible constructs for Type-2 matching
4. accepts only one-delete/one-insert Type-2 groups
5. emits remaining delete-only and insert-only groups for reporting

Type-2 matching uses a second canonical form that consistently replaces
identifier text inside `name` elements while retaining names used as types. It
is intentionally limited to selected structural constructs and statements.

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

The current matcher reports two match kinds:

- `exact`: delete and insert candidates have identical canonical structure and
  meaningful text
- `type2`: one eligible delete and insert have identical identifier-normalized
  canonical structure

Groups are classified by their delete/insert counts, including one-to-one,
many-to-many, copy-or-repeat, delete-only, and insert-only cases. Groups with
multiple candidates share one move identifier and partner XPath set; srcMove
does not yet infer a unique pairing within an ambiguous many-to-many group.

## Performance model

Parsing and writing are streaming passes, while collected regions, candidates,
and compact candidate-id groups remain in memory. Hash indexing and exact-text
partitioning avoid constructing the full delete-by-insert Cartesian product.
The implementation exposes coarse `--profile` timings for repeatable pipeline
measurements.

This design is intended to scale more predictably than exhaustive pairwise tree
comparison, but the repository does not currently claim a general complexity or
performance result for arbitrary projects.

## Current limitations

- Type-3 and Type-4 moves are not supported.
- Type-2 support is identifier normalization for eligible one-to-one constructs,
  not general near-miss clone detection.
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
