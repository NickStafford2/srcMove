# Converting BigCloneEval Into srcMove Tests

BigCloneEval is not a move-detection benchmark by itself. Its positive oracle is
a set of clone pairs: two independently existing Java function fragments that
implement the same functionality. The current srcMove evaluation synthesizes a
before/after edit where one clone fragment is deleted from the old version and
its paired clone fragment is inserted at a different location in the new
version.

The resulting pass rate is a strict whole-fragment synthetic
detection-and-classification rate for the declared slice and oracle. It is not
historical-move accuracy, general detector recall, overall accuracy, or
precision.

## Local Assets

Install BigCloneEval manually at
`bigMoveBench/data/BigCloneEval/` and follow its setup instructions
in `bigMoveBench/data/BigCloneEval/ReadMe.md` or the upstream README
at <https://github.com/jeffsvajlenko/BigCloneEval>. This checkout expects the
two required inputs at:

```text
bigMoveBench/data/BigCloneEval/bigclonebenchdb/bcb.h2.db
bigMoveBench/data/BigCloneEval/ijadataset/{default,sample,selected}/*.java
```

The H2 database contains the truth tables:

```sql
FUNCTIONS(NAME, TYPE, STARTLINE, ENDLINE, ID, NORMALIZED_SIZE, PROJECT, TOKENS, INTERNAL)
CLONES(FUNCTION_ID_ONE, FUNCTION_ID_TWO, FUNCTIONALITY_ID, TYPE, SYNTACTIC_TYPE,
       SIMILARITY_LINE, SIMILARITY_TOKEN, MIN_SIZE, MAX_SIZE, MIN_PRETTY_SIZE,
       MAX_PRETTY_SIZE, MIN_JUDGES, MIN_CONFIDENCE, MIN_TOKENS, MAX_TOKENS, INTERNAL)
```

`FUNCTIONS.TYPE` is the IJaDataset subdirectory (`selected`, `default`, or
`sample`), and `FUNCTIONS.NAME` is the Java file name.

## Conversion Model

For each selected clone pair:

1. Join `CLONES` to `FUNCTIONS` twice.
2. Extract `function_id_one` lines from its source file.
3. Extract `function_id_two` lines from its source file.
4. Build an old two-file archive containing fragment one in a stable source
   class and an empty destination class.
5. Build a new archive with the source class empty and fragment two in the
   destination class. Both relative files and their distinct classes remain
   present across revisions.
6. Run `srcDiff original/ modified/ --position` in archive mode.
7. Verify that srcDiff exposed the intended synthetic payload as usable
   delete/insert regions.
8. Run `srcMove` over eligible srcDiff XML.
9. Score whether any single reported move links both complete generated fragment
   texts and that same move's XML delete/insert annotations overlap the expected
   line ranges. Other reported moves are incidental evidence, not a rejection.

Each generated revision contains the same two relative paths,
`source/input.java` and `destination/input.java`. srcDiff therefore compares the
stable source file across revisions and exposes the removed payload there, then
compares the stable destination file and exposes the inserted payload there.
The two distinct container classes prevent the wrappers themselves from looking
like a cross-file move.

The current evaluation uses a strict detection-and-classification oracle:
Type-1 cases must classify the intended whole-fragment move as `exact`, Type-2
as `type2`, and Type-3 as `type3`. Position and per-side text validation are
correlated to that move by its result `move_id` and XML `mv:id`/link attributes.
Detecting the intended payload with the wrong match kind is useful failure
evidence, but it is not counted as a pass. Type-3 recall is observational. The
benchmark deliberately uses BigCloneBench as the best available large labeled
source; questionable labels,
unsupported variations, extraction problems, or conversion artifacts discovered
in the failure set should be analyzed and reported rather than silently removed.

This converts clone similarity into move similarity. Exact and Type-2 clone pairs
are the best first target for srcMove because they align with the current exact and
Type-2 match categories. Type-3 and Type-4 pairs are useful later as expected misses
or as recall targets for future similarity scoring.

## Type-3 Similarity Reference

BigCloneBench records `similarity_line` and `similarity_token` for every positive
clone row. These values measure shared normalized syntax rather than raw-text
equality. BigCloneEval's conservative `BOTH` score is the lower of the two:

```text
bigclonebench_both = min(similarity_line, similarity_token)
```

BigMoveBench retains both source values. For a deduplicated Type-3 execution
frame supported by multiple catalog rows, its current strength is the minimum
`BOTH` value across those rows. Sampled Type-3 selections stratify that value as
`>= .90`, `[.70, .90)`, `[.50, .70)`, and `< .50`.

This is a useful external reference for evaluating a srcMove Type-3 score, but it
is not an interchangeable oracle. BigCloneBench computes line and token scores
over its own normalized comparison form; srcMove uses its own srcML-derived
statement/block and token sequences. A sound comparison should therefore report
rank correlation, error or score differences, and detection/classification rates
by BigCloneBench strength band rather than assuming equal numeric scores have
identical meaning. Report the declared selection and active srcMove threshold
with every result. See [the BigCloneBench data notes](bigclonebench.md#similarity_line--similarity_token)
for the upstream score interpretation.

## srcDiff Eligibility Boundary

Well-formed srcDiff XML does not prove that srcDiff exposed the intended
BigCloneBench payload. srcDiff may legally align the synthetic source differently
and omit the delete/insert regions that srcMove would need as candidates. srcMove
cannot recover a move that is absent from its input, so such a case must not be
reported as a srcMove detection miss.

The staged BigCloneBench pipeline applies a versioned semantic eligibility check
before srcMove evaluation. For each side, it finds `diff:delete` or `diff:insert`
regions and aggregates their descendant `pos:start` and `pos:end` line numbers.
A case is eligible only when one delete region covers the complete generated
source range and one insert region covers the complete generated target range.
This deliberately tests candidate exposure rather than srcMove behavior. The
pipeline keeps these outcomes distinct:

- srcDiff failed, timed out, or produced malformed output
- srcDiff produced valid XML but did not expose the intended payload
- srcMove ran on an eligible input but missed the expected move
- srcMove satisfied the positional, text, and match-kind oracle

The per-run summary reports both the end-to-end strict pass rate over generated
cases and the conditional srcMove detection-and-classification rate over
srcDiff-eligible cases. The eligibility and scoring oracle versions are recorded
in the benchmark-case and execution artifacts.

## Exploratory Query and Thesis Selection

The following ordered query is useful for smoke tests and debugging, beginning
with Type-1. Its first `LIMIT` rows are a deterministic convenience slice, not a
random or representative sample and not a basis for inference about the wider
eligible population:

```sql
SELECT
  c.function_id_one,
  f1.type AS type1, f1.name AS name1, f1.startline AS startline1, f1.endline AS endline1,
  c.function_id_two,
  f2.type AS type2, f2.name AS name2, f2.startline AS startline2, f2.endline AS endline2,
  c.syntactic_type, c.similarity_line, c.similarity_token, c.min_tokens
FROM clones c
JOIN functions f1 ON f1.id = c.function_id_one
JOIN functions f2 ON f2.id = c.function_id_two
WHERE c.syntactic_type IN (1, 2)
  AND c.internal = FALSE
ORDER BY c.syntactic_type, c.functionality_id, c.function_id_one, c.function_id_two
LIMIT 100;
```

Then broaden by buckets. A bucket is a named subset of BigCloneBench rows chosen
to answer one testing question, such as exact-move recall, renamed-code recall,
near-miss behavior, or default-vs-internal benchmark coverage. Keep buckets
separate in reports so one easy category does not hide failures in another.

```text
syntactic_type = 1             exact / Type-1 move baseline
syntactic_type = 2             renamed / Type-2 move baseline
syntactic_type = 3, sim >= .90 near-miss or future Type-3 recall
syntactic_type = 3, sim < .70  expected miss / stress cases
internal = FALSE/TRUE          default BigCloneEval rows vs internal rows
f1.project = f2.project        intra-project rows
f1.project != f2.project       inter-project rows
```

Before a thesis evaluation, choose and freeze one of two defensible designs:

- a census of a precisely declared eligible population
- a seeded sample from a declared frame, stratified where needed by clone type,
  functionality, size, raw-text relationship, or project relationship

The selection manifest must preserve the exact query and parameters, database
checksum, ordered eligible and selected row IDs, pre/post-deduplication counts,
sampling seed and strata when applicable, and wrapper/oracle versions. Report
functionality coverage and distinct raw-text-pair coverage so repeated clone rows
cannot masquerade as independent variety.

BigCloneBench treats clone pairs as unordered, but the synthetic edit has a
direction. BigMoveBench uses one deterministic canonical direction per exact
unordered fragment-content pair and retains reverse rows as provenance rather
than executing the same generated input twice.

The current compiled external dataset contains 8,648,734 available labeled pair
rows: 47,146 Type-1 rows, 4,223 Type-2 rows, 8,323,944 Type-3 rows, and 273,421
known-false-positive rows. These collapse to 6,011,979 unique unordered
fragment-content pairs across label kinds. Type 1 collapses to 951 unique content
pairs, Type 2 to 567, and known false positives to about 232,509; Type 3 accounts
for the remaining multimillion-case scale. Counts are dataset-specific and must
be read from the compiled manifest and selection manifests for every reported
run rather than treated as timeless constants.

For BigMoveBench, a full census means **all eligible unique
BigCloneBench-labeled fragment pairs after declared exclusions and
deduplication**. It does not mean the Cartesian product of all IJaDataset
functions or fragments. The default execution unit is one canonical direction
per exact unordered fragment-content pair, while every contributing
BigCloneBench row and its multiplicity remain attached as provenance.

## Practical Test Layout

The canonical workflow publishes content-addressed artifacts rather than a
mutable directory of generated cases:

```text
bigMoveBench/cache/
  bigclonebench/
    compiled/<dataset-id>/
    selections/<selection-id>/
  generated-objects/<object-id>.java
  benchmark-cases/<benchmark-cases-id>/benchmark_cases.sqlite

benchmark-results/bigMoveBench/runs/<run-id>/
  execution.sqlite
  summary.json
  cases.csv
```

Selection frames retain BigCloneBench row and function identities, similarity
fields, fragment hashes, and pair direction. The benchmark-case database adds
the generated-object references, exact deleted and inserted text, and generated
line ranges. Evaluation uses those ranges and texts rather than requiring stable
srcMove UUIDs or absolute xpaths.

Selection defaults to `--dedupe exact-unordered-fragment-pair`, which groups
rows by the two extracted fragment hashes without erasing whitespace or comment
differences. `--dedupe none` remains available for row-based audits. Reverse
directions and duplicate source rows remain attached to the selected frame as
evidence rather than producing repeated executions.

Do not assume the BigCloneBench Type-1 frame contains thousands of
formatting-only variants. With `syntactic_type = 1`, no token-size threshold,
and `internal = FALSE`, the compiled catalog has 47,146 available rows but only
951 unique unordered raw-fragment pairs. Most distinct pairs still contain
identical extracted fragment text on both sides. Keep hand-authored
whitespace/comment fixtures for targeted Type-1 whitespace behavior.

## Known False-Positive Conversion

Known false positives are selected from `false_positives` and joined to
`functions` for source locations, token counts, and the external/internal flag.
The table has no `min_tokens` or `internal` columns of its own. Selection keeps
only pairs whose two functions are external, then applies the configured minimum
judge and confidence thresholds. Token size is retained as reporting metadata
but does not determine eligibility. The ordered table direction is preserved as
fragment one deleted and fragment two inserted.

Generation reuses the positive cases' extraction and two-file archive so the
srcDiff semantic oracle can first establish that both complete payloads were
exposed as candidates. The srcMove negative oracle then rejects only a reported
move that links the complete generated fragment-one text to the complete
fragment-two text. A result with no moves passes. A result containing only
smaller matching child fragments also passes with an incidental-move diagnostic:
BigCloneBench's pair label concerns the whole pair and does not assert that the
fragments contain no shared subtrees.

This is a whole-fragment rejection experiment, not general precision or a
population false-positive rate. Its manifests, summaries, and rates remain
separate from positive Type-1/Type-2 detection-and-classification results. The
`syntactic_type` on a false-positive row is retained only as dataset metadata;
it does not enable Type-3 move matching or create a positive expectation.

## Content-Label Conflict Exclusion

Conflict eligibility is keyed by the unordered SHA-256 pair of the two extracted
fragment contents. Under the default dedupe policy this is also the execution
frame identity and deliberately collapses repeated BigCloneBench rows that would
produce the same synthetic old/new payloads. Row-audit mode retains separate
execution frames but applies the same content-conflict exclusion.

That content-only identity is less specific than BigCloneBench's function-pair
identity. Distinct BigCloneBench function pairs can extract to the same two
fragment contents while one row is a positive clone and another is a known false
positive. This does not by itself prove that BigCloneBench assigned contradictory
labels to the same function pair: project, file, function, and functionality
context can differ even when the extracted payload bytes are equal. The synthetic
wrapper discards that context, however, so it cannot defensibly give the resulting
content-identical test both a positive and a negative oracle.

The selector therefore treats every unordered fragment-content identity carrying
both label kinds as audit-only. It excludes those identities before census
eligibility counting and deterministic sample ranking for every pair set and
dedupe mode. This preserves requested sample sizes when enough unambiguous frames
exist and prevents the same generated input from entering scored selections with
incompatible expectations.

Each selection preserves the complete evidence in `label-conflicts.jsonl`, writes
pair-set-specific exclusions to `exclusions.jsonl` with reason
`positive_negative_content_label_conflict`, and records excluded frame,
catalog-row, and source-row counts in its manifest. Run
`make bigmovebench-conflicts` to inspect the compiled catalog directly. The
report includes contributing BigCloneBench function IDs and separately counts
cases where the exact same function pair carries both labels.

## Important Caveats

### Full-census execution cost

The current runner is serial and commits one compact attempt per case to SQLite.
This avoids permanent four-file case directories and repeated whole-run JSON
rewrites. A multimillion-case Type-3 census still needs measured runtime and
storage work; profiling and bounded parallelism are future performance work, not
a second scientific workflow.

- BigCloneBench labels clones, not historical edits. The generated suite measures
  whether srcMove can recognize a synthetic move whose payload is drawn from a
  known clone pair.
- Selection keeps positive clone rows and known-false-positive rows in
  separate selections and reports. Negative cases measure rejection of the
  complete synthetic fragment pair; they are not part of the positive metric.
- BigCloneBench pair rows can heavily repeat the same fragment texts. Report both
  row counts and distinct raw-text-pair counts when using these cases as a metric.
- H2 embedded database access is single-process. Run BigCloneBench compilation
  or analysis commands serially; parallel queries can fail with a database lock.
- Interpret BigCloneBench source ranges as LF-delimited line numbers. Some
  IJaDataset files contain standalone carriage-return characters inside comments,
  and treating those as line breaks shifts later extracted fragments.
- Each synthetic archive retains distinct source and destination container
  classes at stable relative paths. The payload is removed from the source file
  and added to the destination file, so srcDiff cannot align the two payloads as
  unchanged content within one corresponding file.
- Many BigCloneBench fragments depend on imports or surrounding class members.
  srcDiff/srcML parsing generally does not require compilation, but malformed
  extracted fragments should be filtered out.
- Type-3 strict classification is observational rather than a required passing
  category. Type-4 is not a required positive and is not supported.
- Keep compilation and selection deterministic. Stable identities and ordering
  make failures reproducible and support comparisons across srcMove versions.
