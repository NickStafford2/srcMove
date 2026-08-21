# BigCloneBench Benchmark

This suite generates synthetic positive move cases from BigCloneBench clone
pairs and negative cases from its known false-positive pairs. It supports both
quick smoke runs and large batches.
The resulting pass rate is a strict synthetic detection-and-classification rate
for the selected cases: Type-1 must report `exact`, Type-2 must report `type2`,
and the position/text oracle must pass. It is not general accuracy, recall, or
precision. The generated case directories live under
`benchmarks/bigclonebench/cases/` and are ignored by git.

Known-false-positive results use a separate whole-fragment rejection metric and
are never combined with the Type-1/Type-2 positive rate. See the
[conversion methodology](../../doc/bigclonebench_srcmove_conversion.md).

BigCloneBench is an external manual prerequisite. Both the full IJaDataset and
the smaller BigCloneEval reduced layout are supported; see the
[installation notes](../../doc/bigclonebench_notes.md#local-installation).
Check the installed database, H2 driver, Java runtime, and nonempty corpus
without fetching or modifying anything:

```bash
make bigclonebench-preflight
```

## Compiled Dataset Cache

Phase 1 of the combined suite compiles the external H2 data and referenced Java
ranges into a srcMove-owned SQLite catalog plus a content-addressed fragment
store. From `srcMove/`, compile the complete external pair frame once:

```bash
make bigclonebench-compile
```

The immutable dataset is stored below
`benchmark-data/bigclonebench/compiled/<dataset-id>/`. A small lookup index lets
later invocations reuse it after checking the database and selected source-file
metadata. Reuse does not reopen H2, extract Java, or walk and hash every fragment.
If catalog compilation fails or is interrupted after H2 export, checked exports
remain below `benchmark-data/bigclonebench/work/`; the next identical compile
reuses them. Successful publication removes that temporary work cache. Progress
is reported separately for import, fragment extraction, pair identity, and index
construction, followed by publication validation.
Publication verification can validate the full fragment store explicitly:

```bash
python3 benchmarks/bigclonebench/compile.py validate DATASET_ID \
  --verification full
```

For a developer smoke test of the compiler itself, limit each source table:

```bash
make bigclonebench-compile COMPILE_LIMIT=10
```

The limit is part of dataset identity, so a smoke catalog cannot be mistaken for
the complete frame.

Phase 2 selects directly from this SQLite catalog and never accesses H2. It
publishes each content-identified selection under
`benchmark-data/bigclonebench/selections/<selection-id>/`. Create the complete
deduplicated Type-1 frame with:

```bash
make bigclonebench-select \
  BIGCLONEBENCH_DATASET=<dataset-id> CLONE_TYPE=type1 MODE=census \
  SELECTION_ROLE=evaluation
```

Use `CLONE_TYPE=type2` or `CLONE_TYPE=known-false-positive` for the other pair
sets. `MODE=sample SAMPLE_SIZE=100 SEED=0` selects the lowest seeded SHA-256
ranks from the complete eligible frame. The seed, role, sample size, pair set,
and dedupe policy are part of selection identity. The default
`DEDUPE=exact-unordered-fragment-pair` retains one direction chosen by ascending
fragment SHA-256; `DEDUPE=none` is the row-based audit mode.

Every selection directory contains:

- `manifest.json`: request, source catalog identity, counts, and artifact hashes
- `frames.jsonl`: selected frames and all contributing row, function, and
  functionality metadata
- `exclusions.jsonl`: unavailable inputs and deterministic sample exclusions
- `label-conflicts.jsonl`: the catalog's complete positive/negative conflict
  registry

No token, judgment, or confidence minimum is applied. The manifest reports
sub-50-token coverage explicitly. Reverse-direction rows remain attached to the
selected frame with their multiplicity and are marked as execution exclusions.
Reusing a selection validates all artifact checksums. Phase 3 materializes a
Type-1, Type-2, or known-false-positive selection directly from the compiled
fragment store:

```bash
make bigclonebench-snapshot \
  BIGCLONEBENCH_SELECTION_ID=<selection-id>
```

The command validates the selection and compiled catalog without opening H2,
verifies each selected fragment object, and writes generated old/new Java files
straight into the shared content-addressed input snapshot. Synthetic class names
derive from fragment-content identity, and all contributing rows remain in each
case's snapshot metadata. The mutable `benchmarks/bigclonebench/cases/` tree is
not read or written.

## Combined Suite

Run every currently supported pair set without copying any dataset, selection,
snapshot, or corpus identifier:

```bash
make bigclonebench-suite MODE=sample
make bigclonebench-suite MODE=census
```

The command compiles or reuses the dataset, publishes or reuses a deterministic
selection for Type 1, Type 2, and known false positives, reuses immutable
snapshots and srcDiff corpora when their inputs and tool identity are unchanged,
then creates a separate srcMove evaluation for each pair set. Results are never
blended into one accuracy percentage. Combined run metadata is saved below
`benchmark-data/bigclonebench/suite-runs/` and links to each append-only
evaluation run.

Compiled snapshots use `input.java` as the relative filename on both sides.
This is required in archive mode: srcDiff pairs files by relative path and would
treat differently named old/new files as a whole-file deletion and insertion.

The live `srcMove execution` counter reports completed cases, while its suffix
reports oracle passes. The final digest leads with `PASS` or `FAIL` and
`passed X/Y` for each pair set; whole-fragment detection, wrong classification,
misses, errors, false acceptances, and incidental moves are secondary
diagnostics. Exit status 0 means every selected case in every pair set passed;
status 1 means the benchmark completed but at least one oracle case failed.

Use `ROLE=tuning|evaluation`, `SEED=<integer>`, `SAMPLE_SIZE=<count>`, and
`VERIFY_SOURCE=1` as needed. Normal development runs trust artifacts when they
were sealed: they validate manifest identities and hash `srcdiff` and `srcMove`
once, but do not revisit the original dataset or rehash selection JSONL,
snapshot sources, or corpus XML. `VERIFY_SOURCE=1` is the explicit upstream
audit; it rehashes the original H2 database, H2 driver, and selected Java
sources before accepting a compiled cache. The compile, select, snapshot,
corpus, and evaluate commands remain available as debugging interfaces, and
direct snapshot/corpus loads retain full checksum verification.

The workflow keeps generated sources, reusable srcDiff XML, and srcMove runs
separate. Generate a deterministic tuning slice:

```bash
make bigclonebench-cases LIMIT=10
```

Generate the slice and run the staged benchmark with the workspace's srcDiff
and srcMove builds in one command:

```bash
make bigclonebench LIMIT=10
```

The case generator defaults to `CLONE_TYPE=type1`, `LIMIT=100`,
`SELECTION_ROLE=tuning`, and `CASES_DIR=benchmarks/bigclonebench/cases`.
`CANDIDATE_LIMIT`, `DEDUPE`, and `TEXT_CHANGE` can also be set as needed.
These targets are available from either `srcMove` or the SrcMLBuildTemplate
workspace root and run inside Docker when invoked from the workspace root.
Interactive runs use one updating progress line per phase, including the current
case and elapsed time. Redirected output uses sparse progress checkpoints. Tool
failures appear immediately; detailed stdout and stderr remain in the saved
attempt artifacts, and the final digest lists up to five failing cases.

The command creates or reuses the input snapshot and corpus, records every
srcDiff attempt, and writes a new append-only srcMove evaluation run.

For debugging, invoke the lower-level pipeline directly. The equivalent setup
and coupled benchmark commands are:

```bash
python3 benchmarks/bigclonebench/pipeline.py preflight
python3 benchmarks/bigclonebench/pipeline.py cases \
  --clone-type type1 --limit 10 --selection-role tuning
python3 benchmarks/bigclonebench/pipeline.py benchmark \
  --clone-type type1 --cases-dir benchmarks/bigclonebench/cases \
  --srcdiff /workspace/srcDiff/build/bin/srcdiff \
  --srcmove /workspace/srcMove/build/srcMove
```

To debug individual stages, create the input snapshot, corpus, and evaluation
separately:

```bash
python3 benchmarks/bigclonebench/pipeline.py snapshot --clone-type type1
python3 benchmarks/bigclonebench/pipeline.py corpus INPUT_SNAPSHOT_ID \
  --srcdiff /path/to/srcdiff
python3 benchmarks/bigclonebench/pipeline.py evaluate CORPUS_ID \
  --srcmove /path/to/srcMove
```

After corpus creation, any number of srcMove builds can be evaluated without
BigCloneBench, its source files, or `srcdiff` being available.

Each evaluation writes `summary.json` and `cases.csv` below its unique
`benchmark-data/runs/<run-id>/` directory. Reports are never written to one
shared summary path. The summary reconciles upstream failures, srcDiff semantic
ineligibility, srcMove tool failures, misses, wrong classifications, other
oracle failures, and strict passes. It reports both the end-to-end rate over all
selected cases and the conditional rate over srcDiff-eligible cases.

The selected count can be below the requested limit after dedupe and filtering.
The selection manifest declares the exact query and parameters, ordered row
identifiers, input and tool checksums, pair direction, dedupe policy, and
whether the cases are tuning or evaluation data. The default ordered
convenience slice makes no claim about the wider BigCloneBench population.

By default, generated cases are deduped by exact raw extracted fragment pairs:

```bash
python3 benchmarks/bigclonebench/pipeline.py cases \
  --dedupe raw-text-pair --limit 10
```

Raw text is the default because BigCloneBench Type-1 allows whitespace and
comment differences. Collapsing those differences would remove useful Type-1
move tests. Use `--dedupe none` only when you specifically want row-based
BigCloneBench coverage, including duplicates.

To focus on the rare Type-1 rows where the extracted fragments are not raw-text
identical:

```bash
python3 benchmarks/bigclonebench/pipeline.py cases \
  --clone-type type1 --text-change raw-different
```

Run a smaller Type-2 sample:

```bash
python3 benchmarks/bigclonebench/pipeline.py cases --clone-type type2 --limit 10
```

Generate and run known false positives as negative cases:

```bash
make bigclonebench CLONE_TYPE=known-false-positive LIMIT=10
```

The equivalent direct commands are:

```bash
python3 benchmarks/bigclonebench/pipeline.py cases \
  --known-false-positives --limit 10
python3 benchmarks/bigclonebench/pipeline.py benchmark \
  --known-false-positives --cases-dir benchmarks/bigclonebench/cases \
  --srcdiff /workspace/srcDiff/build/bin/srcdiff \
  --srcmove /workspace/srcMove/build/srcMove
```

The negative selection reads `false_positives`, retains the smaller joined
function token count as reporting metadata without filtering on it, and defaults
to at least one judge and one confidence point. Use `--min-judges` and
`--min-confidence` when generating a stricter slice. Its manifest is
`bcb_fp_manifest.json`; cases use the `bcb_fp_` prefix, so they cannot collide
with positive Type-1/Type-2 selections.

The legacy coupled `run.py` remains as an exploratory reference only. It has no
compatibility guarantee and may be removed after the staged pipeline replaces
its remaining diagnostic uses. Thesis and cross-build results should use
`pipeline.py` so srcDiff failures, semantic eligibility, provenance, immutable
corpus reuse, and append-only run artifacts are preserved.

## Thesis Data Runs

For thesis or paper data, freeze the declared evaluation selection separately
from tuning cases with `--selection-role evaluation`. Publication enforcement
and archive verification belong to Phase 6; Phase 4 development runs already
retain their manifests and summaries by run identifier. Generate the immutable
srcDiff corpus first, then use the shared
[performance workflow](../README.md#performance-measurements) to compare srcMove
builds without rerunning BigCloneBench or srcDiff.

## Validation

- Type-1 expects one `exact` move.
- Type-2 expects one `type2` move.
- A known-false-positive case expects no single reported move to link the full
  generated source and target fragments. Zero moves passes. Smaller incidental
  child moves also pass and are reported separately; requiring zero moves would
  incorrectly treat every shared child subtree as a whole-pair false positive.
- The reported delete and insert move positions must overlap the synthetic line
  ranges for the BigCloneBench fragments stored in `metadata.json`.
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
