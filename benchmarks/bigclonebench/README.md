# BigCloneBench Benchmark

This suite generates synthetic move benchmarks from BigCloneBench clone pairs.
It supports both quick smoke runs and large Type-1/Type-2 batches. The generated
case directories live under `benchmarks/bigclonebench/cases/` and are ignored by
git.

Run the default one-case Type-1 smoke test:

```bash
python3 benchmarks/bigclonebench/run.py
```

Run more Type-1 cases:

```bash
python3 benchmarks/bigclonebench/run.py --limit 10
```

Run a large Type-1 batch:

```bash
python3 benchmarks/bigclonebench/run.py --clone-type type1 --limit 1000
```

Run a large Type-2 batch:

```bash
python3 benchmarks/bigclonebench/run.py --clone-type type2 --limit 1000
```

The selected count can be below the requested limit after dedupe and filtering.
Treat the generated manifest and summary as the source of truth for a run.

By default, generated cases are deduped by exact raw extracted fragment pairs:

```bash
python3 benchmarks/bigclonebench/run.py --dedupe raw-text-pair --limit 10
```

Raw text is the default because BigCloneBench Type-1 allows whitespace and
comment differences. Collapsing those differences would remove useful Type-1
move tests. Use `--dedupe none` only when you specifically want row-based
BigCloneBench coverage, including duplicates.

To focus on the rare Type-1 rows where the extracted fragments are not raw-text
identical:

```bash
python3 benchmarks/bigclonebench/run.py --clone-type type1 --text-change raw-different
```

Run a smaller Type-2 sample:

```bash
python3 benchmarks/bigclonebench/run.py --clone-type type2 --limit 10
```

The BigCloneBench-native spelling also works:

```bash
python3 benchmarks/bigclonebench/run.py --syntactic-type 2 --limit 10
```

Each run also writes `benchmarks/bigclonebench/cases/summary.csv`. This is the
quick index for reviewing a batch without opening every generated case. It
records the case id, pass/fail status, clone type, BigCloneBench function ids,
source files, dedupe keys, per-run dedupe group sizes and indices, reported move
counts, reported match-kind counts, whether the extracted fragments are
raw/trim-identical, text-validation status, failure classification, and failure
messages.

The runner uses the generator's manifest for the selected cases. This prevents
old ignored case directories from a previous larger run from silently becoming
part of a smaller deduped run.

## Thesis Data Runs

For thesis or paper data, archive each run's generated metadata before starting
the next run. The Type-1 and Type-2 runners both overwrite the shared
`benchmarks/bigclonebench/cases/summary.csv`, so copy the Type-1 summary before
running Type-2. Archive the matching manifest with each summary:

```text
benchmarks/bigclonebench/cases/summary.csv
benchmarks/bigclonebench/cases/bcb_t1_manifest.json
benchmarks/bigclonebench/cases/bcb_t2_manifest.json
```

Use a timestamped archive directory in the thesis repository, currently
`doc/thesis/thesis-data/<timestamp>/`, and keep the archived data there rather
than duplicating large thesis data in srcMove docs. For repeatable performance
data, write profiler output directly into the archive and avoid replacing
`profile-results/latest.*`:

```bash
python3 benchmarks/profile.py \
  --suite bigclonebench \
  --clone-type type1 \
  --repeats 5 \
  --label thesis-type1 \
  --out doc/thesis/thesis-data/<timestamp>/profile/thesis-type1.csv \
  --no-latest
```

The profiler records internal `srcMove --profile` timings only. It does not
include Python startup, BigCloneBench database loading, case generation, or
`srcdiff` generation time.

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

The runner invokes `srcdiff` with `--position` so `diff_new.xml` contains
`pos:start` / `pos:end` attributes. This makes the oracle independent of raw
string formatting differences introduced by the synthetic wrapper.

Type-2 is a strict test mode. If current srcMove does not detect a generated
BigCloneBench Type-2 pair, the command exits nonzero and reports the missed move.

Type-3 and Type-4 moves are not supported.
