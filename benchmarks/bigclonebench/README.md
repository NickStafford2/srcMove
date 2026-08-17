# BigCloneBench Benchmark

This suite currently generates synthetic positive move cases from BigCloneBench
clone pairs. It supports both quick smoke runs and large Type-1/Type-2 batches.
The resulting pass rate is a strict synthetic detection-and-classification rate
for the selected cases: Type-1 must report `exact`, Type-2 must report `type2`,
and the position/text oracle must pass. It is not general accuracy, recall, or
precision. The generated case directories live under
`benchmarks/bigclonebench/cases/` and are ignored by git.

BigCloneBench's known false-positive clone pairs are an optional future source of
negative cases; they are not required for this positive-case benchmark's declared
purpose. Any such extension needs its own srcMove-specific conversion and oracle.
See the [conversion methodology](../../doc/bigclonebench_srcmove_conversion.md).

BigCloneBench is an external manual prerequisite. Check it without fetching or
modifying anything:

```bash
python3 benchmarks/bigclonebench/pipeline.py preflight
```

The workflow keeps generated sources, reusable srcDiff XML, and srcMove runs
separate. Generate a deterministic tuning slice:

```bash
python3 benchmarks/bigclonebench/pipeline.py cases \
  --clone-type type1 --limit 10 --selection-role tuning
```

Then run the complete saved benchmark without passing intermediate identifiers:

```bash
python3 benchmarks/bigclonebench/pipeline.py benchmark \
  --clone-type type1 \
  --srcdiff /path/to/srcdiff \
  --srcmove /path/to/srcMove
```

The command creates or reuses the input snapshot and corpus, records every
srcDiff attempt, and writes a new append-only srcMove evaluation run.

For stage-level debugging, create the input snapshot, corpus, and evaluation
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

Type-3 and Type-4 moves are not supported.
