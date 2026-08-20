# srcMove Benchmarks

Benchmarks are experiments and are intentionally separate from deterministic
correctness tests in `tests/`.

- [BigCloneBench](bigclonebench/README.md): synthetic positive-case Type-1 and
  Type-2 detection workloads generated from BigCloneBench clone pairs.
- [Repository benchmarks](repositories/README.md): end-to-end `srcdiff` and
  `srcMove` runs across configured revisions of real repositories.
- `profile.py`: paired/interleaved internal and external performance measurements
  over immutable srcDiff XML.

Generated benchmark data is ignored by Git but saved automatically below
`benchmark-data/`. Repository invocations create append-only run records and a
small series index; see the [repository benchmark guide](repositories/README.md).
Treat those manifests and their referenced immutable artifacts—not mutable
`work/` directories—as the authoritative result.

The phased upgrade of reusable srcDiff corpora, provenance, failure incidents,
dataset adapters, and publication runs is described in the
[benchmarking upgrade plan](../doc/benchmarking_upgrade_plan.md).

## Upgrade contracts

`contracts.py` is the versioned shared boundary for the upgrade. It defines the
canonical content-identity encoding, process/XML/provenance status vocabulary,
development/publication labels, and the narrow interface implemented by dataset
adapters. Dataset adapters expose old/new input pairs and add semantic eligibility
checks; they must not replace shared execution, provenance, storage, or
reporting.

Phase 0 characterization is entirely offline. Tiny source and srcDiff fixtures,
a configurable fake executable, and strict BigCloneBench oracle tests live under
`tests/`. BigCloneBench remains an external manual prerequisite and normal tests
must neither download it nor depend on historical large-run counts.

Older benchmark-specific interfaces remain exploratory references, not
compatibility contracts:

- `benchmarks/bigclonebench/run.py` generates and evaluates cases together,
  writing ignored cases and a replaceable `cases/summary.csv`.
- `benchmarks/repositories/run_case.py` is the public repository orchestrator.
  Its case-local `work/` directory is only a checkout/export cache; authoritative
  input snapshots, attempts, corpora, runs, and series indexes are stored under
  `benchmark-data/`.
- `benchmarks/profile.py` reads existing XML inputs and writes ignored local
  profiles unless an explicit output is selected.

Previously archived thesis results are historical evidence, not regression
expectations for the refactored implementation.

## Provenance foundation

`provenance.py` provides read-only collection of repository state, relevant
untracked source checksums, executable and input checksums, and a small host
environment snapshot. It validates a build receipt when one exists but never
infers that a nearby binary came from the current checkout. Binary verification
and current-checkout agreement are reported separately.

The supported CMake build writes
`<srcMove executable>.build-receipt.json` immediately after linking `srcMove`.
The receipt binds the executable checksum to the observed srcMove/srcReader
source state, workspace-lock checksum when available, compiler, configuration,
and relevant CMake options. It records tests as `not_run`; building alone is not
evidence that tests passed.

Development and publication labels are part of observation manifests, but
publication requirements are not enforced yet. The staged workflows record
these observations; legacy coupled runners do not.

## Staged corpus workflow

`pipeline.py` provides the shared input snapshot, attempt, corpus, and run stages.
Generated data defaults to the ignored `benchmark-data/` directory.
Input snapshots and corpora use content-derived identifiers; runs use unique,
append-only identifiers.

An **input snapshot** is a frozen, checksummed old/new source pair saved for
later srcDiff execution. It makes the exact source inputs reusable without
depending on a mutable checkout or repeating repository export.

### Current srcDiff language limitation

srcDiff does not currently support Python input reliably and may terminate or
emit unusable XML when Python files are present. The shared input-snapshot
workflow therefore excludes `.py` files automatically and records every
excluded path in the snapshot manifest. This is a srcDiff limitation, not a
claim that Python is outside srcMove's intended scope.

Every tool invocation owns a unique attempt directory. Its atomic terminal
record keeps process termination separate from XML validation, retains bounded
stdout/stderr with full-stream checksums, and records timeout cleanup. The
temporary `started.json` checkpoint is removed after a terminal record is
sealed. Only a normal zero exit with structurally valid, checksummed srcDiff XML
can be promoted into a corpus. After promotion, the corpus copy is the sole
owner of successful srcDiff XML; failed output remains with its attempt. Input
snapshots and corpus XML are checksum-verified again whenever consumed.

Repository commands are documented in the
[repository benchmark guide](repositories/README.md). An existing corpus can be
replayed with a different srcMove executable without the input snapshot's
original checkout or `srcdiff` being available.

BigCloneBench uses the same core through its
[staged benchmark guide](bigclonebench/README.md). Its adapter adds only the
versioned payload-exposure eligibility check and strict Type-1/Type-2 oracle.
Fixture-backed unit tests cover corpus reuse across multiple srcMove builds and
reconcile upstream failures, semantic ineligibility, misses, wrong
classifications, and passes without installing BigCloneBench.

Generation batches checkpoint every terminal case. Repeating `generate` with
the same input snapshot, executable, and options skips recorded cases; use
`--retry-failed` (and optionally repeatable `--case`) to append child attempts
without replacing earlier evidence. `run` supports the same selection policy
with `--resume-run RUN_ID`. Linux attempts record process-group peak RSS and
cgroup OOM evidence when those interfaces are available.

`investigate.py` replays a preserved srcDiff incident from its checksummed input
snapshot. A repeatable `--relative-path` selects individual files while
preserving their paths; `isolate` bisects an archive inventory and retains the
candidate subsets and every attempt below `benchmark-data/investigations/`.

## Performance measurements

`profile.py` compares one or more named srcMove builds on identical checksummed
inputs. The first `--variant` is the comparison baseline. The recorded schedule
keeps builds adjacent for each case/repetition, rotates their order, and uses the
declared seed to make the schedule reproducible:

```bash
python3 benchmarks/profile.py \
  --variant baseline=/path/to/baseline/srcMove \
  --variant candidate=/path/to/candidate/srcMove \
  --corpus CORPUS_ID \
  --warmups 1 \
  --repetitions 6 \
  --seed 2026 \
  --cache-policy warm_os_cache
```

Use repeatable `--case CASE_ID` to select accepted corpus cases. For a small
standalone experiment, replace `--corpus` with repeatable
`--input NAME=/path/to/input.srcdiff.xml`. Measured repetitions must be at least
the number of variants so each build can occupy each schedule position.

Each append-only run is stored below
`benchmark-data/performance/runs/<run-id>/` with:

- `run.json`: input and binary checksums, provenance, environment, policy, and
  the complete schedule
- `raw.csv`: warmup and measured attempts, including failures, external wall/CPU
  time, Linux peak RSS when available, workload sizes, and srcMove internal
  timings
- `summary.json`: per-build and per-case median/MAD summaries plus paired deltas
  and ratios against the baseline
- `attempts/`: exact commands, bounded logs, result JSON, terminal records, and
  failed output evidence. Successful output XML is checksummed and structurally
  validated, then discarded to avoid multiplying large corpus storage.

The cache policy is declared metadata; the runner does not flush or warm caches
implicitly. A completed run can contain failed measurements, returns a nonzero
CLI status when it does, and retains those failures in `raw.csv` and the summary.

## Reporting wishlist

These are desired thesis-facing outputs, not claims about fields already present
in every summary. Some underlying counts are recorded today but still need to be
calculated and presented consistently.

Highest priority:

- **Moved-region share:** report `annotated_region_count / regions_total` as a
  percentage, always alongside both counts. This answers what proportion of
  srcDiff's inserted and deleted regions srcMove classified as belonging to a
  move. Keep move-group and move-pair counts separate because they use different
  units.
- **Change composition:** report inserted regions, deleted regions, total changed
  regions, and unchanged or whitespace-only elements excluded from the
  denominator.
- **Move structure:** report one-to-one, many-region, exact, Type-2, ambiguous,
  insertion-only, deletion-only, and copy-or-repeat groups, with counts and
  percentages.
- **Move size distribution:** report moved lines or tokens per move using median,
  quartiles, range, and a small histogram. A few very large moves should not
  obscure the typical detected move.
- **Scale-normalized results:** report moves and moved regions per thousand
  changed lines or per thousand diff regions, together with files and source
  lines examined. This makes projects of different sizes comparable.
- **Per-project distributions:** retain every project/revision-pair result and
  summarize across projects with medians and quartiles. Do not rely only on one
  pooled total dominated by the largest repository.

For datasets with a trustworthy oracle, such as the controlled BigCloneBench
cases:

- report true positives, false positives, false negatives, precision, recall,
  and F1, split by Type-1 and Type-2 cases;
- report the number selected, excluded, semantically ineligible, executed, and
  successfully scored so every accuracy denominator is auditable;
- keep tuning and evaluation results separate and label them prominently.

For performance and reliability:

- report srcDiff and srcMove wall time and peak memory separately, plus srcMove
  throughput normalized by input bytes and diff-region count;
- report repeated-run medians, variability, paired deltas, and practical effect
  sizes when comparing srcMove builds;
- report srcDiff failures, invalid XML, timeouts, srcMove failures, and excluded
  files as first-class results rather than silently dropping them;
- attach input, corpus, executable, configuration, environment, and source
  revision identifiers to every table intended for the thesis.
