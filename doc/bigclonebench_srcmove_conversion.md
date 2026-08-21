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
`benchmarks/bigclonebench/data/BigCloneEval/` and follow its setup instructions
in `benchmarks/bigclonebench/data/BigCloneEval/ReadMe.md` or the upstream README
at <https://github.com/jeffsvajlenko/BigCloneEval>. This checkout expects the
two required inputs at:

```text
benchmarks/bigclonebench/data/BigCloneEval/bigclonebenchdb/bcb.h2.db
benchmarks/bigclonebench/data/BigCloneEval/ijadataset/{default,sample,selected}/*.java
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
4. Build a synthetic old file containing fragment one inside a stable wrapper
   class.
5. Build a synthetic new file containing the paired fragment after that class,
   at top-level srcML scope.
6. Run `srcDiff original.java modified.java --position`.
7. Verify that srcDiff exposed the intended synthetic payload as usable
   delete/insert regions.
8. Run `srcMove` over eligible srcDiff XML.
9. Score whether srcMove reports one delete/insert move whose annotated positions
   overlap the generated line ranges for the two benchmark fragments.

The current evaluation uses a strict detection-and-classification oracle:
Type-1 cases must report the intended whole-fragment move as `exact`, and Type-2
cases must report it as `type2`. Position and per-side text validation must also
pass. Detecting the intended payload with the wrong match kind is useful failure
evidence, but it is not counted as a pass. The benchmark deliberately uses
BigCloneBench as the best available large labeled source; questionable labels,
unsupported variations, extraction problems, or conversion artifacts discovered
in the failure set should be analyzed and reported rather than silently removed.

This converts clone similarity into move similarity. Exact and Type-2 clone pairs
are the best first target for srcMove because they align with the current exact and
Type-2 match categories. Type-3 and Type-4 pairs are useful later as expected misses
or as recall targets for future similarity scoring.

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
in the corpus and run artifacts.

## Future Negative Cases From Known False Positives

BigCloneBench also provides known false-positive clone pairs. They are an
optional future source of negative cases: similar-looking regions that srcMove
must not annotate as moves. Their absence does not make the current positive-case
detection-and-classification evaluation incomplete for its declared purpose.

This work is intentionally deferred until the positive-case pipeline is
reproducible. A BigCloneBench clone-detector false positive is not automatically
a valid srcMove negative case. The future extension must define:

- how each pair is converted into a before/after source edit without introducing
  an accidental real move through the synthetic wrapper
- why the expected srcMove result is no move
- how to verify that srcDiff exposed comparable candidate regions
- which judgment, confidence, size, and deduplication filters define eligibility
- whether the metric describes the selected negative slice or supports a broader
  false-positive-rate or precision claim

Keep those negative results separate from the current positive-case detection
rate. Once the conversion and oracle are defensible, useful failures can be
minimized into small checked-in regression tests while the generated suite
continues to provide breadth.

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
  AND c.min_tokens >= 50
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
sampling seed and strata when applicable, and generator/oracle versions. Report
functionality coverage and distinct raw-text-pair coverage so repeated clone rows
cannot masquerade as independent variety.

BigCloneBench treats clone pairs as unordered, but the synthetic edit has a
direction. The evaluation must declare whether `(A, B)` means only deleting A and
inserting B, whether both directions are evaluated, or whether a canonical
direction is chosen. Keep cases used to tune srcMove identifiable and freeze a
separate evaluation census or sample for the final thesis result.

## Practical Test Layout

Generate into a separate directory so the large suite is not mixed with small
hand-authored e2e fixtures:

```text
benchmarks/bigclonebench/
  cases/
    bcb_t2_000001/
      original.java
      modified.java
      metadata.json
```

`metadata.json` should record BigCloneBench IDs, source file locations, original
BigCloneBench line ranges, generated synthetic line ranges, similarity fields,
stable dedupe keys, and the exact deleted/inserted fragment text. The large-suite
runner should validate by generated line ranges and counts instead of requiring
stable srcMove UUIDs or absolute xpaths.

The generator defaults to `--dedupe raw-text-pair`, so a run selects distinct
extracted fragment pairs before writing cases. Raw text is intentional for
Type-1: BigCloneEval describes Type-1 similarity as allowing strict
pretty-printing plus whitespace/comment/formatting variation, and srcMove should
still be tested against those differences. `--dedupe none` is available for
row-based BigCloneBench coverage, and `--dedupe trimmed-text-pair` is available
only for auditing near-identical extracted text.

Do not assume the current filtered BigCloneBench Type-1 slice contains thousands
of formatting-only variants. With `syntactic_type = 1`, `min_tokens >= 50`, and
`internal = FALSE`, the local database has many duplicate rows and most distinct
raw text pairs still contain identical extracted fragment text on both sides. Use
`--text-change raw-different` when reviewing the small subset whose extracted
fragments differ, and keep hand-authored whitespace/comment fixtures for
targeted Type-1 whitespace behavior.

Each generator run writes a per-type manifest listing the selected case
directories. The runner consumes that manifest instead of scanning all old
ignored case directories, so a deduped run cannot be polluted by stale generated
cases from a previous larger run.

## Known False-Positive Conversion

Known false positives are selected from `false_positives` and joined to
`functions` for source locations, token counts, and the external/internal flag.
The table has no `min_tokens` or `internal` columns of its own. Selection keeps
only pairs whose two functions meet the token threshold and are external, then
applies the configured minimum judge and confidence thresholds. The ordered
table direction is preserved as fragment one deleted and fragment two inserted.

Generation reuses the positive cases' extraction and asymmetric wrapper so the
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

## Important Caveats

- BigCloneBench labels clones, not historical edits. The generated suite measures
  whether srcMove can recognize a synthetic move whose payload is drawn from a
  known clone pair.
- The generator keeps positive clone rows and known-false-positive rows in
  separate selections and reports. Negative cases measure rejection of the
  complete synthetic fragment pair; they are not part of the positive metric.
- BigCloneBench pair rows can heavily repeat the same fragment texts. Report both
  row counts and distinct raw-text-pair counts when using these cases as a metric.
- H2 embedded database access is single-process. Run BigCloneBench generator or
  analysis commands serially; parallel queries can fail with a database lock.
- Interpret BigCloneBench source ranges as LF-delimited line numbers. Some
  IJaDataset files contain standalone carriage-return characters inside comments,
  and treating those as line breaks shifts later extracted fragments.
- The synthetic old/new payloads intentionally sit under different parent
  shapes. If both sides use comparable wrapper blocks, srcDiff can align those
  wrappers and treat the payload as common code instead of exposing it as
  delete/insert content for srcMove.
- Many BigCloneBench fragments depend on imports or surrounding class members.
  srcDiff/srcML parsing generally does not require compilation, but malformed
  extracted fragments should be filtered out.
- Type-3 and Type-4 pairs should not be marked as required positives unless
  srcMove grows a similarity matcher designed for them.
- Keep the generator deterministic. A stable SQL `ORDER BY` makes failures
  reproducible and lets you compare recall across srcMove versions.
