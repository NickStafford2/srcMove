# Benchmarking Upgrade Plan

## Status and Purpose

This document is a plan, not a description of implemented behavior. The current
commands and output formats remain documented in the
[benchmark index](../benchmarks/README.md).

The goal is to turn srcMove's early benchmark scripts into a reproducible,
inspectable evaluation system suitable for master's thesis results without
making normal development across srcML, srcDiff, srcReader, and srcMove
cumbersome.

The upgraded system must answer four different questions:

1. **Correctness:** Did a known behavior regress?
2. **Detection capability:** How often does srcMove recognize moves in a defined
   evaluation dataset?
3. **Performance:** How much time and memory does srcMove require for a fixed
   srcDiff input?
4. **Reliability and scale:** Which real repositories can the srcML/srcDiff/srcMove
   pipeline process, and how do failures occur?

These questions require related infrastructure, but their results must not be
combined into one ambiguous score.

The current implementation already has useful BigCloneBench generation,
position/text validation, repository export, internal profiling, and shared tool
discovery. Its main gaps are that srcDiff and srcMove execution are coupled,
repository failure reports are written only after both tools succeed, processes
have no timeout policy, Python files are removed implicitly, prepared srcDiff
XML is only an incidental cache, BigCloneBench summaries overwrite one shared
path, and performance provenance does not yet bind source state to binaries and
input checksums.

## Terminology and Suite Boundaries

### Correctness tests

Small, checked-in, deterministic cases belong in `tests/`. They should be fast
enough for routine development and should normally pass before a change is
merged.

### BigCloneBench-derived synthetic positive-case evaluation

BigCloneBench belongs under `benchmarks/`, even though each generated case uses
an oracle like a test. The current generated workload measures whether srcMove
recognizes whole-fragment synthetic moves constructed from selected Type-1 and
Type-2 clone pairs. A benchmark does not have to measure only execution time.

These are positive cases, so their pass rate is a synthetic detection rate for
the declared BigCloneBench slice and oracle. It is not general move-detection
recall, historical-edit accuracy, overall accuracy, or precision. See the
[conversion methodology](bigclonebench_srcmove_conversion.md) for the exact
construction and its limitations.

When this evaluation discovers a useful failure, minimize it and promote the
small stable example into `tests/regression/`. The large evaluation continues
to measure breadth; the promoted test prevents recurrence.

BigCloneBench also contains known false-positive clone pairs. They are a
promising future source of synthetic negative cases because srcMove needs many
tests showing which similar regions it must not label as moves. That extension
is deliberately later work: it needs a documented conversion and negative
oracle that are appropriate for srcMove rather than assuming a clone-detector
false positive transfers directly to move detection. Unexpected extra moves in
a positive synthetic case remain diagnostics, not a precision metric.

### Repository evaluation

Repository revision pairs measure pipeline reliability, scale, resource use,
and observed move counts. Without a labeled oracle, move counts are not accuracy
measurements. A later manually reviewed, stratified sample—supported by
srcVisual—can provide a real-world precision estimate with its sampling method
and uncertainty reported explicitly.

### Performance benchmark

Performance measurements run srcMove repeatedly over immutable, checksummed
srcDiff XML. srcDiff generation time is measured separately so upstream cost and
instability do not distort srcMove timing.

## Design Principles

1. **Separate preparation from measurement.** Source export, srcDiff generation,
   srcMove execution, validation, and reporting are distinct resumable stages.
2. **Observe normal development; gate only publication runs.** Development
   benchmarks record provenance and warn about uncertainty without switching
   branches or rejecting useful experiments.
3. **Never infer provenance from a path, `--version` string, or nearby checkout.**
   A post-build observation records what is present; only a receipt emitted by
   the build can establish a source-to-binary claim.
4. **Preserve failures as data.** A crash, signal, timeout, missing output, or
   malformed XML receives a structured report and retained diagnostic artifacts.
5. **Keep generated data out of source control.** Track schemas, small fixtures,
   and documentation; store large corpora and run outputs under ignored or
   explicitly selected external directories.
6. **Make results append-only.** A new run gets a new identifier and must not
   silently overwrite a previous summary.
7. **Report denominators and exclusions.** Skipped languages, files, duplicate
   pairs, invalid cases, and tool failures must remain visible.
8. **Keep one source of truth.** Methodology belongs in `doc/`; operational
   commands belong in the relevant `benchmarks/**/README.md`; schemas belong
   beside their implementation.

## Target Pipeline

```text
repository revisions or BigCloneBench rows
                    |
                    v
          prepared source cases
          + preparation manifest
                    |
                    v
             srcDiff stage
       /                              \
valid checksummed XML             incident record
       |                    (exit/signal/timeout/XML error)
       v
 reusable srcDiff corpus
       |
       v
 repeated srcMove runs
       |
       v
 validation + raw measurements + summary
```

The srcDiff corpus is a first-class input dataset. Once prepared, it can be used
to compare srcMove revisions without rerunning srcDiff. Changing srcDiff or
srcML creates a new corpus identity rather than mutating the old corpus.

For BigCloneBench, well-formed srcDiff XML is necessary but not sufficient. The
corpus must also record whether srcDiff exposed the intended synthetic payload
as usable delete/insert regions. That dataset-specific eligibility rule belongs
in the [conversion methodology](bigclonebench_srcmove_conversion.md), not in the
generic corpus format.

## Artifact and Provenance Model

Generated roots should be configurable, with an ignored local default. A
conceptual layout is:

```text
benchmark-data/
  corpora/
    <corpus-id>/
      manifest.json
      cases/
        <case-id>/
          input.srcdiff.xml
          case.json
          srcdiff.stdout.txt
          srcdiff.stderr.txt
  incidents/
    <incident-id>/
      incident.json
      srcdiff.stdout.txt
      srcdiff.stderr.txt
      partial.srcdiff.xml
  runs/
    <run-id>/
      run.json
      cases.csv
      summary.json
      logs/
```

Exact names may change during implementation, but the separation between
corpora, incidents, and runs should remain.

### Observed source and artifact state

For each relevant repository, record:

- repository identity and full commit
- branch as informational metadata
- tracked dirty state, a working-tree diff hash, and relevant untracked source
  paths
- optional captured patch for a deliberately preserved development experiment

When srcMove is developed inside a coordinating workspace, a workspace source
lock may describe a known-compatible combination. A benchmark must still record
the actual state it observed; the lock is an intended checkpoint, not proof that
a particular binary came from it.

The run-time provenance collector also records resolved executable paths and
checksums, relevant environment facts, and the observation time. This snapshot
describes the repositories and artifacts that were present when the run began.
It must not claim that an executable was built from the current checkout merely
because the executable is near that checkout or its version string looks
compatible.

### Build-time receipt and verification status

A build receipt can bind source state to executable artifacts only when the build
creates it as part of producing those artifacts. A benchmark-time collector may
locate and validate an existing receipt, but must not reconstruct one from the
current checkout and present that reconstruction as proof.

The required receipt core should remain small enough for normal builds to emit
automatically:

- receipt schema version and stable receipt identifier
- source-state snapshot and source-lock checksum, when present
- exact build entry point, Debug or Release configuration, and relevant CMake
  options
- compiler identity and version
- container image or environment identity
- checksums for the executable artifacts produced by that build
- build completion time and test status

Extended publication metadata may additionally record upstream receipt
identities, linked srcML/srcReader artifact checksums, static or dynamic linkage,
and resolved dynamic-library paths and checksums. Collect these only where they
materially improve reproducibility; they should not make ordinary development
builds slow or fragile.

Each consumed executable receives one of these provenance statuses:

- `verified`: its checksum matches an artifact in a valid build-time receipt
- `stale`: a candidate receipt exists, but its recorded artifact checksum does
  not match the executable being used
- `unverified`: the executable is usable, but no build-time receipt establishes
  its source-to-binary binding
- `unavailable`: required artifact or repository observations could not be
  collected

Whether the currently checked-out sources match the receipt is a separate
recorded relationship; a developer may legitimately run a verified older build
while editing newer sources. Receipt creation must not force normal builds to
match the workspace lock.

### Corpus manifest

Each srcDiff corpus records:

- schema version and stable corpus identifier
- source dataset or repository URLs and exact revisions
- selected subdirectories and explicit include/exclude policy
- file counts, language counts, byte counts, and excluded-file counts
- srcML/srcDiff build receipt and verification status, or an explicitly
  unverified observed-artifact snapshot, plus the exact command
- per-case XML checksum, byte size, validity, and generation status
- dataset-specific metadata, including BigCloneBench database/corpus identity

### Run manifest

Each srcMove run records:

- schema version and unique run identifier
- corpus identifier and manifest checksum
- srcMove/srcReader build receipt and verification status, or an explicitly
  unverified observed-artifact snapshot
- exact binary and input checksums
- command, environment, timestamps, and exit status
- development or publication mode
- warmup, repetition, ordering, timeout, and resource-measurement policy
- validation result and paths to raw measurements

The run directory should contain a copy or immutable snapshot of critical
provenance rather than only a pointer to a mutable current lockfile.

## Development and Publication Workflows

### Development mode

Development runs use the binaries already available. They should:

- collect observed source and artifact state automatically
- validate a build-time receipt when one exists; otherwise label the executable
  `unverified`
- warn about dirty repositories, stale receipts, unverified binaries, or a lock
  mismatch
- continue when the run remains technically possible
- clearly label results as development data
- never switch branches, clean repositories, or rebuild unrelated projects

Dirty development results can be useful for comparison and diagnosis, but are
not publication-ready unless the tested patch is preserved.

### Publication mode

Publication mode is explicit. It should:

- require clean, recorded source revisions
- use Release builds from an isolated workspace or isolated build directories
- avoid disturbing active development checkouts and build trees
- require `verified` build-time receipts and verify binary checksums against them
- run the deterministic correctness suite first
- consume immutable, checksummed inputs
- write an append-only result directory
- fail when required provenance is missing

Builds should be cached by their source and configuration identity. A
publication run may reuse a verified matching build; it need not rebuild all
four repositories every time.

For cached inputs, srcML and srcDiff are built when the corpus is generated.
Subsequent srcMove comparisons can reuse that corpus and rebuild only the
srcReader/srcMove side when its identity changes.

## srcDiff Reliability and Investigation

The srcDiff stage must write its report even when srcDiff fails. Classify at
least:

- success with valid XML
- nonzero exit
- terminating signal
- timeout
- output missing
- malformed or truncated XML
- resource exhaustion, when detectable

Record stdout, stderr, elapsed time, peak memory when available, the exact
command, partial-output metadata, and the source-case manifest. Batch execution
must continue after one case fails and support resuming incomplete work.

Repository filtering must be explicit and non-destructive. For example, Python
files may be excluded by a recorded policy while srcDiff's current Python bugs
are unresolved; exported source snapshots should not be silently mutated.

Diagnostic tooling should support:

- replaying one file pair with preserved relative paths
- identifying large and pathological files before a run
- bisecting file subsets to isolate an archive failure
- preserving a minimal reproduction with checksums and an exact command
- distinguishing malformed srcML/srcDiff data from srcMove failures

The benchmark runner should capture evidence that helps fix srcDiff, while
srcDiff-specific progress logging and invariant dumps should ultimately be
implemented in srcDiff itself.

## Evaluation Outputs

### BigCloneBench-derived synthetic positive-case evaluation

Report Type-1 and Type-2 separately. At minimum include:

- eligible, selected, generated, executed, passed, and failed counts
- distinct raw-text-pair count and deduplication policy
- srcDiff tool failures, srcDiff semantic-ineligibility outcomes, and srcMove
  detection misses as separate categories
- strict versus encoding-tolerant validation
- token-size and raw-text-relationship strata
- unexpected extra or child moves as diagnostic categories
- manifest and dataset checksums

Describe the main metric as the whole-fragment synthetic detection rate for a
precisely defined slice. The slice, denominator, conversion method, selection
policy, and exclusions must accompany every percentage. Reserve `recall` for a
design whose eligible population and sampling interpretation justify that term.

A later negative-case evaluation derived from BigCloneBench's known
false-positive pairs must be reported separately. Its results must not be mixed
into the current positive-case pass rate.

Report an end-to-end rate over generated cases and a conditional srcMove rate
over cases where srcDiff exposed the intended candidate regions. A valid XML
document that aligned away or otherwise failed to expose the payload is an
upstream semantic-ineligibility outcome, not a srcMove miss.

### Repository evaluation

Report:

- exact repository revisions and selected scope
- file/language/byte inventory and exclusions
- srcDiff success, failure class, time, and memory
- srcMove success, time, memory, input size, regions, candidates, and moves
- manually reviewed sample results only when an explicit annotation protocol is
  available

Move counts alone are descriptive output, not evidence of accuracy.

### Performance results

Retain both raw observations and summaries. Prefer:

- external wall time, CPU time, and peak resident memory
- srcMove internal stage timings
- input XML bytes and structural workload counts
- warmups plus multiple measured repetitions
- median and distribution/dispersion, not only a mean
- identical input checksums when comparing srcMove revisions

Case ordering and cache policy must be stable or recorded. Performance failures
must remain rows in the raw dataset instead of disappearing from summaries.

## Implementation Phases

### Phase 1: Schemas and provenance foundation

- Define versioned observed-state, build-receipt, corpus-manifest, incident, and
  run-manifest schemas.
- Add a read-only collector for repository state, binaries, and environment. It
  may validate a build-time receipt but must not infer a source-to-binary binding.
- Add cheap build-time receipt emission to the supported build path, with the
  mandatory core separated from optional extended publication metadata.
- Add development/publication labels without enforcing publication mode yet.
- Unit-test clean, dirty, missing-repository, verified, stale, unverified,
  unavailable, and malformed-manifest behavior.

**Complete when:** a trivial run records exactly which source states, binary
bytes, and input bytes it observed, and either verifies the binary against a
build-time receipt or truthfully labels the source-to-binary relationship as
unverified.

### Phase 2: Split preparation, srcDiff, and srcMove execution

- Refactor repository benchmarking into resumable stages.
- Make prepared srcDiff XML reusable by checksum.
- Write reports atomically and preserve prior runs.
- Allow selection of an existing corpus without requiring source repositories or
  srcDiff at srcMove execution time.

**Complete when:** srcMove can be rerun or compared across revisions without
rerunning srcDiff.

### Phase 3: Robust srcDiff failure handling

- Add timeouts, signal/exit classification, XML validation, and partial-artifact
  retention.
- Replace implicit Python deletion with a manifest-recorded filter.
- Continue batches after failures and support resume/retry selection.
- Add single-file replay and archive-subset isolation tooling.

**Complete when:** every srcDiff attempt yields either a valid corpus case or a
repeatable incident record.

### Phase 4: BigCloneBench evaluation migration

Begin this phase only after the repository benchmark has established the shared
preparation, corpus, provenance, and srcDiff failure-handling infrastructure.
BigCloneBench should adapt that foundation rather than create a second runner
architecture.

- Add a clear preflight error and setup guidance when BigCloneBench is absent.
- Separate case generation, srcDiff corpus generation, and srcMove evaluation.
- Add a semantic eligibility check that verifies srcDiff exposed the intended
  synthetic payload as usable delete/insert regions before attributing an
  outcome to srcMove.
- Store each run summary under its run identifier instead of overwriting one
  shared `summary.csv`.
- Preserve deterministic selection and the existing positional/text oracle.
- Report the synthetic positive-case detection rate and strata with tool
  failures separated from misses.
- Preserve BigCloneBench's known false-positive pairs as a documented future
  negative-case source; do not make their conversion a prerequisite for the
  positive-case migration.

**Complete when:** the same generated corpus can evaluate multiple srcMove
builds with immutable manifests and comparable summaries, and every generated
case is classified separately as an upstream tool failure, srcDiff semantic
ineligibility, srcMove miss, or oracle pass.

### Phase 5: Performance measurement

- Extend the current internal profiler runner rather than creating a competing
  timing path.
- Add external wall/CPU time, peak memory, workload sizes, warmups, and stable
  repeated measurements.
- Produce raw CSV or JSON rows plus a machine-readable summary.

**Complete when:** two srcMove revisions can be fairly compared on identical
inputs with sufficient provenance to reproduce the comparison.

### Phase 6: Publication workflow

- Add explicit strict validation for clean source, receipts, checksums, tests,
  Release configuration, and immutable output.
- Build or reuse verified artifacts in isolation from active development.
- Generate a compact thesis archive containing manifests, summaries, and the
  checksums/locations of large external artifacts.

**Complete when:** one command can either produce a self-describing thesis run
or stop before measurement with a precise unmet precondition.

### Phase 7: Scale progression

Increase scale only after the preceding layers are reliable:

1. tiny hand-authored and generated smoke cases
2. small BigCloneBench Type-1 sample
3. zlib or Notepad++ repository pair
4. larger BigCloneBench Type-1 and Type-2 slices
5. srcMove, SQLite, or similar medium repositories
6. OpenCV or a Linux subsystem
7. two exact full Linux kernel revisions

Each tier should establish expected runtime, storage, and failure behavior before
advancing. Full-kernel execution is a final scale target, not the first test of
the infrastructure.

## Testing Strategy for the Infrastructure

Use fake executables and tiny fixtures to test orchestration without invoking
the real toolchain. Cover:

- successful output
- nonzero exit and terminating signal
- timeout
- missing and malformed XML
- partial output
- stale build receipt or input checksum
- executable without a build-time receipt
- current checkout differing from a valid older build receipt
- dirty development provenance
- strict publication rejection
- interrupted batch resume
- preservation of earlier run directories

Keep a small real integration case for srcDiff-to-srcMove behavior. BigCloneBench
and repository-scale data remain outside the deterministic default test suite.

## Decisions to Resolve During Implementation

- final schema representation and generated-data root name
- compression policy for large srcDiff XML and transparent replay
- portable peak-memory collection inside the supported Docker environment
- whether development runs store a patch or only its hash by default
- corpus distribution and archival location for thesis reproducibility
- annotation and sampling protocol for real-world precision review
- conversion and negative oracle for BigCloneBench known false-positive pairs
- exact Linux revisions and whether the first large run targets a subsystem

These decisions should be made before their corresponding phase, not used to
delay the provenance and stage-separation foundation.

## Explicit Non-Goals

- forcing ordinary builds to match a source lock
- switching or cleaning active development checkouts automatically
- treating repository move counts as accuracy
- presenting the current BigCloneBench-derived positive-case pass rate as
  general recall, accuracy, or precision
- rerunning srcDiff for every srcMove performance comparison
- committing large generated corpora or benchmark results to the srcMove source
  repository
