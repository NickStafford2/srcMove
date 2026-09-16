# BigMoveBench

BigMoveBench is srcMove's benchmark derived from BigCloneBench. It converts
clone pairs into synthetic cross-file moves and uses known false-positive pairs
as negative cases. BigCloneBench supplies the source data; BigMoveBench defines
the conversion, selection, execution, and scoring methodology.

## Layout

- `installation.py` locates and validates the external BigCloneBench data and
  Java runtime.
- `compile.py` builds or reuses the catalog implemented by `catalog.py`.
- `selection.py` publishes deterministic pair-set samples or censuses.
- `synthetic.py` converts one selected fragment pair into a two-file move.
- `generated_objects.py` provides the stable, content-addressed wrapper store
  used by normalized benchmark cases.
- `benchmark_cases.py` publishes normalized case/object tables and provides the serial,
  reusable scratch-archive runner. The live suite does not use this path yet.
- `snapshot.py` converts a compiled selection into immutable source inputs.
- `contracts.py` defines source-pair, semantic-eligibility, and adapter types.
- `corpus.py` owns the input-snapshot, srcDiff-corpus, and srcMove-run stages.
- `execution.py` configures those generic stages for BigMoveBench and applies
  the benchmark evaluation.
- `paths.py` owns the default BigMoveBench cache location.
- `progress.py` provides terminal-aware progress reporting for these commands.
- `oracle.py` defines scoring; `evaluate.py` applies it to completed runs.
- `suite.py` is the benchmark entry point.
- `tests/` and `docs/` contain BigMoveBench-specific verification and
  documentation. Generic execution, provenance, identity, and serialization
  infrastructure remains in `benchmarking/`.

The cache remains under `bigMoveBench/cache/bigclonebench/` because it is a sealed
representation of the upstream dataset. BigMoveBench suite summaries are stored
under `benchmark-results/bigMoveBench/`.
The resulting pass rate is a strict synthetic detection-and-classification rate
for the selected cases: Type-1 must report `exact`, Type-2 must report `type2`,
Type-3 must report `type3`, and the position/text oracle must pass. Type-3
recall is observational: misses remain measurements rather than operational
suite failures. These rates are not general accuracy, recall, or precision.
Known-false-positive results use a separate whole-fragment rejection metric and
are never combined with the positive rates. See the
[conversion methodology](docs/methodology.md).

BigCloneBench is an external manual prerequisite. Both the full IJaDataset and
the smaller BigCloneEval reduced layout are supported; see the
[installation notes](docs/bigclonebench.md#local-installation).
Check the installed database, H2 driver, Java runtime, and nonempty corpus
without fetching or modifying anything:

```bash
make bigmovebench-preflight
```

## Compiled Dataset Cache

Phase 1 of the combined suite compiles the external H2 data and referenced Java
ranges into a srcMove-owned SQLite catalog plus a content-addressed fragment
store. From `srcMove/`, compile the complete external pair frame once:

```bash
make bigmovebench-compile
```

The immutable dataset is stored below
`bigMoveBench/cache/bigclonebench/compiled/<dataset-id>/`. A small lookup index lets
later invocations reuse it after checking the database and selected source-file
metadata. Reuse does not reopen H2, extract Java, or walk and hash every fragment.
If catalog compilation fails or is interrupted after H2 export, checked exports
remain below `bigMoveBench/cache/bigclonebench/work/`; the next identical compile
reuses them. Successful publication removes that temporary work cache. Progress
is reported separately for import, fragment extraction, pair identity, and index
construction, followed by publication validation.
Publication verification can validate the full fragment store explicitly:

```bash
python3 bigMoveBench/compile.py validate DATASET_ID \
  --verification full
```

For a developer smoke test of the compiler itself, limit each source table:

```bash
make bigmovebench-compile COMPILE_LIMIT=10
```

The limit is part of dataset identity, so a smoke catalog cannot be mistaken for
the complete frame.

Phase 2 selects directly from this SQLite catalog and never accesses H2. It
publishes each content-identified selection under
`bigMoveBench/cache/bigclonebench/selections/<selection-id>/`. Create the complete
deduplicated Type-1 frame with:

```bash
make bigmovebench-select \
  BIGCLONEBENCH_DATASET=<dataset-id> CLONE_TYPE=type1 MODE=census \
  SELECTION_ROLE=evaluation
```

Use `CLONE_TYPE=type2`, `CLONE_TYPE=type3`, or
`CLONE_TYPE=known-false-positive` for the other pair sets. Ordinary samples
select the lowest seeded SHA-256 ranks from the complete eligible frame. Type-3
samples instead divide frames by `min(line similarity, token similarity)` into
`>=.90`, `[.70,.90)`, `[.50,.70)`, and `<.50` bands, allocate equally across
all four required bands (redistributing unavailable quota), then rank within
each band. A frame with multiple catalog rows uses their minimum strength.
Type-3 sample sizes below four, or catalogs missing a band, are rejected. Sample
nonselections are aggregate manifest counts for Type-3 rather than one JSONL
record per frame. The seed, role, sample size, pair set, and dedupe policy are
part of selection identity. The default
`DEDUPE=exact-unordered-fragment-pair` retains one direction chosen by ascending
fragment SHA-256; `DEDUPE=none` is the row-based audit mode.

Every selection directory contains:

- `manifest.json`: request, source catalog identity, counts, and artifact hashes
- `frames.jsonl`: selected frames and all contributing row, function, and
  functionality metadata
- `exclusions.jsonl`: unavailable inputs and ordinary deterministic sample
  exclusions; Type-3 sample nonselections are aggregate-only
- `label-conflicts.jsonl`: the catalog's complete positive/negative conflict
  registry, including every contributing BigCloneBench function pair

No token, judgment, or confidence minimum is applied. The manifest reports
sub-50-token coverage explicitly. Reverse-direction rows remain attached to the
selected frame with their multiplicity and are marked as execution exclusions.
An extracted-content pair found under both positive and known-false-positive
labels is excluded before census counting or sample ranking. The manifest reports
the pair-set-specific excluded frame, catalog-row, and source-row counts, while
`exclusions.jsonl` records the reason
`positive_negative_content_label_conflict`. This is a conflict introduced at the
local content-only abstraction boundary, not necessarily two labels on the same
BigCloneBench function pair; see the
[methodology explanation](docs/methodology.md#content-label-conflict-exclusion).
Inspect the complete evidence from the compiled catalog with:

```bash
make bigmovebench-conflicts
```

Pass `BIGCLONEBENCH_DATASET=<dataset-id>` if the local compiled index contains
more than one dataset. The report shows the contributing labels, syntactic types,
and function IDs and confirms how many conflicts reuse the same BigCloneBench
function pair.
Reusing a selection validates all artifact checksums. Phase 3 materializes a
Type-1, Type-2, Type-3, or known-false-positive selection directly from the
compiled fragment store:

```bash
make bigmovebench-snapshot \
  BIGCLONEBENCH_SELECTION_ID=<selection-id>
```

The command validates the selection and compiled catalog without opening H2,
verifies each selected fragment object, and writes generated old/new Java files
straight into the shared content-addressed input snapshot. Synthetic class names
derive from fragment-content identity, and all contributing rows remain in each
case's snapshot metadata. Materialization does not create a separate mutable
case tree.

The normalized census path can instead publish immutable benchmark-case tables
whose rows reference shared generated objects:

```bash
make bigmovebench-benchmark-cases \
  BIGCLONEBENCH_SELECTION_ID=<selection-id>
```

Benchmark cases are stored under
`bigMoveBench/cache/benchmark-cases/<benchmark-cases-id>/benchmark_cases.sqlite`;
shared wrappers are stored once under `bigMoveBench/cache/generated-objects/`.
The serial benchmark-case runner links each case's four objects into one
temporary archive and reuses that archive for the next case. This is an
experimental comparison path: `suite.py` continues to use immutable snapshots
until the journal and equivalence gate are complete. See the
[normalized census architecture](docs/plans/normalized_census.md).

## Combined Suite

Run every currently supported pair set without copying any dataset, selection,
snapshot, or corpus identifier:

```bash
make bigmovebench-suite PROFILE=small
make bigmovebench-suite PROFILE=medium
```

The command compiles or reuses the dataset, publishes or reuses a deterministic
selection for Type 1, Type 2, Type 3, and known false positives, reuses immutable
snapshots and srcDiff corpora when their inputs and tool identity are unchanged,
then creates a separate srcMove evaluation for each pair set. Results are never
blended into one accuracy percentage. Combined run metadata is saved below
`benchmark-results/bigMoveBench/suite-runs/` and links to each append-only
evaluation run.

Every compiled case is an isolated two-file archive. Both revisions retain
`source/input.java` and `destination/input.java`; the payload is removed from a
stable source class and added to a distinct stable destination class. This
forces srcDiff to expose the cross-file delete and insert without making either
container or whole file appear moved.

Run Type-3 alone with `make bigmovebench-suite PAIR_SET=type3`. The live
`srcMove execution` counter reports completed cases, while its suffix
reports results by strength band. A suite containing observational Type-3
results reports `COMPLETE` when execution is operationally sound; individual
pair sets use `PASS`, `FAIL`, or `OBS`. A sampled Type-3 run is labeled as a
balanced strength sample and shows
strict-classification and whole-fragment-detection counts for all four bands.
Its unweighted overall rate is not population recall. Whole-fragment detection,
wrong classification, misses, errors, false acceptances, and incidental moves
are secondary diagnostics. Exit status 0 means every strict pair set passed and
each observational Type-3 case completed without upstream, tool, semantic, or
oracle errors. Type-3 misses and wrong classifications do not change the exit
status.

Use `PROFILE=small|medium` for the checked-in reproducible profiles and
`PROFILE=full` for the complete deduplicated census. Use
`ROLE=tuning|evaluation`, `PAIR_SET=<pair-set>`, and `VERIFY_SOURCE=1` as
needed. Normal development runs trust artifacts when they
were sealed: they validate manifest identities and hash `srcdiff` and `srcMove`
once, but do not revisit the original dataset or rehash selection JSONL,
snapshot sources, or corpus XML. `VERIFY_SOURCE=1` is the explicit upstream
audit; it rehashes the original H2 database, H2 driver, and selected Java
sources before accepting a compiled cache. The compile, select, and snapshot
commands remain available as debugging interfaces, and direct snapshot/corpus
loads retain full checksum verification.

Each suite run keeps immutable generated-source snapshots, reusable srcDiff
corpora, and append-only srcMove evaluations separate. Input snapshots and
corpora use content-derived identifiers; evaluation runs use unique identifiers.
Each process invocation records bounded logs, terminal status, timeout cleanup,
and XML validation.

The scoring rules live in `oracle.py`; BigMoveBench orchestration lives in
`execution.py`, while generic execution and artifact management remain in the
shared `benchmarking/` infrastructure. This separation keeps the oracle
independent of process orchestration.

## Thesis Data Runs

For thesis or paper data, freeze the declared evaluation selection separately
from tuning cases with `ROLE=evaluation`. Type-3 is currently
tuning/observational only: evaluation selection is rejected until a held-out
partition is implemented. Publication enforcement
and archive verification belong to Phase 6; Phase 4 development runs already
retain their manifests and summaries by run identifier. BigMoveBench data is
not reused for runtime experiments. Use independent, large, pre-existing
srcDiff XML workloads with the
[performance benchmark](../performance/README.md) when comparing srcMove
builds.

## Validation

- Type-1 expects the complete intended move to be `exact`.
- Type-2 expects the complete intended move to be `type2`.
- Type-3 expects the complete intended move to be `type3`; its recall is observational.
- A known-false-positive case expects no single reported move to link the full
  generated source and target fragments. Zero moves passes. Smaller incidental
  child moves also pass and are reported separately; requiring zero moves would
  incorrectly treat every shared child subtree as a whole-pair false positive.
- One reported move must link both complete generated texts, and the XML
  delete/insert annotations carrying that move's ID and link attributes must
  overlap the synthetic ranges stored in `metadata.json`. Positions belonging
  to another move cannot satisfy the oracle; unrelated extra moves are allowed.
- The reported delete and insert raw texts must match their own expected
  generated fragment texts after wrapper indentation normalization. Type-2 does
  not require the delete text to equal the insert text.
- Text validation is strict unless the only successful comparison requires
  collapsing obvious replacement-character encoding damage. The summary records
  `strict`, `encoding_tolerant`, `failed`, or `not_checked` for each move side.

`encoding_tolerant` means the exact raw-text comparison failed, but the observed
and expected texts matched after the runner repaired only obvious
replacement-character encoding damage. The tolerance is intentionally narrow: it
is considered only when either side contains the Unicode replacement character
`�` or the common mojibake spelling `ï¿½`; the runner then tries a Latin-1 to
UTF-8 repair and normalizes `ï¿½` back to `�`. It does not ignore ordinary text,
comment, whitespace, or identifier differences.

The summary's `failure_class` column groups common outcomes:

- `pass_strict`: the case passed strict validation.
- `pass_encoding_tolerant`: the case passed only after the encoding-damage
  tolerance.
- `no_move_raw_different`: srcMove reported no move and the BigCloneBench
  fragments are not raw-text-identical. These usually need manual review because
  comments, formatting, or a bad extracted range may explain the mismatch.
- `no_move_raw_identical`: srcMove reported no move even though the extracted
  fragments are raw-text-identical.
- `too_many_expected_child_moves`: srcMove found moves inside the expected
  BigCloneBench fragment instead of one move for the whole fragment.
- `anchor_only_false_positive`: legacy bucket for runs generated with method
  anchors where srcMove reported only synthetic wrapper anchor moves, not the
  BigCloneBench fragment.
- `mixed_anchor_and_payload_moves`: legacy bucket for runs generated with method
  anchors where srcMove reported at least one wrapper anchor move alongside
  other moves.
- `text_mismatch`, `tool_failure`, `invalid_results`, `validation_failure`, and
  `unknown_failure`: fallback buckets for runner/tool failures or results that
  do not match a more specific BigCloneBench pattern.

The runner invokes `srcdiff` with `--position` so `srcmove.xml` contains
`pos:start` / `pos:end` attributes. This makes the oracle independent of raw
string formatting differences introduced by the synthetic wrapper.

Type-2 is a strict test mode. If current srcMove does not detect a generated
BigCloneBench Type-2 pair, the command exits nonzero and reports the missed move.

Type-3 and Type-4 moves are not supported. The syntactic type stored on a known
false-positive row is descriptive metadata, not a positive move expectation.
