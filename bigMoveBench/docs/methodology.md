# Converting BigCloneBench Pairs Into srcMove Tests

BigCloneBench is not a move-detection benchmark. Its positive oracle is a set of
clone pairs: two independently existing Java function fragments that implement
the same functionality. BigCloneEval distributes the database and source layout
used here. The current srcMove evaluation synthesizes a before/after edit where
one clone fragment is deleted from the old version and its paired clone fragment
is inserted at a different location in the new version.

The resulting strict outcome rate measures whole-fragment synthetic detection
and classification for the declared slice and oracle. Type-1 and Type-2 are
required pass/fail categories; Type-3 is observational. None of these rates is
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
8. Run `srcMove` over eligible srcDiff XML with `--results-only`.
9. Score whether any single reported move links both complete generated fragment
   texts and its reported source/destination XPaths resolve to srcDiff nodes that
   overlap the expected line ranges. Other reported moves are incidental
   evidence, not a rejection.

Each generated revision contains the same two relative paths,
`source/input.java` and `destination/input.java`. srcDiff therefore compares the
stable source file across revisions and exposes the removed payload there, then
compares the stable destination file and exposes the inserted payload there.
The two distinct container classes prevent the wrappers themselves from looking
like a cross-file move.

The original-label evaluation uses a strict detection-and-classification oracle:
Type-1 cases must classify the intended whole-fragment move as `type1`, Type-2c
as `type2c`, Type-2b as `type2b`, and
Type-3 as `type3`. Position and per-side text validation are
correlated to the same JSON result; the result's XPaths supply its position
evidence from the admitted srcDiff XML.
Detecting the intended payload with the incorrect content classification is useful failure
evidence, but it is not counted as a pass. Type-3 recall is observational. The
benchmark deliberately uses BigCloneBench as the best available large labeled
source; questionable labels,
unsupported variations, extraction problems, or conversion artifacts discovered
in the failure set should be analyzed and reported rather than silently removed.

Keep a reviewed content classification separate from the inherited label. For
example, a supplied Type-2 pair may also add or remove an empty statement, which
exceeds srcMove's Type-2 identifier/literal substitutions. Detecting the whole
fragment as Type-3 remains a strict label disagreement even when review accepts
that interpretation. Record the case identity, original label, reviewed label,
reason, and source evidence; do not silently drop the case or rewrite the source
catalog. Any review-adjusted summary must declare its cases and denominator
alongside the original-label result. A srcMove similarity value does not assign
a BigCloneBench Type-3 strength band.

Reviewed expectations determine the suite's pass/fail result for required
Type-1 and Type-2 strata. The reviewed result equals the original-label result
unless an explicit content-pair correction applies. A correction changes only
the expected content type: the same whole-fragment, source-position, output
schema, and execution checks remain required. A missing move still fails, and
reporting the inherited type instead of the reviewed type also fails the
reviewed expectation.

The checked-in [current correction registry](../content_relationship_corrections.json) records
each review. Each correction identifies the two exact fragment hashes, original and reviewed
types, source function IDs, and the reason for review. The unordered hash pair
supports either comparison direction; a modified fragment does not inherit the
correction. Function IDs provide provenance rather than overriding content
identity. The source catalog and generated case definitions remain unchanged.
The registry snapshot and its digest are recorded with run provenance so a run
cannot resume under changed review decisions.

A corrected case remains in its original sample and denominator. For example,
one reviewed Type-3 case in a 100-case Type-2-labeled sample can yield original
label agreement of 99/100 and reviewed success of 100/100. It is not transferred
into the separate Type-3 sample or assigned a BigCloneBench strength band.
Per-case reports retain the original outcome, reviewed outcome, and correction
identity; summary reports show both scores and the number of corrections.
The existing `outcome`, `counts`, and `rates` fields retain original-label
meaning. `reviewed_outcome`, `reviewed_counts`, and `reviewed_rates` record the
reviewed interpretation. A displayed reviewed pass therefore does not change
the original-label failure stored for a corrected case.

The initial correction, `bcb-69322-96077-empty-statement`, covers functions
69322 and 96077. The supplied label is Type-2, but the fragments also differ by
a standalone empty statement after a `while` block. The reviewed expectation is
Type-3. Registry hashes refer to the exact extracted source fragments, before
the synthetic wrapper adds indentation or surrounding code.

This converts clone similarity into move similarity. Type-1 and Type-2 clone
labels supply the expected match categories, subject to the reviewed-definition
limits above. Type-3
matching is also implemented, but srcMove accepts only high-similarity candidates:
either the normalized statement/block sequence or normalized token sequence must
satisfy its symmetric `0.90` bounded-LCS rule. BigMoveBench evaluates Type-3 as
an observational recall stratum, so below-threshold pairs remain informative
misses rather than suite failures. Type-4 is not supported.

## Exclusive derived categories and output contract

`categories.py` is the canonical rule implementation. Category rules version 1
matches the local BigCloneEval “Tool Evaluation Report” in
`data/BigCloneEval/ReadMe.md` (lines 380–396),
`ToolEvaluator.java`'s `getNumClones_type2c_inter` and
`getNumClones_type2b_inter` (including their intra-project/detected counterparts),
and `EvaluateTools.java`'s `getCondition`:

| Derived benchmark category | Original database membership |
| --- | --- |
| `type1` | `syntactic_type = 1` |
| `type2c` (consistent) | `syntactic_type = 2`, regardless of similarity |
| `type2b` (blind-only) | `syntactic_type = 3` and both similarity fields equal 1.0 |
| `type3` | Remaining `syntactic_type = 3` rows; retain the existing strength bands |

Upstream implements blind-only membership with `least(similarity_line,
similarity_token) >= 1.0`; BigMoveBench uses the same comparison on database
scores stored in [0,1], without rounding or tolerance. The general blind-renaming
criterion also accepts consistent pairs; **`type2b` here denotes only the
exclusive blind-only reporting subset**. BigCloneEval's aggregate “Type-2” is
Type-2b plus Type-2c. It is not a detector output alias and is not an exclusive
BigMoveBench pair-set name. New selection accepts `type2b` and `type2c`; it
rejects ambiguous `type2` requests.

Source `syntactic_type`, `pair_type`, similarity values, contributing row IDs,
function IDs, fragment hashes and multiplicities are preserved unchanged.
Selection rows add `benchmark_category` and `category_rules_version`; the
selection request includes that version in its content identity. Generated
cases store the derived category in `expected_content_relationship`, expose it as
`benchmark_category` and `clone_type`, and retain raw `syntactic_type` separately.
Only derived Type-3 receives a Type-3 strength band. Deduplication, conflict
exclusion, source availability and srcDiff admission rules remain unchanged.

Results schema 2 uses `moves[].content_relationship` and `content_relationships`
for predicted content classifications and their group counts. Current consumers
reject schema 1, superseded fields, legacy `type2`, and `type2b` as a selected
report label. Counts must agree with the reported groups. Reference expectations
may still be Type-2b; this does not manufacture a detector prediction.
No Type-2b detection capability is presumed:
a complete Type-2b pair reported as Type-3 is detected but incorrectly
classified, whereas smaller child moves are detection misses. The detector's
rename to `type2c` requires no matching-behavior change in this benchmark.

Reviewed corrections are still matched by exact unordered fragment hashes.
Historical correction `original_content_relationship: type2` means consistent `type2c`;
its reviewed Type-3 expectation is preserved. A correction matching content
but conflicting with a new inherited category produces an explicit oracle
failure requiring review, rather than being discarded or silently applied.
The corrected case remains in its inherited category's denominator. Original
and reviewed outcomes and correction identity/digest remain separate. A reviewed
Type-3 correction does not assign an external Type-3 band to a Type-2c case.

### Report schema and denominators

Scoring oracle version 8 writes complete detection evidence independently of
classification. Run `summary.json` schema version 3 retains `category_rules_version`,
`category_membership` (`derived` or `legacy_syntactic_type`) and
`category_reports[category]`; suite summaries copy these reports and console
output prints their counts. Existing `counts`, `rates`, `reviewed_counts` and
`reviewed_rates` retain their original strict outcome meanings.

Each category report exposes:

- `denominators.selected`: all generated execution cases in the category,
  including operational failures and pending cases, not contributing row count.
- `denominators.completed`: cases with a latest terminal attempt.
- `denominators.srcdiff_eligible`: terminal cases admitted by the unchanged
  srcDiff semantic gate, including subsequent tool/schema failures.
- `denominators.complete_detections`: cases with one single move satisfying
  both complete texts and the existing per-side positional overlap oracle.
- `complete_detections`, `original_category_agreements`, and
  `reviewed_category_agreements`: separate numerators. Complete detections
  include both `oracle_pass` and `wrong_classification`.
- `rates.complete_detection_over_selected` and
  `rates.complete_detection_over_eligible`; original and reviewed agreement
  rates over selected cases and over complete detections.
- `reported_categories_among_complete_detections`: normalized reported-category
  counts and proportions, with complete detections as denominator. One move per
  case is chosen by the existing oracle: prefer an agreeing complete move,
  otherwise the first complete move. Incidental and partial moves do not enter
  this distribution. `unavailable` marks missing historical diagnostic evidence.

Zero denominators yield JSON `null`, and empty distributions remain empty.
Running summaries have pending cases in the selected denominator; use completed
summaries for final rates. CSV adds `benchmark_category`,
`category_rules_version`, `complete_fragment_detected` and
`normalized_observed_category`, while preserving raw `observed_content_relationship`,
`syntactic_type`, reviewed outcome, and correction fields.

### Existing artifacts: regeneration, not implicit migration

Existing compiled catalogs and generated Java object bytes remain reusable;
they preserve the raw evidence needed for category derivation. Existing
selection manifests, case databases, frozen profile rows, journals and results
remain legacy evidence under their recorded rules. Current consumers require
new benchmark-case collections (schema/user version 2), execution journals
(schema/user version 2), and results (schema 2). Do not relabel retained output
or resume old run directories. Scoring oracle 9 requires a new run ID/directory.
Versionless raw source metadata is not inferred to be Type-2b from a high score;
category derivation and case publication remain separate from output admission.
See [the reporting contract](../../doc/architecture.md#results-terminology) for
the historical/current correction registries and full regeneration requirements.

For a new evaluation, reuse the verified compiled dataset ID, create new
selections with selector version 4, then publish new benchmark-case databases
and execute into new result directories. A bounded Type-2b sample, from the
workspace root, is:

```bash
./bin/srcml-dev-shell python3 srcMove/bigMoveBench/selection.py <dataset-id> --pair-set type2b --mode sample --sample-size 20 --seed 0
./bin/srcml-dev-shell python3 srcMove/bigMoveBench/benchmark_cases.py <new-selection-id>
./bin/srcml-dev-shell python3 srcMove/bigMoveBench/normalized_execution.py <new-benchmark-cases-id> --results-root /workspace/srcMove/benchmark-results
```

Use `type2c` separately with the same declared sampling parameters. Follow the
case publisher's CLI help for an explicit cache root. Execution without
`--resume-run` creates a **new** run directory. Recreate Type-3 selections too, since Type-2b rows
are now excluded from those bands. No database recompile is needed.

The checked-in `frozen_profiles.jsonl` remains an unchanged legacy profile.
New Type-2b/Type-2c/Type-3 preset requests reject it with regeneration guidance;
the suite preflights this before starting tools or writing results. To prepare
new frozen profiles explicitly, retain the old profile and its digest and use
new paths for both companion and profile. The commands below are opt-in and
construction can read the entire catalog; no full-dataset construction or
evaluation was run for this change.

```bash
./bin/srcml-dev-shell python3 srcMove/bigMoveBench/selection_index.py <dataset-id> --output /workspace/srcMove/bigMoveBench/cache/selection-index-categories-v1.sqlite
./bin/srcml-dev-shell python3 srcMove/bigMoveBench/generate_frozen_profiles.py <dataset-id> --selection-index /workspace/srcMove/bigMoveBench/cache/selection-index-categories-v1.sqlite --output /workspace/srcMove/bigMoveBench/cache/frozen-profiles-indexed-v1-seed0.jsonl --seed 0
./bin/srcml-dev-shell python3 srcMove/bigMoveBench/suite.py --profile small --frozen-profiles /workspace/srcMove/bigMoveBench/cache/frozen-profiles-indexed-v1-seed0.jsonl
```

Generation without `--selection-index` retains full-frame SHA-256 ranking and
verified `--selection PAIR_SET=PATH` reuse. Type-3 now uses that full-frame
selection path too; the earlier capped candidate query is retired. Supplied
selections must carry category rules version 1. The unvalidated
`--sampling bounded`, time/probe limits, and bounded exploratory reporting have
been retired. Neither generation nor sampling implicitly builds a companion.

### Indexed selection companion version 1

`selection_index.py` writes a new SQLite artifact, opened read-only for reuse.
It binds dataset ID, compiled manifest digest, catalog digest, category rules,
eligibility, dedupe policy and position order. Unsupported versions and identity
mismatches fail explicitly. It adds nothing to the compiled catalog and does
not reclassify old selections, profiles, case databases, corrections or results.
Choose a new filename to rebuild; outputs are published exclusively through a
same-directory temporary file and existing files cannot be replaced. Interrupted
construction leaves no usable partial companion. Allow free space for the new
companion, SQLite transaction journal, and temporary publication file (the latter
is hard-linked rather than copied).

Construction first counts available rows, then streams available rows in
unordered content-identity order through `pair_unordered_idx`. Within each
identity it excludes positive/negative content conflicts before grouping by
derived category. `exclusions` retains the complete conflict row evidence;
`contributors` retains every eligible catalog pair ID. Multiplicities remain
source-row counts rather than additional sampling tickets. Frames can appear in
more than one positive category when distinct source assertions so indicate,
matching the existing selector. Type-3 uses the minimum of both similarities
across its contributing category rows and the existing four bands.

Each category/band receives dense zero-based positions ordered by frame ID.
`frames` has primary key `(category, band, position)`; `counts` stores frame,
catalog-row and source-row totals, including zero counts for empty categories or
bands. Empty/insufficient populations fail explicitly, without probing or a
fallback algorithm. The profile generator requires 100 frames for each
non-Type-3 category and 25 for each Type-3 band. The companion supports only
available-source, unordered-content dedupe with the documented default
eligibility; row-audit and custom filter selections still use `selection.py`.

Sampling uses independently seeded Python `random.sample(range(count), quota)`
per category/band and direct primary-key position lookups. It then hydrates only
selected identities through the catalog's `pair_unordered_idx`, retaining the
existing direction policy, contributor metadata and reverse-row exclusions.
The seed and algorithm version describe a new sample, not equivalence to the old
SHA-256-ranked samples. The frozen profile records companion SHA-256, identity,
and full population counts; those fields propagate into the frozen selection's
request and identity. Retain the companion and profile with research provenance.
The profile's small subset preserves the existing SHA-256 ordering of its
selected medium frames (five per Type-3 band); it is a nested subset, not a new
independent population sample. Frozen-selection count fields describe selected
profile frames; population totals live in `request.sample.indexed_selection`.

`ProgressDisplay` reports construction phases and elapsed time, processed
available rows and percentage during materialization, an animated TTY heartbeat
through SQL/commit work, and periodic durable status when redirected (default
30 seconds). Construction reports per-phase elapsed seconds, available rows,
eligible frames, exclusions, catalog bytes and companion bytes. Memory during
grouping depends on the largest repeated content identity, not just sample size.
Full-catalog construction runtime, peak memory and disk overhead remain
unmeasured; fixture observations do not establish production performance.

Focused fixture validation, from the workspace root:

```bash
./bin/srcml-dev-shell bash -lc 'cd srcMove && python3 -m unittest bigMoveBench.tests.test_selection_index bigMoveBench.tests.test_categories bigMoveBench.tests.test_selection bigMoveBench.tests.test_progress -v'
./bin/srcml-dev-shell bash -lc 'cd srcMove && python3 -m unittest discover -s tests/tooling/bigmovebench -v'
```

The tests print `EXPLAIN QUERY PLAN` evidence: position sampling uses
`SEARCH frames USING PRIMARY KEY (category=? AND band=? AND position=?)`;
selected catalog hydration uses `SEARCH p USING INDEX pair_unordered_idx
(unordered_pair_id=?)` and indexed function/materialization joins. Neither
retrieval plan scans the catalog. Construction deliberately scans it, and profile
provenance hashes the companion once per generation.

Docker fixture measurements on 2026-10-05 (single runs, not a scaling claim):

| Available catalog rows | Eligible frames | Catalog bytes | Companion bytes | Construction seconds |
| --- | --- | --- | --- | --- |
| 34 | 32 | 167,936 | 32,768 | 0.041 |
| 802 | 800 | 2,068,480 | 331,776 | 0.139 |

Both fixtures exclude one content-conflict identity. Construction seconds cover
setup, counting, materialization and initial finalization through the report
snapshot; publication and profile generation are separate. The tests also check
reference-inventory agreement, deterministic samples, dense positions, duplicate
multiplicity, conservative strength, reverse contributors, identity rejection,
shortages, unchanged catalog bytes and exclusive profile publication.

No in-place artifact migration is implemented. Any future audit migration must
write a new artifact, name the old identity and digest, declare changed
membership/denominators, preserve review evidence, and rescore retained outputs
under a new oracle identity; it must not relabel old summary counts in place.

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

srcMove runs with `--results-only`. The scoring oracle uses the reported move
XPaths to resolve source and destination nodes in the admitted srcDiff XML,
then applies the same line-range overlap checks formerly read from annotated
srcMove XML. The JSON move identities, classifications, and texts remain the
other half of the dual oracle.

The per-run summary reports both the end-to-end strict outcome rate over
generated cases and the conditional srcMove detection-and-classification rate
over srcDiff-eligible cases. Type-3 reports use those same strict outcome rules
but remain observational. The eligibility and scoring oracle versions are
recorded in the benchmark-case and execution artifacts.

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
syntactic_type = 2             consistent / Type-2c move baseline
syntactic_type = 3, line = token = 1.0   blind-only / Type-2b
syntactic_type = 3, .90 <= min(line,token) < 1.0   Type-3 reference
syntactic_type = 3, sim < .70  weak external Type-3 stress cases
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

The compiled external dataset identified by the checked-in
[`frozen_profiles.jsonl`](../frozen_profiles.jsonl) manifest contains 8,648,734
available labeled pair rows under the **legacy raw syntactic-type grouping**:
47,146 type-1 rows, 4,223 type-2 rows, 8,323,944 type-3 rows, and 273,421 known-false-positive rows. These collapse to 6,011,979
unique unordered fragment-content pairs across label kinds. These historical
counts do not describe the new exclusive derived categories; Type-2b was
contained in the raw type-3 grouping. Raw syntactic type 1 collapses to
951 unique content pairs, raw syntactic type 2 to 567, and known false positives to about
232,509; Type 3 accounts for the remaining multimillion-case scale. Counts are
dataset-specific and must be read from the compiled manifest and selection
manifests for every reported run rather than treated as timeless constants.

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
only pairs whose two functions are external. Token size is retained as reporting
metadata but does not determine eligibility. The ordered table direction is
preserved as fragment one deleted and fragment two inserted.

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
