# Chapter 7: srcMove History

> Draft status: first-pass thesis prose. Architecture and runtime descriptions
> reflect the documented implementation as reviewed on September 15, 2026.
> The repository study and endpoint contrast remain proposed; this chapter does
> not contain empirical results yet.

## 7.1 Contribution and research question

BigMoveBench asks whether srcMove can recover a controlled, labeled
relationship. srcMove History asks a different question: what move evidence
does the tool produce when it is applied at the revisions where changes occur
in real repositories? The first question requires a benchmark oracle. The
second requires a reproducible longitudinal execution and evidence model.

srcMove History is the production component that supplies that model. It
freezes a repository analysis definition, walks adjacent commits, executes
srcDiff and srcMove over each relevant change, and stores normalized outcomes
in SQLite. It is not part of the core `srcMove` matching pipeline, and it does
not change the detector's classification rules. Its contribution is to make
history-scale application of that detector bounded, recoverable, inspectable,
and reproducible.

This chapter addresses three questions:

1. How can srcDiff and srcMove be executed reproducibly over adjacent commit
   pairs?
2. What move evidence is observed in selected real repository histories?
3. What evidence is visible in adjacent revisions but absent from a comparison
   between the endpoints of a longer change window?

The latter two are observational questions. A Git history records versions and
developer commit boundaries, not a complete ground-truth label for every code
move. Consequently, this chapter reports detections and manually reviewed
examples, not general precision or recall.

## 7.2 Why analysis must follow history

A move is easiest to detect when the deleted and inserted regions still
resemble one another. Consider three revisions: a function exists in file A;
the function is moved to file B; then its implementation is substantially
modified. Comparing the first and third revisions may expose a deletion and an
insertion with too little remaining similarity for srcMove to link. Comparing
the adjacent revisions can preserve the evidence at the moment of relocation.

This example does not imply that adjacent comparison always detects more moves.
Commit boundaries may combine unrelated edits, split one logical refactoring
across several revisions, or temporarily place the program in an intermediate
state. Instead, it establishes that an endpoint comparison and a sequence of
adjacent comparisons answer different questions. srcMove History treats
adjacent first-parent edges as the normal unit of longitudinal observation and
provides explicit endpoint comparison as a contrast.

**Literature task:** relate this motivation to empirical studies of software
evolution, refactoring histories, and commit-based mining. Add primary sources
and distinguish their definitions of move or refactoring from srcMove's
structured detector output.

## 7.3 Analysis architecture

The analyzer separates command presentation, coordination, pair execution,
persistence, and reporting. A CLI or benchmark adapter requests a target from
an analysis coordinator. The coordinator freezes bounded work, dispatches
commit pairs through a bounded worker pool, and publishes normalized outcomes
through a single transactional SQLite authority. Query services read the same
database for status, reports, pair lists, and detailed evidence; they do not
schedule work.

Each worker receives one complete old/new commit edge rather than one file.
The worker inventories changed paths, materializes the relevant old and new
trees, invokes srcDiff in archive mode, validates its archive XML, invokes
srcMove, and normalizes the outcome. Keeping every relevant path in the same
work item is necessary for cross-file detection. Splitting the edge into
independent per-file comparisons would remove the context needed to relate a
deletion in one file to an insertion in another.

Modified files appear on both materialized sides, additions only on the new
side, deletions only on the old side, and renames retain their old and new
paths. Path admission follows srcML's recognized, case-sensitive extensions
and then applies the analysis's configured exclusions. Unsupported extensions,
symlinks, submodules, and other unsupported Git modes remain observable as
path-exclusion counts rather than being silently treated as analyzed source.
A pair with no analyzable path receives a terminal
`no_analyzable_change` outcome without running srcDiff.

> **Figure 7.1 placeholder — analyzer data flow.** Show target selection,
> first-parent pair planning, the bounded queue and private worker scratch,
> Git/srcDiff/srcMove execution, ordered publication, and the single SQLite
> writer. Distinguish disposable scratch and optional retained comparison
> artifacts from authoritative database state.

## 7.4 Immutable analysis and identity model

An analysis represents one immutable study definition with coverage that can
grow toward older history. The definition includes repository identity, the
frozen newest commit, traversal and retention policies, source scope,
configuration, executable identities, and schema versions. The exact srcDiff
and srcMove executable bytes are copied into an analysis-owned,
content-addressed store when the analysis is created. Their SHA-256 digests and
sizes are revalidated at subsequent runs. Replacing an executable at its
original path therefore cannot silently alter later results in the same
analysis.

The durable model distinguishes an analysis, command invocation, bounded batch,
adjacent commit pair, terminal pair outcome, and normalized move evidence. A
pair is identified by its ordered old and new commits and by a stable distance
from the frozen newest revision. Extending the analysis toward older commits
does not renumber existing pairs. Each covered pair has one immutable terminal
outcome in that analysis. Comparing another detector build or configuration
requires a separate analysis rather than overwriting prior evidence.

SQLite is the only authoritative saved state. JSON, human-readable reports,
and future tabular exports are derived views. Successful pair outcomes retain
compact move evidence: metrics, match kind, source and destination XPath
arrays, hashes and UTF-8 lengths for moved raw-text regions, and an observation
of the results file. Full successful XML and source trees are not retained by
the normal history run. Failures retain termination and resource observations,
bounded output samples, and whole-stream lengths and hashes. This design keeps
large studies inspectable without treating disposable intermediate artifacts
as a second result database.

## 7.5 Target-driven execution and recovery

The public `run` lifecycle creates an analysis, resumes interrupted work, or
extends coverage. A requested target can be an absolute pair count, an
additional number of pairs beyond the current frontier, a full immutable commit
through which to analyze, or the repository root. Repeating a satisfied target
verifies the existing state and performs no pair execution. The newest anchor
is frozen, so later movement of a branch does not change the meaning of the
study.

Work is divided into bounded batches independently of the final target. Work
and completion queues are bounded by worker count, and each worker owns private
scratch. Pair execution may finish out of order, but publication advances in a
contiguous sequence. The durable protocol is:

1. freeze a pending batch in one transaction;
2. publish each terminal pair outcome in its own transaction; and
3. commit the batch and advance the history frontier after all its pairs are
   terminal.

A process failure before a pair publication leaves that pair pending. A later
invocation resumes the exact batch and does not recompute its already published
terminal prefix. Scratch data can therefore be removed after interruption
without losing authoritative progress. One nonblocking operation lock prevents
two writers from mutating the same analysis simultaneously, while read-only
status, list, and show operations use consistent snapshots.

Terminal pair outcomes distinguish successful comparison, no analyzable
change, export failure, srcDiff failure, srcMove failure, and orchestration
failure. A tool failure is still a covered observation and is not rerun by
repeating the same target. This rule is important to interpreting study totals:
"covered," "successfully compared," "without analyzable changes," and
"failed" are different populations.

## 7.6 Browsing, reporting, and endpoint comparison

The current CLI provides `init`, `run`, `status`, `report`, `list`, `show`, and
`compare`. `status` separates durable coverage from outcomes and derives live
writer state by probing the operation lock. `report` produces a deterministic
research summary from committed results, including coverage, outcome totals,
move prevalence, classification, file location, topology, distributions,
performance totals, exclusions, and the frozen analysis definition. `list`
and `show` expose stable pair identities and load detailed evidence lazily.

`compare COMMIT` analyzes one commit against its first parent, while
`compare OLD NEW` analyzes an explicit pair. `compare --pair PAIR` regenerates
artifacts for a pair selected from the canonical history database. These
commands use the analysis's frozen configuration and admitted executables but
do not publish coverage, outcomes, or move evidence back into SQLite. Optional
saved artifacts therefore support inspection without mutating the study.

The export of stable CSV or JSONL research tables, read-only preflight, Git-diff
inspection, and `status --watch` remain planned interface work as documented in
the CLI plan. They must not be described in the final thesis as current
features unless implemented in the frozen revision. The existing report and
database query interfaces are sufficient to design the study, but the final
replication package should use a versioned export rather than undocumented SQL
if that interface becomes available in time.

## 7.7 Repository-history study design

The history study must freeze its selection procedure before results or
illustrative examples are chosen. For each repository, record:

- repository URL and immutable newest commit;
- rationale for project inclusion;
- exact first-parent window or target count;
- language and configured suffix exclusions;
- merge treatment implied by first-parent traversal;
- srcDiff and srcMove executable digests;
- srcMove History revision and database schema version;
- worker count, timeout configuration, retention policy, and environment; and
- the procedure for failures and manual review.

The primary unit is an adjacent commit pair. Report the number covered, the
number successfully compared, the number without analyzable changes, and the
number failed before presenting move prevalence. Percentages of detections
should use successfully compared pairs as the denominator unless another
denominator is explicitly named. Path exclusions are observations across pairs,
not necessarily unique repository paths.

For successful comparisons, candidate descriptive measures include detected
move groups, source/destination pairings, annotated regions, match kind,
within-file versus cross-file location, move-group cardinality, moved-region
size, and moved-region share. Counts should also be normalized by an explicit
measure of change volume so that a larger or more active project is not
interpreted as intrinsically more move-prone merely because it supplies more
opportunities. Per-repository distributions must remain visible rather than
being replaced by one pooled total.

> **Study-definition placeholder.** Insert the final repository table with full
> commit IDs, pair windows, exclusions, tool digests, failure policy, and review
> sample. The current chapter intentionally does not nominate projects or
> sample sizes without the frozen study protocol.

## 7.8 Endpoint-versus-history contrast

The endpoint contrast should use a small set of commit windows selected by a
declared rule. For each window, compare the union of detections observed across
its adjacent first-parent pairs with one explicit comparison between the
window's oldest and newest endpoints. Preserve the results and annotated XML
for the endpoint comparison, and trace every adjacent detection back to its
canonical pair evidence.

The contrast should report at least four categories: observed in both views,
observed only in adjacent history, observed only in the endpoint comparison,
and not directly comparable because the represented regions changed identity
or granularity. Manually reviewed examples can explain how later editing,
intermediate changes, or detector behavior produced a difference. Example
selection must not simply choose the most persuasive cases after reading the
results; use a predetermined rule such as stratified sampling by category and
move kind.

This experiment is not a recall comparison. Neither view is a complete oracle,
and the union of adjacent detections is still detector output. The defensible
claim is narrower: the two analysis strategies expose different observable
evidence, and selected cases can demonstrate why the time at which comparison
occurs matters.

## 7.9 Results

No repository-history results are asserted in this draft.

> **Results placeholder A — coverage and outcomes.** For every repository,
> report covered, successfully compared, no-analyzable-change, and failed pairs,
> with failure reasons and path exclusions.

> **Results placeholder B — observed moves.** Report per-project distributions
> and normalized rates for move detections, match kinds, region counts,
> within/cross-file locations, cardinality, and sizes. Include uncertainty or
> dispersion appropriate to the descriptive measure; do not present pooled
> totals alone.

> **Results placeholder C — endpoint contrast.** Report the frozen window set,
> the four comparison categories, and manually reviewed cases selected by the
> declared protocol. Label every count as detector output unless independently
> validated.

The narrative should keep failures visible. A repository with fewer observed
moves may have fewer eligible changes, more excluded paths, or more srcDiff
failures; it is not enough to compare raw detection totals.

## 7.10 Threats to validity and limitations

Repository history does not provide a complete oracle for code moves. Commit
structure reflects developer practice: changes may be squashed, reordered,
mixed with unrelated edits, or split over several revisions. First-parent
traversal provides a deterministic linear history but does not analyze every
side-branch edge, and merge commits require careful interpretation.

Project and window selection limit external validity. Language mix, coding
style, refactoring practice, repository age, and generated code policies can
all affect the opportunity to observe moves. File renames, unsupported Git
modes, excluded suffixes, and tool failures create missing or altered
observations. Later modifications can obscure earlier moves even across short
windows, while one large mechanical commit can dominate aggregate counts.

The analysis also inherits srcDiff and srcMove's definitions and failure modes.
Normalized evidence makes those outputs reproducible but does not independently
validate them. Manual review introduces reviewer judgment and must report its
sampling, instructions, and agreement procedure if more than one reviewer is
used. These constraints require the chapter to use terms such as "detected" or
"observed" rather than treating every stored move as historical fact.

## Evidence still required

- [ ] Add primary literature on repository mining and longitudinal refactoring
  analysis.
- [ ] Freeze the repository/window selection protocol and full commit IDs.
- [ ] Record environment, configuration, and tool digests.
- [ ] Define the change-volume normalization used in cross-project tables.
- [ ] Define and execute the manual-review protocol.
- [ ] Run and retain the adjacent-history study.
- [ ] Run the endpoint contrast with a predeclared selection procedure.
- [ ] Replace all results placeholders with versioned artifacts.

Current behavior is defined by the
[srcMove History documentation](../../../srcmove_history/docs/README.md), with
the [runtime contract](../../../srcmove_history/docs/runtime.md) authoritative
for implemented behavior.
