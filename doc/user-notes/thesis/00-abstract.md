# Abstract

> **Provisional draft.** This abstract must be revised after the evaluation is
> frozen. Bracketed markers identify results and scope decisions that must not
> be inferred from exploratory runs.

Source-code differencing tools can represent a relocated program construct as
an unrelated deletion and insertion, obscuring a relationship that is useful
when reviewing, understanding, or studying software changes. This thesis
introduces **srcMove**, a deterministic C++ post-processor that recovers move
relationships from the structured source representation already embedded in
srcDiff XML. srcMove selects statement-or-larger structural candidates,
constructs canonical representations, and classifies accepted deletion and
insertion relationships as exact, consistently normalized Type-2, or bounded
Type-3 matches. It supports archive inputs so that relationships may cross file
boundaries, and it preserves the srcDiff document while adding shared move
identifiers and directional XPath links. The work also contributes
**BigMoveBench**, a reproducible evaluation pipeline that converts labeled
BigCloneBench fragment pairs into controlled cross-file move cases while
separating srcDiff candidate exposure from srcMove detection and
classification. On the frozen evaluation population, srcMove achieved
**[RESULT NEEDED: end-to-end and conditional detection/classification results,
split by match type and with denominators]**. In a separate whole-fragment
rejection experiment, it rejected **[RESULT NEEDED: count/rate and exact
known-false-positive population]**. Performance experiments measured
**[RESULT NEEDED: principal runtime, memory, throughput, or scaling result on a
named workload and environment]**. An observational repository-history tool
examines detected moves across adjacent revisions, and the companion
**srcVisual** system presents the annotated XML, source, tree, diff, and
directional move views in a synchronized interface. These artifacts support the
claim that structured srcDiff output can be post-processed to recover useful
syntactic move relationships without replacing the underlying differencing
engine; the final claim must remain limited to the evaluated candidate classes,
languages, workloads, and oracles.

## Finalization checklist

- TODO: Replace every result marker from frozen, publication-labeled manifests.
- TODO: State the evaluated Type-1, Type-2, and Type-3 populations exactly; do
  not imply support beyond the final experiment.
- TODO: Include the distinction between generated cases and srcDiff-eligible
  cases in the final result wording.
- TODO: Decide whether the repository-history observation is important enough
  to retain in the abstract.
- TODO: Verify the university's word limit and required keyword format.
