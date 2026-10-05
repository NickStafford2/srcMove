# srcMove History analysis engine plan

Status: proposed; no implementation is authorized by this document.
Prepared and revised 2026-10-05 following two independent adversarial reviews.

## Objective and scope

Add a reproducible descriptive-analysis layer to `srcmove_history` that turns
stored detector observations into summaries, history series, concentration
measures, and inspection candidates. srcDiffVisual consumes the public JSON
interface; thesis figures can consume the same results from frozen evidence.

Prioritize a small usable milestone for thesis work. Do not build a generic
plugin engine, rerun detection for statistics, introduce a second evidence
store, or infer precision, recall, developer intent, or causal explanations
from detector activity. Formal similarity clustering, fragment lineage,
calendar analysis, and cross-analysis comparisons are later decision gates.

## Existing foundation

Implementation references, not a new description of current behavior:

- [`report.py`](../../srcmove_history/report.py): committed-batch summaries,
  distributions, content/location counts, timing, and limited Git enrichment.
- [`queries.py`](../../srcmove_history/queries.py): immutable read models;
  status/list/show include durable observations from pending batch checkpoints.
- [`compact.py`](../../srcmove_history/compact.py): compact outcomes, move
  endpoints, raw-text hashes and byte sizes; raw source is not retained here.
- [`snapshot.py`](../../srcmove_history/snapshot.py): checksummed portable ZIPs,
  definition/status, pair JSON Lines, report, and optional verified comparisons.
- [Data model](../../srcmove_history/docs/data_model.md),
  [runtime](../../srcmove_history/docs/runtime.md), and
  [architecture](../../srcmove_history/docs/architecture.md): current contracts.

Verified in the current checkout: `results.py` requires admitted schema-2
`move_count == move_group_count == len(moves)`. `report.py` already uses
nearest-rank p95. Empty report mean/median/p95 currently return zero; the proposed
JSON contract returns null for undefined statistics. Preserve existing report
presentation through an explicit compatibility adapter. Recheck these admission
invariants during implementation; reject corrupt or unsupported inputs.

## Proposed architecture

```text
Live SQLite consistent read / integrity-checked evidence ZIP
    -> validated immutable analytical observations
    -> pure metric calculations
    -> versioned result document
    -> CLI JSON / existing report renderer / srcDiffVisual
```

Keep the implementation inside srcMove History. Start with one analysis module
and explicit dataclasses; split modules when reader, calculation, and output
boundaries actually require it. Do not introduce registries or dynamic plugins.
Database SQL belongs to an internal reader, never to srcDiffVisual or calculators.
Both live and snapshot adapters supply the same normalized records.

Proposed public command spelling, subject to implementation review:

```text
srcmove-history -C REPOSITORY statistics --format json
srcmove-history -C REPOSITORY statistics --section activity --window 10 --format json
srcmove-history statistics --snapshot EVIDENCE.zip --format json
```

`statistics` describes existing detections; the existing analysis lifecycle
continues to own repository execution. Do not overload extension commands.

## Evidence and consistency

Reuse `AnalysisDatabase.read_snapshot()` to capture the immutable definition,
minimal scalar pair records, coverage, and identity in one SQLite read transaction.
First-stage metrics do not need move rows, endpoint bodies, or failure captures.
Materialize these records before calculation and formatting. Use SQLite read-only
mode without tool admission, Git context, writes, or an application writer lock;
normal SQLite reader locking can still apply. Do not combine independently
paginated reads into a purported consistent snapshot.

First milestone supports only `committed`: completed batches, matching current
report coverage. Explicitly label included coverage and the frozen newest/oldest
pair range; no checkpointed pair contributes. Result identity includes mode and
all included pair identities, not just the pair count. A captured result remains
immutable even if an extension completes while calculation runs.

Defer optional `durable` coverage. Existing snapshots reject pending batches,
so they cannot reproduce that mode. Before adding it, define checkpoint admission,
promotion identity, partial-outcome visibility, and UI labels. Promotion changes
coverage provenance but should not alter a content digest of unchanged
observations; coverage mode remains part of result identity.

Snapshot mode checks the manifest and every consumed member checksum, schema
versions, pair identity uniqueness, definition association, count consistency,
and ordering. Existing snapshots contain the initial manifest, not every later
batch manifest. Validate the frozen newest anchor, `number = distance + 1`,
adjacent old/new commit continuity across the included prefix, overlap with the
initial commit sequence where present, and recomputed pair fingerprints using
`inputs.py`'s shared helpers. Do not require extended pairs to appear in the
initial manifest. Reject unsupported/inconsistent evidence instead of supplying
zeros. Require the selected committed frontier to be contiguous and anchored:
absent records or duplicate distances are corruption, not merely graph gaps.
Terminal failures/no-source records remain explicit null measurements. Future
range exclusions require their own explicit selection contract.

Snapshot parsing must bypass live CLI repository discovery/admission and the
filesystem-resolving manifest loader. Dispatch `statistics --snapshot` before
`_repository_and_analysis()`; reject conflicting live options. Parse portable
records independently, reusing pure fingerprint helpers. It must work from an
empty directory without the repository, native binaries, or Git access.
Do not use `report.txt` as an input to calculations.

Read ZIP members directly without extraction. Verify required member inventory,
schema versions, definition hash, recomputed snapshot ID, and consumed member
checksums; reject duplicate archive members and duplicate JSON keys. Stream
`pairs.jsonl`, validate each record, then retain only fields needed by the selected
sections. Apply configurable limits before allocation/decompression: proposed
initial ceilings are 512 MiB total expanded bytes and 16 MiB per JSON record,
subject to the early measured performance gate. Reject excessive sizes rather
than returning partial metrics. Name exactly which members were verified; optional
XML not consumed by statistics is not automatically validated.

Checksums and fingerprints establish internal consistency, not authenticity.
Someone can edit observations and recompute a manifest. Trusted provenance still
requires a known originating snapshot identity/receipt and separate source review;
do not claim integrity checks independently prove detector execution or accuracy.

Define a versioned identity projection before implementation. For first-stage
metrics, hash repository identity, frozen newest anchor and first-parent ordering
policy, frozen analysis configuration, tool content hashes, contract versions,
and ordered pair number/distance/old/new/fingerprint/status/group-count records.
Include path counts and exclusion counts if the result exposes them. Include
coverage mode; the first projection only admits committed observations.
Do not hash the full manifest or `show` record: repository/executable locators,
invocation IDs, timing/log details, and mount paths are not inputs to these metrics.
Use an explicit hash-domain prefix such as `srcmove-history-statistics-input-v1`,
UTF-8 canonical compact JSON with sorted object keys and integer count fields,
ordered pairs by distance ascending, and an allow-listed field schema. Hash
these exact bytes with SHA-256. Repository/tool locators are excluded; field
selection, encoding, and numerical semantics are part of the projection version.
Execution provenance remains separately available; future timing or endpoint
sections require a versioned input projection covering their actual inputs.

Retain source snapshot ID separately from analytical evidence digest: adding
verified XML can change ZIP identity without changing metric inputs. The canonical
result payload excludes source-specific envelope metadata so live/snapshot parity
compares the same semantic fields. New calculation/input-projection versions
invalidate previous result identities rather than silently reusing them.

## Result contract

Use a versioned JSON envelope with:

- result schema version and calculation version;
- evidence identity, optional snapshot identity, and frozen detector tool hashes;
- normalized parameters: coverage mode, sections, ordering, window, thresholds;
- coverage/outcome counts, exclusions, and warnings about unsupported fields;
- metric results with explicit count unit, denominator, and null/availability;
- contributing pair numbers/fingerprints for ranked results;
- section capability status when evidence does not support a requested metric.

Define a deterministic `result_id` from evidence identity, calculation version,
and normalized parameters. Repeating a request on unchanged inputs produces
identical semantic output. Avoid volatile timestamps in canonical results.
Undefined rates and empty distributions are null with an explanation, not zero.
Use deterministic tie-breaking and JSON serialization. Nonfinite numbers are
invalid. The CLI exits nonzero for unsupported schemas or invalid parameters.

## Metric definitions for the first milestone

Let `C` be successfully compared pairs, `B` those in `C` with positive detected
move-group count, and `M_i` the group count for pair `i`. Preserve failures and
`no_analyzable_change` as separate outcomes. Distributions and concentration are
conditional on successfully compared, analyzable pairs, not all covered commits.
No-source records mean no eligible source changes under the frozen scope;
failures mean detector output is unavailable. Report each outcome fraction.
Busy comparisons may fail disproportionately; missing intervals are not evidence
of inactivity. The anchored first-parent window is a scoped census of observed
history, not a representative sample of all commits or repositories.

1. **Coverage and outcome totals.** Covered, included, successful, no-source,
   and failures by cause. Report path filters and tool identity next to scope.
2. **Count distribution.** Sum, mean, median, nearest-rank p95, and maximum of
   `M_i` over `C`, including successful zeros. Also report `|B| / |C|` and the
   positive-only distribution over `B`, with clearly separate denominators.
3. **Activity series.** One observation per included pair, oldest to newest,
   with stable pair identity, status, group count, and evidence reference.
   Failure/no-source points have null analytical count. Successful zero is zero.
   An unexplained missing pair distance invalidates the input; never compress it
   out silently. Future explicit range exclusions must be represented as gaps.
4. **Rolling means.** Use trailing windows in oldest-to-newest order, ending
   at the current observation. For a window of `w` consecutive pair distances, emit a
   mean only if all `w` observations are successful. Use raw counts before
   display transforms. For a partial or excluded window, return null and its
   coverage counts. The first `w-1` positions are null with reason `range_edge`.
   Include each window's pair range; summarize eligible/full windows, emitted
   windows, and null windows by reason (edge, missing, failure, no-source;
   reasons may overlap). Default window 10; permit 5, 10, and 25 initially.
5. **Concentration.** Sort `C` by count descending; ties use stable pair number.
   For `n = ceil(0.10 * |C|)`, report the sum of the first `n` counts divided by
   total detected groups, plus `n`, population size, actual selected fraction
   `n / |C|`, contributing pairs,
   and number of pairs tied at the cutoff. Describe it as the share in the top
   `n` successful comparisons: rounding can select far more than 10% of a small
   dataset. Rank by count descending, then pair number ascending; select exactly
   `n` even at a tie. Return null if the total is zero. Parameterize the fraction
   explicitly.
6. **Inspection candidates.** Return the top `k` move-bearing pairs by count,
   score/unit, and exact ranking reason. Ties use pair number ascending. These
   are purposeful inspection
   candidates, not a representative sample or an accuracy estimate.

Use existing report conventions where correct; explicitly version any change
such as percentile interpolation versus nearest rank. No silent changes to
existing report output or archived snapshot bytes.

## Later analyses and collection gates

### Endpoint activity

Extract paths using a shared, validated endpoint parser. Do not duplicate
report regexes in new calculations or guess filenames from arbitrary XPaths.
Missing/unparseable paths stay unknown. A group contributes at most once per
source file and once per destination file; directory rollups deduplicate per
group/directory. Report that endpoint incidence totals need not sum to group
counts. Keep within-file, cross-file, and mixed endpoint cases explicit.

### Burst summaries

Start with descriptive highest-count fixed windows or consecutive move-bearing
runs, not a statistical claim of clustering. Choose window size, threshold,
missing-data policy, and treatment of overlapping windows before interpreting
results. Return the contributing pairs and coverage. Exploratory parameter
search is labeled exploratory; do not present its best outcome as a prespecified
thesis test. Inferential clustering requires a separately reviewed hypothesis,
baseline, and evaluation method.

### Metadata and lineage

Current storage does not freeze per-commit subject/date/parent metadata. Calendar
or author analysis requires an explicitly versioned enrichment artifact keyed
by immutable commits, with field definitions and checksum provenance. Do not
silently fetch mutable Git metadata during snapshot calculations.
Raw-text hashes can identify equal observations, but do not establish fragment
continuity across revisions. Defer lineage and similarity clustering until
necessary source/structure features and their validation are specified.

### Dataset comparisons

Require compatible detector/configuration definitions and an explicitly aligned
pair set. Different covered windows or filters are not directly comparable;
show scope differences rather than presenting their rate difference as a tool
improvement. Human review judgments remain separate from detector evidence.

## Updates, performance, and srcDiffVisual integration

Initially recompute requested descriptive sections from compact observations
after extension completion or an explicit refresh. Do not run expensive metric
work in a pair-publication transaction. Freeze each response to its own frontier.
No durable cache or schema migration is required for the first milestone.

Run an early measurement gate after the first live slice: read time, calculation
time, peak memory, and output bytes against representative existing datasets.
Before that gate closes, select documented resource budgets and validate the
proposed ZIP/record ceilings against actual evidence. Section selection controls
output size: summaries/rankings need not emit the whole series. Fail visibly if
an output limit is exceeded. Add bounded series projection only if measurements
justify it; do not silently truncate analytical populations. Avoid caching until
profiling demonstrates a benefit. Bounded series projections may aggregate contiguous bins for large histories; each bin
must carry its actual pair range, coverage, failures, no-source counts, and unit.
Do not aggregate away gaps or mix a bin total with a per-pair rolling mean.

srcDiffVisual adds an allow-listed endpoint that delegates to this CLI and
validates the versioned response. Replace its independent all-page series fetch
only after parity tests establish identical units, order, zeros, and gaps on the
same completed frontier. During extensions, the first engine reports committed
coverage while existing status totals may include checkpoints; the viewer must
label those different scopes explicitly rather than suggest the graph includes
all durable observations. Display the result's coverage and identity, refresh after extensions complete,
and link inspection candidates to existing `show`/comparison workflows.
Y-axis scale is a display choice and does not alter analytical counts or means.

## Implementation sequence and acceptance gates

1. **Contract audit.** Establish admitted count units, percentile semantics,
   committed-frontier behavior, and available compact fields using code and
   fixtures. Write the normalized record/result schemas before implementation.
2. **Small vertical slice.** Live committed reader, totals/distribution/activity,
   deterministic JSON CLI, and tests. Demonstrate no writes and no native calls.
   Run the early resource measurement gate before expanding this slice.
3. **Frozen evidence adapter.** Integrity-check ZIPs; reproduce live committed
   results
   on the same evidence without Git/native tools. Address malformed members,
   duplicate pairs, tampering, and absent capabilities explicitly.
4. **Concentration and ranked inspection.** Add calculations with reference
   fixtures and empty/all-zero/tie cases. Keep sample-selection semantics explicit.
5. **Viewer integration.** Separate srcDiffVisual change with contract/parity,
   refresh, cancellation, and error tests. Preserve existing graphs until parity.
6. **Optional report sharing.** Reuse pure calculations where semantics match;
   preserve existing report enrichment through Git and its presentation rules.
   This is not a first-deliverable dependency. Retain golden compatibility fixtures
   and document intentional versioned differences. Do not replace the report
   wholesale or make the standalone engine depend on Git. Update canonical runtime
   documentation as each public capability becomes implemented.
7. **Performance gate.** Measure before optimizing. Add later metrics individually
   only when evidence and an actual research question justify them.

For thesis urgency, steps 1–4 form the first deliverable; UI polish and endpoint,
burst, calendar, and lineage work can follow independently. Revisit scope after
contract audit rather than assigning a speculative fixed completion date.

## Verification

Use srcMove's existing unit-test fixtures and Docker entry points. Exercise:

- successful zero/positive, no-source, each failure, empty and all-zero evidence;
- trailing alignment (e.g. raw counts `0, 10, failure, 0, 20`), incomplete
  windows, corrupted missing distances, ties, and group/endpoint count differences;
- growing history and a writer publishing while a live read is captured; use
  barriers/events to demonstrate complete old-or-new frontiers, never sleeps;
- standalone snapshot CLI from an empty directory with Git/native tools unavailable;
- archive limits, duplicate ZIP/JSON keys, absent members, verification scope,
  reconstructed fingerprints, and snapshot ID/definition hash validation;
- an independent hand-calculated fixture spanning zero/positive, no-source,
  failures, multi-endpoint groups, ties, and appended history; assert exact units,
  denominators, percentile, concentration, and rolling results before parity;
- live committed versus snapshot parity; unsupported/tampered snapshot inputs;
- deterministic output under changed mounts, repeated runs, and request order;
- parameter validation, finite numbers, explicit unavailable fields;
- current report compatibility and srcDiffVisual contract integration.

Run appropriate srcMove unit targets through the workspace Docker wrapper,
then required checks for changed code. For this documentation-only task, validate
local links and `git diff --check`; do not execute new analyses or modify evidence.

## Adversarial review

Review 1 — evidence/methodology: accepted corrections to the identity projection,
extended-snapshot chain validation, conditional denominators and missingness,
trailing-window alignment and coverage, actual concentration fractions and ties,
independent correctness fixtures, and current admission/percentile facts.

Review 2 — architecture/operations: accepted standalone snapshot dispatch and
pure portable parsing, precise canonical identity encoding, integrity versus
authenticity language, verification scope and resource limits, committed-only
initial scope, minimal projections, early performance measurement, rejection of
unexplained holes, reuse of SQLite snapshot support, barrier-based concurrency
tests, and optional report sharing with preserved Git enrichment.

Deferred by design: durable/checkpointed coverage, general endpoint collection,
formal clustering/lineage/calendar analysis, durable caching, and report redesign.
They have separate evidence or performance gates; they do not block committed
statistics, frozen snapshot parity, or concentration/ranking. Both reviewers
worked independently and read implementation evidence. Their critiques are design
feedback, not experimental results or independent validation of detector accuracy.
