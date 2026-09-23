# Abstract

> **Provisional draft.** This abstract must be revised after the evaluation is
> frozen. Bracketed markers identify results and scope decisions that must not
> be inferred from exploratory runs.


## Summary / things I want to Include
- Summary of srcMove
- Summary of bigMoveBench + results
- Summary of srcMove-history for historical analysis + results
- Summary of srcVisual

## Abstract

Source-code differencing tools can represent a relocated program construct as
an unrelated deletion and insertion, obscuring a relationship that is useful
when reviewing, understanding, or studying software changes. This thesis
introduces **srcMove**, a deterministic C++ post-processor that recovers move
relationships from the structured source representation already embedded in
srcDiff XML. 

#### Note: Fix. confusing
The thesis proposes a general Type-1 through Type-4 taxonomy that
classifies how source fragments change while relocating and separates
transformation type from granularity, spatial scope, cardinality, operation,
temporal scope, and evidence. srcMove operationalizes the first three types by
selecting statement-or-larger structural candidates,
constructs canonical representations, and classifies accepted deletion and
insertion relationships as exact, consistently normalized Type-2, or bounded
Type-3 matches. 

It supports archive inputs so that relationships may cross file
boundaries, and it preserves the srcDiff document while adding shared move
identifiers and directional XPath links. 

The work also contributes
**BigMoveBench**, a reproducible evaluation pipeline that converts labeled
BigCloneBench fragment pairs into controlled cross-file move cases while
separating srcDiff candidate exposure from srcMove detection and
classification. On the frozen evaluation population, srcMove achieved
**[RESULT NEEDED: end-to-end and conditional detection/classification results,
split by match type and with denominators]**. In a separate whole-fragment
rejection experiment, it rejected **[RESULT NEEDED: count/rate and exact
known-false-positive population]**. Performance experiments measured
**[RESULT NEEDED: principal runtime, memory, throughput, or scaling result on a
named workload and environment]**. 

An observational repository-history tool
examines detected moves across adjacent revisions, and the companion
**srcVisual** system presents the annotated XML, source, tree, diff, and
directional move views in a synchronized interface. These artifacts support the
claim that structured srcDiff output can be post-processed to recover useful
syntactic move relationships without replacing the underlying differencing
engine; the final claim must remain limited to the evaluated candidate classes,
languages, workloads, and oracles.


srcVisual, is a custom made GUI editor developed to  gg

