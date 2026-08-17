# srcMove Benchmarks

Benchmarks are experiments and are intentionally separate from deterministic
correctness tests in `tests/`.

- [BigCloneBench](bigclonebench/README.md): synthetic positive-case Type-1 and
  Type-2 detection workloads generated from BigCloneBench clone pairs.
- [Repository benchmarks](repositories/README.md): end-to-end `srcdiff` and
  `srcMove` runs across configured revisions of real repositories.
- `profile.py`: repeatable internal `srcMove --profile` measurements over
  prepared XML inputs.

Generated benchmark data is ignored. Archive thesis-quality results with their
manifest and metadata rather than treating a mutable working directory as the
authoritative result.

The planned upgrade to separate prepared srcDiff corpora, provenance, failure
incidents, and publication runs is described in the
[benchmarking upgrade plan](../doc/benchmarking_upgrade_plan.md).

## Upgrade contracts

`contracts.py` is the versioned shared boundary for the upgrade. It defines the
canonical content-identity encoding, process/XML/provenance status vocabulary,
development/publication labels, and the narrow interface implemented by dataset
adapters. Dataset adapters may prepare inputs and add semantic eligibility
checks; they must not replace shared execution, provenance, storage, or
reporting.

Phase 0 characterization is entirely offline. Tiny source and srcDiff fixtures,
a configurable fake executable, and strict BigCloneBench oracle tests live under
`tests/`. BigCloneBench remains an external manual prerequisite and normal tests
must neither download it nor depend on historical large-run counts.

The older benchmark-specific interfaces remain available:

- `benchmarks/bigclonebench/run.py` generates and evaluates cases together,
  writing ignored cases and a replaceable `cases/summary.csv`.
- `benchmarks/repositories/run_case.py` exports revisions and runs both tools,
  writing ignored artifacts below each case's `work/` directory. Network access
  is disabled unless `--refresh-repo` is passed, and Python exclusion is an
  explicit `--exclude-python` filter recorded in the report.
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

Development and publication labels are now part of observation manifests, but
publication requirements are not enforced yet. The staged workflow records
these observations; legacy benchmark runners do not yet consume them.

## Staged corpus workflow

`pipeline.py` provides the shared preparation, attempt, corpus, and run stages.
Generated data defaults to the ignored `benchmark-data/` directory.
Preparations and corpora use content-derived identifiers; runs use unique,
append-only identifiers.

Every tool invocation owns a unique attempt directory. Its atomic terminal
record keeps process termination separate from XML validation, retains bounded
stdout/stderr with full-stream checksums, and records timeout cleanup. Only a
normal zero exit with structurally valid, checksummed srcDiff XML can be
promoted into a corpus. Prepared inputs and corpus XML are checksum-verified
again whenever consumed.

Repository commands are documented in the
[repository benchmark guide](repositories/README.md). An existing corpus can be
replayed with a different srcMove executable without the source preparation or
`srcdiff` being available.

Generation batches checkpoint every terminal case. Repeating `generate` with
the same preparation, executable, and options skips recorded cases; use
`--retry-failed` (and optionally repeatable `--case`) to append child attempts
without replacing earlier evidence. `run` supports the same selection policy
with `--resume-run RUN_ID`. Linux attempts record process-group peak RSS and
cgroup OOM evidence when those interfaces are available.

`investigate.py` replays a preserved srcDiff incident from its checksummed
preparation. A repeatable `--relative-path` selects individual files while
preserving their paths; `isolate` bisects an archive inventory and retains the
candidate subsets and every attempt below `benchmark-data/investigations/`.
