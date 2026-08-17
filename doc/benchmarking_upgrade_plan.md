# Benchmarking Upgrade Plan

## Status and Purpose

This document is a plan, not a description of implemented behavior. The current
commands and output formats remain documented in the
[benchmark index](../benchmarks/README.md).

BigCloneBench is not installed in the current workspace, and the large
BigCloneBench and repository workloads have not been rerun since the current
srcMove refactor. Previously archived results are historical evidence, not a
validation baseline for the refactored implementation. This plan does not
authorize downloading or running large datasets as part of implementation.

The goal is to turn srcMove's early benchmark scripts into a reproducible,
inspectable evaluation system suitable for master's thesis results without
making normal development across srcML, srcDiff, srcReader, and srcMove
cumbersome.

The upgraded system must answer four different questions:

1. **Correctness:** Did a known behavior regress?
2. **Detection and classification capability:** How often does srcMove recognize
   and correctly classify moves in a defined evaluation dataset?
3. **Performance:** How much time and memory does srcMove require for a fixed
   srcDiff input?
4. **Reliability and scale:** Which real repositories can the srcML/srcDiff/srcMove
   pipeline process, and how do failures occur?

These questions require related infrastructure, but their results must not be
combined into one ambiguous score.

The thesis evaluation has two central empirical pillars. BigCloneBench provides
the best available large labeled source of Type-1 and Type-2 clone pairs for the
synthetic detection-and-classification evaluation. Repository revision pairs
provide the primary workloads for real-world scale, reliability, performance,
and failure analysis. The BigCloneBench implementation already provides a strong
baseline; most new engineering in this plan is therefore directed at reusable
srcDiff corpora and large-repository execution rather than redesigning its
generator or oracle.

The current implementation already has useful BigCloneBench generation,
position/text validation, repository export, internal profiling, and shared tool
discovery. Its main gaps are that srcDiff and srcMove execution are coupled,
repository failure reports are written only after both tools succeed, processes
have no timeout policy, Python files are removed implicitly, prepared srcDiff
XML is only an incidental cache, BigCloneBench summaries overwrite one shared
path, BigCloneBench does not yet distinguish srcDiff semantic ineligibility from
srcMove misses, and performance provenance does not yet bind source state to
binaries and input checksums.

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

These are positive cases, so their pass rate is a strict synthetic
detection-and-classification rate for the declared BigCloneBench slice and
oracle. It is not general move-detection recall, historical-edit accuracy,
overall accuracy, or precision. See the
[conversion methodology](bigclonebench_srcmove_conversion.md) for the exact
construction and its limitations.

The current strict oracle is intentional: a Type-1 case must detect the intended
whole-fragment move as `exact`, and a Type-2 case must detect it as `type2`, in
addition to satisfying the frozen position and text checks. A detected payload
with the wrong classification is useful diagnostic evidence but is not a pass.
The resulting percentage measures detection and classification under the
declared BigCloneBench slice and srcMove conversion—not universal agreement
between every possible clone taxonomy. Questionable labels, unsupported
variations, extraction problems, and conversion artifacts found among failures
belong in the thesis analysis rather than being silently removed to improve the
score. The canonical oracle is documented in the
[conversion methodology](bigclonebench_srcmove_conversion.md).

When this evaluation discovers a useful failure, minimize it and promote the
small stable example into `tests/regression/`. The large evaluation continues
to measure breadth; the promoted test prevents recurrence.

BigCloneBench also contains known false-positive clone pairs. They are an
optional future source of synthetic negative cases, not a missing requirement
for the current positive-case evaluation. Such an extension would need a
documented conversion and negative oracle appropriate for srcMove rather than
assuming a clone-detector false positive transfers directly to move detection.
Unexpected extra moves in a positive synthetic case remain diagnostics, not a
precision metric.

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

## Benchmark Compatibility Policy

Benchmark artifacts are intentionally forward-only while this infrastructure is
under development. A schema or oracle change may invalidate old preparations,
corpora, runs, and summaries; those artifacts may be deleted and regenerated.
The implementation should reject obsolete schema versions rather than carry
compatibility readers or migrations that complicate the future thesis pipeline.
Historical results remain evidence only in the context of the code, schema, and
oracle versions that produced them.

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
8. **Build one orchestration core.** Repository and BigCloneBench workflows are
   adapters over the same preparation, attempt, corpus, run, and reporting
   abstractions.
9. **Separate tuning from evaluation.** Cases used to diagnose and tune srcMove
   must remain identifiable; a thesis claim should use a frozen census or a
   separately declared evaluation sample.
10. **Keep one source of truth.** Methodology belongs in `doc/`; operational
   commands belong in the relevant `benchmarks/**/README.md`; schemas belong
   beside their implementation.
11. **Prefer a strict current contract over benchmark backward compatibility.**
   Follow the [forward-only compatibility policy](#benchmark-compatibility-policy).

## Target Pipeline

```text
repository revisions or BigCloneBench rows
                    |
                    v
          prepared source cases
          + preparation manifest
                    |
                    v
       srcDiff attempt in unique staging directory
                         |
                         v
             exit/output/XML validation
       /                              \
valid checksummed XML      failed terminal attempt (incident)
       |                    (exit/signal/timeout/XML error)
       v
atomic promotion into corpus
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

Every srcDiff invocation writes to a unique attempt staging directory, never
directly to a corpus case path. Only successful, validated, checksummed XML is
atomically promoted. Missing, partial, malformed, timed-out, signaled, or
nonzero-exit output remains attempt evidence and cannot become corpus input.

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
  preparations/
    <preparation-id>/
      manifest.json
      sources/                 # retained inputs when licensing permits
      external-artifacts.json  # immutable references otherwise
  attempts/
    <attempt-id>/
      attempt.json
      stdout.bin
      stderr.bin
      partial.srcdiff.xml
  corpora/
    <corpus-id>/
      manifest.json
      cases/
        <case-id>/
          input.srcdiff.xml
          case.json
  runs/
    <run-id>/
      run.json
      cases.csv
      summary.json
      logs/
```

Exact names may change during implementation, but the separation between
prepared inputs, execution attempts, accepted corpora, and evaluation runs
should remain. An incident is a failed terminal attempt, not a second execution
record with a competing schema.

### Prepared source manifest

A preparation is the exact input offered to srcDiff. Its manifest records the
source origin and revisions, selected scope, post-filter file inventory and
checksums, filtering policy, preparation-tool version, and retained-source or
external-artifact location. Repository exports may be retained locally;
BigCloneBench material may instead require a verified external reference because
of size or redistribution constraints. Either form must make replay possible
without relying on a mutable checkout.

Preparation identity is content-derived from a documented canonical identity
payload. Machine-specific paths, timestamps, and labels are metadata and do not
change the identity. The payload includes the schema version, ordered input
checksums, source revisions or dataset identity, selected scope, and filter
configuration.

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
- preparation identifier and manifest checksum
- source dataset or repository URLs and exact revisions
- selected subdirectories and explicit include/exclude policy
- file counts, language counts, byte counts, and excluded-file counts
- srcML/srcDiff build receipt and verification status, or an explicitly
  unverified observed-artifact snapshot, plus the exact command
- per-case attempt identifier, XML checksum, byte size, validity, and generation
  status
- dataset-specific metadata, including BigCloneBench database/corpus identity

The corpus identifier is the hash of a canonical identity payload containing the
schema version, preparation-manifest checksum, srcML/srcDiff artifact checksums,
generation configuration, and ordered accepted-case XML checksums. It excludes
timestamps, labels, absolute paths, and logs. An implementation must test that
copying the same content to another generated root preserves the identifier and
that changing any identity input changes it.

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
- runner, validator, and dataset-specific oracle versions or checksums
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
- never fetch, clone, or refresh a benchmark repository unless preparation was
  explicitly requested; corpus replay should work offline

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
- record host CPU, memory, kernel, container identity and limits, locale,
  timezone, and measurement-tool versions for performance claims

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

### Process execution contract

Process termination and output validation are separate fields, not one
overloaded status. The attempt record should represent termination as one of
`exited`, `signaled`, `timed_out`, `spawn_failed`, or
`orchestration_interrupted`. Record `exit_code` only for a normal exit and record
both signal number and portable signal name for a signal. A timeout remains
`timed_out` even though termination later sends signals; record those cleanup
signals separately.

The timeout covers wall-clock time from successful process creation until the
entire child process group has exited and been reaped. Initial CLI defaults are:

- 60 seconds for one synthetic or single-file srcDiff case
- 30 minutes for one repository/archive srcDiff case
- 5 minutes for one srcMove evaluation

Every override is recorded per stage in the manifest. Larger scale tiers must
choose and record an explicit override rather than silently disabling the
timeout. On the supported Linux environment, start the tool in a new process
group. At timeout, send `SIGTERM`, allow a five-second grace period, then send
`SIGKILL` to the remaining group and reap it. If a platform cannot provide the
same process-tree guarantee, record that limitation and reject publication mode.

Capture stdout and stderr as byte streams while the process runs so a full pipe
cannot deadlock it. The initial retained-log limit is 16 MiB per stream: preserve
the first and last 8 MiB, continue draining excess bytes, and record the total
byte count, omitted byte count, truncation flag, and full-stream checksum.
The limit applies to logs, not to the expected srcDiff XML artifact. Partial XML
records its byte count and checksum; retention or externalization follows the
declared artifact-storage policy and must never silently discard evidence.

### Attempt identity, validation, and publication

Give every invocation a collision-resistant attempt identifier. A retry creates
a new attempt, records its parent attempt identifier and retry ordinal, and
never overwrites the earlier evidence. The attempt owns unique staging paths for
stdout, stderr, XML, and its record, so files left by an earlier invocation
cannot satisfy a later attempt.

A zero exit code alone is not success. Corpus admission requires all of the
following:

- normal zero exit without a timeout or cleanup signal
- a present, nonempty output file created in this attempt's staging directory
- a complete XML parse with no trailing malformed content
- the expected single-file or archive document shape and required srcML/srcDiff
  namespace and element invariants
- recorded byte size and checksum

Dataset-specific semantic checks, such as BigCloneBench candidate exposure, run
after this generic structural admission and retain their own status.

Write the terminal attempt or incident record through a temporary file and
atomically rename it only after its referenced artifacts are finalized. If the
orchestrator itself stops first, the next invocation recovers the abandoned
staging directory as `orchestration_interrupted`; it never promotes its XML.
Likewise, promote validated XML and its case metadata into the corpus with one
atomic directory rename on the same filesystem.

Classify OOM or another resource exhaustion only when the operating system,
container runtime, or resource monitor supplies affirmative evidence. `SIGKILL`
alone is not proof of OOM; absent evidence, use `unknown_resource_failure` and
retain the observed signal and resource data.

### Repeatable incidents

An incident is repeatable only when it contains the exact prepared inputs or a
verified immutable reference to them, plus their checksums and filtering
manifest. It must also preserve the executable checksum and receipt or observed
provenance, argument vector, working directory, relevant environment, timeout
and cleanup policy, and all retained diagnostics. A command string that points
to mutable paths is not a repeatable incident.

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
- row counts before deduplication, distinct raw-text-pair counts after
  deduplication, and the deduplication policy
- declared population or sampling frame, exact eligibility query, ordering,
  candidate count, and census or sampling method
- seed and strata for a random sample, or an explicit statement that a
  deterministic convenience slice does not estimate the wider population
- pair-direction policy and functionality-group coverage
- srcDiff tool failures, srcDiff semantic-ineligibility outcomes, and srcMove
  detection misses as separate categories
- strict versus encoding-tolerant validation
- expected and observed srcMove match-kind counts
- token-size and raw-text-relationship strata
- unexpected extra or child moves as diagnostic categories
- manifest and dataset checksums

Describe the main metric as the strict whole-fragment synthetic
detection-and-classification rate for a precisely defined slice. The slice,
denominator, conversion method, selection policy, and exclusions must accompany
every percentage. Reserve `recall` for a design whose eligible population and
sampling interpretation justify that term.
Passing the strict oracle requires the intended whole-fragment correspondence,
positional coverage, text validation, and the expected srcMove classification:
`exact` for Type-1 and `type2` for Type-2. Report wrong-classification outcomes
separately when they occur, but do not count them as passes.

A later negative-case evaluation derived from BigCloneBench's known
false-positive pairs must be reported separately. Its results must not be mixed
into the current positive-case pass rate.

Report an end-to-end rate over generated cases and a conditional srcMove rate
over cases where srcDiff exposed the intended candidate regions. A valid XML
document that aligned away or otherwise failed to expose the payload is an
upstream semantic-ineligibility outcome, not a srcMove miss.

The selection manifest must preserve the BigCloneBench database checksum, H2 and
Java identities, exact query and parameters, ordered selected row identifiers,
selected source-file checksums, extraction/decoding policy, generator checksum,
and oracle checksum. If cases are directed from fragment one to fragment two,
say so; if direction is intended to be irrelevant, canonicalize or evaluate both
directions. Results used during algorithm tuning remain labeled as tuning data
and are not silently reused as a held-out thesis evaluation.

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
- paired, interleaved revision execution with a recorded randomization seed
- host and container resource identity and measurement-tool versions

Use a recorded paired/interleaved schedule so one revision is not always favored
by warm caches, thermal state, or run order. Cache policy must be controlled or
recorded. Report raw observations and at least median plus an explicit dispersion
measure such as IQR or MAD. Performance failures and timeouts remain rows in the
raw dataset instead of disappearing from summaries; exclusions and censored
measurements must be counted.

## Implementation Phases

### Phase 0: Freeze the current baseline and contracts

- Inventory current runner interfaces, ignored output locations, and historical
  result archives without treating old large-run counts as current expectations
  or making their formats a compatibility requirement.
- Add tiny checked-in source/srcDiff fixtures and fake executables for the
  orchestration outcomes in the testing strategy.
- Freeze the initial status vocabulary, identity rules, and dataset-adapter
  boundary before moving outputs.
- Preserve the current strict BigCloneBench oracle, including the Type-1 to
  `exact` and Type-2 to `type2` classification requirements, while characterizing
  its existing outputs before moving them.
- Record that BigCloneBench is an external manual prerequisite; preflight may
  explain its absence but must not download it.

**Complete when:** the legacy commands and historical artifacts are identified,
the refactored code has a tiny offline characterization path, and no acceptance
criterion depends on an unavailable large dataset or a pre-refactor pass count.
The frozen oracle contract must retain both whole-fragment detection and correct
srcMove classification as pass requirements.

### Phase 1: Minimum provenance foundation

- Define only the versioned observed-state and build-receipt core plus the shared
  identifiers/status fields needed by the first vertical slice. Add later schema
  fields with the phase that consumes them rather than designing unused formats.
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

### Phase 2: Safe staged corpus vertical slice

- Implement one generic preparation/attempt/corpus/run core and a repository
  adapter; do not create dataset-specific orchestration paths.
- Split repository preparation, srcDiff corpus generation, and srcMove execution.
- Define the minimum preparation, attempt, corpus, and run schemas as their first
  real artifacts are implemented.
- Run each srcDiff attempt in a unique staging directory.
- Implement the process execution contract, including timeout cleanup, bounded
  logs, termination fields, structural XML admission, and interrupted-attempt
  recovery, before accepting any corpus output.
- Retain stdout, stderr, partial-output metadata, the exact command, elapsed time,
  and a terminal attempt record even when srcDiff fails.
- Validate and checksum successful XML, then atomically promote it into an
  immutable corpus case.
- Make prepared srcDiff XML reusable by checksum and preserve prior runs.
- Treat that reuse as a guarantee within the current schema and oracle contract,
  not across breaking benchmark-infrastructure changes.
- Allow selection of an existing corpus without requiring source repositories or
  srcDiff at srcMove execution time.

**Complete when:** srcMove can be rerun or compared across revisions without
rerunning srcDiff, every srcDiff invocation has one terminal attempt record, and
no missing, partial, malformed, timed-out, signaled, or nonzero-exit output can
appear as a corpus case. Hiding the source repositories and `srcdiff` executable
after corpus creation must not break srcMove replay.

### Phase 3: Resumability and srcDiff investigation tooling

- Replace implicit Python deletion with a manifest-recorded filter.
- Continue batches after failures and support resume/retry selection.
- Use the attempt parent/ordinal lineage to retry without overwriting earlier
  evidence.
- Extend resource-exhaustion detection and peak-memory reporting where the
  environment supports them.
- Add single-file replay and archive-subset isolation tooling.
- Make network refresh explicit and support offline reuse of cached repository
  preparations and corpora.

**Complete when:** interrupted or partially failing batches resume without
repeating completed work or losing evidence, and a failed repository case can be
replayed or reduced from its preserved attempt record.

### Phase 4: Targeted BigCloneBench reproducibility integration

Begin this phase only after the repository benchmark has established the shared
preparation, corpus, provenance, and srcDiff failure-handling infrastructure.
BigCloneBench should adapt that foundation rather than create a second runner
architecture.

Retain the current generator, deduplication policy, position/text validation,
and strict Type-1/Type-2 classification oracle unless a separately justified
methodology change is made. This phase adapts a successful benchmark to shared
corpus, failure-handling, provenance, and append-only reporting infrastructure;
it is not a new benchmark design.

- Add a clear preflight error and setup guidance when BigCloneBench is absent.
- Separate case generation, srcDiff corpus generation, and srcMove evaluation.
- Add a semantic eligibility check that verifies srcDiff exposed the intended
  synthetic payload as usable delete/insert regions before attributing an
  outcome to srcMove.
- Preserve the strict oracle requiring Type-1 cases to report `exact` and Type-2
  cases to report `type2`; retain wrong-classification outcomes as diagnostics
  rather than passes.
- Store each run summary under its run identifier instead of overwriting one
  shared `summary.csv`.
- Define the eligible population, pair direction, census or sampling method,
  tuning/evaluation split, and selection-manifest fields before reporting a rate.
- Preserve reproducible selection and version the positional/text and srcDiff
  semantic-eligibility oracles.
- Report the strict synthetic positive-case detection-and-classification rate
  and strata with tool failures separated from misses.
- Report wrong classifications, questionable source ranges, unsupported
  variations, and conversion artifacts clearly enough to support thesis failure
  analysis without silently changing the selected population.
- Preserve BigCloneBench's known false-positive pairs as a documented future
  negative-case source; do not make their conversion a prerequisite for the
  positive-case integration.

**Infrastructure complete when:** tiny fixture-backed tests prove that the same
generated corpus can evaluate multiple srcMove builds with immutable manifests,
reconciled counts, and separate upstream failure, srcDiff semantic-ineligibility,
srcMove miss, wrong-classification, and oracle-pass outcomes. The fixtures must
also prove that detecting the intended payload with the wrong match kind remains
diagnostic evidence but fails the strict oracle.

**Dataset validation complete when:** an explicitly installed and checksummed
BigCloneBench distribution passes preflight, Type-1 is evaluated first under a
frozen selection/oracle specification, and Type-2 is enabled only after the
Type-1 pipeline and reporting are accepted. This validation is a deliberate
external run, not part of ordinary implementation testing.

### Phase 5: Performance measurement

- Extend the current internal profiler runner rather than creating a competing
  timing path.
- Add external wall/CPU time, peak memory, workload sizes, warmups, and repeated
  measurements.
- Generate a recorded paired/interleaved schedule with a reproducible seed when
  comparing revisions.
- Produce raw CSV or JSON rows plus a machine-readable summary.

**Complete when:** two srcMove revisions can be fairly compared on identical
input checksums, neither revision always runs first, environment and cache policy
are recorded, failures remain raw rows, and the comparison can be reproduced
from its manifest.

### Phase 6: Publication workflow

- Add explicit strict validation for clean source, receipts, checksums, tests,
  Release configuration, and immutable output.
- Build or reuse verified artifacts in isolation from active development.
- Generate a compact thesis archive containing manifests, summaries, and the
  checksums/locations of large external artifacts.
- Add an archive-verification command that validates schemas, checksums,
  provenance status, count reconciliation, and external-artifact references
  without consulting mutable `latest` paths.

**Complete when:** one command can either produce a self-describing thesis run
or stop before measurement with a precise unmet precondition, and a second clean
environment can verify the resulting compact archive.

### Phase 7: Scale progression

Increase scale only after the preceding layers are reliable:

1. tiny hand-authored and generated smoke cases
2. zlib or Notepad++ repository pair
3. srcMove, SQLite, or similar medium repositories
4. small BigCloneBench Type-1 sample after its external prerequisite is installed
5. larger BigCloneBench Type-1, then Type-2, slices
6. OpenCV or a Linux subsystem
7. two exact full Linux kernel revisions

Each tier should establish expected runtime, storage, and failure behavior before
advancing. Full-kernel execution is a final scale target, not the first test of
the infrastructure. Before running a tier, declare its case count, timeout and
storage budgets, and acceptable failure classes. Advance only after all counts
reconcile, replay succeeds, and no unexplained orchestration failure remains;
expected tool limitations may remain when they are classified and reported.

## Testing Strategy for the Infrastructure

Use fake executables and tiny fixtures to test orchestration without invoking
the real toolchain. Cover:

- successful output
- nonzero exit and terminating signal
- timeout with graceful termination and forced process-group cleanup
- distinct exit-code, signal, timeout, spawn-failure, and interrupted-attempt
  records
- missing, empty, structurally invalid, malformed, and truncated XML
- partial output
- stale staging output and interrupted-staging recovery
- stdout/stderr truncation with correct byte counts and checksums
- retry lineage and preservation of the original attempt
- `SIGKILL` without OOM evidence classified as `unknown_resource_failure`
- stale build receipt or input checksum
- executable without a build-time receipt
- current checkout differing from a valid older build receipt
- dirty development provenance
- strict publication rejection
- interrupted batch resume
- preservation of earlier run directories
- identical content producing the same preparation/corpus identity after moving
  the generated root
- an identity-changing input producing a different identifier
- srcMove corpus replay with source repositories and `srcdiff` unavailable
- exact reconciliation of selected, excluded, failed, eligible, executed, and
  scored counts
- strict BigCloneBench oracle enforcement, including detection of the intended
  payload and the expected Type-1/`exact` or Type-2/`type2` classification
- reproducible paired/interleaved performance ordering

Keep a small real integration case for srcDiff-to-srcMove behavior. BigCloneBench
and repository-scale data remain outside the deterministic default test suite.

## Cross-Phase Acceptance Invariants

These conditions apply throughout implementation rather than belonging to one
late publication phase:

- Every process invocation has exactly one recoverable terminal attempt record.
- Only structurally admitted, checksummed srcDiff output appears in a corpus.
- Prepared inputs, accepted corpus data, and run results are immutable once
  referenced by a completed manifest.
- All generated identifiers follow one documented canonicalization algorithm and
  are independent of absolute paths and timestamps.
- Every aggregate reconciles to raw rows; failures, exclusions, and semantic
  ineligibility never disappear from the denominator accounting.
- Dataset adapters add metadata and semantic validation but use the shared
  execution, provenance, storage, and reporting core.
- Development mode does not fetch, switch, clean, rebuild, or modify sibling
  repositories implicitly.
- Publication output contains immutable provenance snapshots and verifies without
  a mutable workspace lock, current checkout, or `latest` result.

## Risks and Mitigations

- **Sampling bias:** ordered first-N BigCloneBench rows can overrepresent repeated
  functionality. Use a declared census or seeded stratified sample and report
  distinct text-pair and functionality coverage.
- **Benchmark overfitting:** promoting failures into regressions can tune srcMove
  to the evaluation set. Label tuning cases and freeze a separate evaluation
  census or sample before the thesis run.
- **srcDiff confounding:** valid XML may omit the intended candidate. Preserve
  end-to-end and conditional srcMove results with semantic eligibility explicit.
- **Timeout censoring:** timeouts can make a faster tool appear more reliable or
  remove hard cases from summaries. Preserve them as rows and report the timeout
  policy and censored count.
- **Schema or oracle drift:** changed validators can alter results without a code
  change. Follow the [forward-only compatibility policy](#benchmark-compatibility-policy),
  then rerun measurements under one declared contract before comparing them.
- **Dataset and conversion limitations:** BigCloneBench is the best available
  large labeled source for this evaluation, but individual labels, extracted
  ranges, unsupported variations, or synthetic wrappers may contribute to
  failures. Preserve the strict declared oracle and selected population, inspect
  failures, and report credible dataset or conversion limitations in the thesis
  instead of silently excluding them.
- **Measurement bias:** fixed revision order, cache warmth, host load, and thermal
  state can distort comparisons. Use paired/interleaved ordering and record the
  environment and cache policy.
- **Storage and corruption:** XML corpora and partial outputs can be large. Use
  checksums, atomic writes, explicit retention, optional transparent compression,
  and a verification command before reuse.
- **Licensing and redistribution:** repository exports and BigCloneBench data may
  not be suitable for a thesis archive. Archive manifests, checksums, acquisition
  instructions, and permitted artifacts rather than assuming sources can be
  redistributed.
- **False provenance confidence:** a nearby clean checkout does not identify a
  binary's source. Require build-time receipts for verified claims and label
  everything else honestly.
- **External-tool concurrency:** BigCloneBench H2 access and large repository runs
  may have locking or resource contention. Serialize constrained stages and
  record any configured concurrency.

## Decisions to Resolve During Implementation

- final schema representation, canonical identity encoding, and generated-data
  root name
- compression policy for large srcDiff XML and transparent replay
- attempt, preparation, corpus, and run retention/garbage-collection policy
- portable peak-memory collection inside the supported Docker environment
- whether development runs store a patch or only its hash by default
- prepared-source retention, licensing boundaries, corpus distribution, and
  archival location for thesis reproducibility
- BigCloneBench census or sampling frame, pair direction, randomization seed,
  strata, and tuning/evaluation separation
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
