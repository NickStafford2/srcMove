# Chapter 9: Discussion and Threats to Validity

## 9.1 Purpose of this chapter

The preceding chapters examine the thesis contributions separately. srcMove
provides the move-detection mechanism; BigMoveBench provides controlled positive
and negative experiments; srcVisual provides an inspection interface; srcMove
History applies the analysis across repository revisions; and the performance
infrastructure measures the cost of those analyses. This chapter brings those
results together and asks what can—and cannot—be concluded from them.

This draft deliberately avoids inserting conclusions before the publication
runs are frozen. Statements marked `[RESULT NEEDED]` must be replaced with
specific evidence from Chapters 5, 7, or 8. Explanations that remain plausible
but untested should be presented as hypotheses rather than findings.

## 9.2 Interpreting the detection results

srcMove approaches move detection as a sequence of increasingly permissive
syntactic comparisons. Exact canonical matches are considered first, followed
by consistently normalized Type-2 matches and then bounded Type-3 similarity.
This ordering preserves the strongest available explanation for a pair before
attempting a weaker one. It also makes each reported match kind interpretable
in terms of a declared transformation rather than a single opaque confidence
score.

The BigMoveBench results should be interpreted at two boundaries. The
end-to-end result measures whether the complete generated experiment succeeded,
including whether srcDiff exposed usable deletion and insertion regions. The
conditional result measures srcMove only after that eligibility requirement was
satisfied. The first reflects the practical toolchain; the second isolates the
detector more closely. Reporting either one without the other would hide an
important source of failure.

`[RESULT NEEDED: summarize Type-1 detection and classification, including the
eligible-case denominator and the dominant failure classes.]`

`[RESULT NEEDED: summarize Type-2 behavior and distinguish normalization limits
from srcDiff-ineligible inputs.]`

`[RESULT NEEDED: summarize Type-3 results by declared BigCloneBench strength
stratum and explain wrong-kind classifications separately from misses.]`

These experiments do not establish that every accepted match is a historical
move or that every rejected pair is unrelated. They test whether srcMove
recovers the expected complete synthetic relationship under a precisely defined
conversion and oracle. The resulting rates therefore characterize that
experiment, not move detection in all languages, repositories, or development
contexts.

## 9.3 Detection versus developer intent

A source-code move is partly a structural relationship and partly an
interpretation of how a program changed. srcMove establishes the former. It
links a deleted construct to an inserted construct when their canonical or
sequence representations satisfy a declared rule. It does not inspect commit
messages, issue discussions, runtime behavior, or the developer's stated
intent. Even a structurally strong match can be a copy, a repeated idiom, or a
coincidental correspondence.

This distinction explains why the thesis uses terms such as *detected move
group* and *match kind* rather than claiming to reconstruct intent. Group
cardinality adds further ambiguity. A one-to-one group offers a direct
relationship, whereas a many-to-many group may indicate duplication,
consolidation, repetition, or several possible pairings. The shared group is
useful evidence, but it is not a fully disambiguated edit script.

The known-false-positive experiment addresses one part of this problem. It asks
whether srcMove links the complete fragments in pairs that BigCloneBench has
identified as non-clones under the benchmark's review process. A shared child
statement inside those fragments is not necessarily a false move, so the oracle
correctly limits itself to the complete pair. Consequently, the experiment can
support a whole-fragment rejection claim but not a general precision estimate.

`[RESULT NEEDED: report the final complete-pair rejection result, incidental
child-match count, and all eligibility exclusions.]`

## 9.4 The role of srcDiff

srcMove deliberately builds on srcDiff rather than recomputing a base edit
script. This separation allows move annotations to remain compatible with the
srcML ecosystem, but it also establishes a hard input boundary. If srcDiff
aligns a generated example in a way that does not expose the complete deleted
and inserted payloads, srcMove cannot recover that intended relationship from
regions it never receives.

BigMoveBench makes this dependency visible through its eligibility stage. The
same distinction should guide interpretation of real histories. An absence of
srcMove annotations may mean that no qualifying relationship exists, that the
candidate is below the configured granularity, that the matcher rejects it, or
that srcDiff did not expose it as a suitable pair of regions. These explanations
must not be collapsed into one undifferentiated false-negative category.

This boundary also suggests a practical division of future work. Improvements
to candidate exposure belong in srcDiff or in an explicitly documented
preprocessing layer. Improvements to canonicalization, similarity, grouping,
and ambiguity resolution belong in srcMove. Keeping that boundary explicit
prevents evaluation results from being attributed to the wrong component.

## 9.5 What repository history adds

The controlled BigMoveBench experiments and srcMove History answer different
questions. BigMoveBench provides known expected relationships under synthetic
conditions. Repository-history analysis sacrifices a complete oracle in return
for authentic project structure, commit practices, file movement, and change
scale.

Adjacent-pair analysis is especially valuable when a fragment is first moved
and later modified. A distant comparison can miss the original relationship
because the endpoints no longer meet the matching rule. An endpoint-versus-
history contrast can demonstrate this phenomenon through selected examples,
but it cannot measure recall without independent labels for every true move in
the window.

`[RESULT NEEDED: summarize the repositories and commit pairs analyzed, detected
move distributions, cross-file observations, and execution failures.]`

`[RESULT NEEDED: discuss the selected endpoint-versus-history cases and state
the procedure used to select them.]`

Move counts should be normalized by a measure of change volume before projects
are compared. A large repository or unusually active window will naturally
produce more candidates than a small one. Per-project distributions, annotated
region share, moves per changed region, and move-size distributions are more
informative than one pooled total dominated by the largest history.

## 9.6 Performance implications

srcMove's design attempts to keep exact and Type-2 matching away from an
unrestricted deletion-by-insertion Cartesian product. Hash indexes locate
possible groups, full canonical representations confirm equality, and Type-3
comparison is constrained by element kind, size windows, cached sequences, and
early termination. The performance experiments must determine how those choices
behave on the selected workloads rather than treating the design as proof of a
general complexity bound.

`[RESULT NEEDED: identify the dominant srcMove stages, typical variability, peak
memory behavior, and any workload where Type-3 matching becomes material.]`

History scaling introduces different costs. Repository materialization,
filesystem behavior, process startup, srcDiff execution, and write contention
can dominate even when the core srcMove matcher is inexpensive. A measured
scaling knee therefore belongs to the tested repository, commit window,
machine, container allocation, storage location, and program revisions. It
should guide that configuration, not be presented as a universal worker count.

`[RESULT NEEDED: summarize observed speedup, parallel efficiency, and the scoped
scaling knee with its complete environment.]`

## 9.7 The role of srcVisual

srcVisual addresses an interpretability problem rather than changing detection
accuracy. A move annotation refers to two structural locations that may reside
in different files. The synchronized XML, tree, source, diff, and move views
allow an investigator to see those locations in one consistent presentation
and to inspect the evidence used during failure analysis.

This makes srcVisual valuable to the research workflow: it supports manual
inspection, communicates representative examples, and can reveal metadata or
file-ownership errors that are difficult to notice in raw XML. It does not,
however, provide an independent correctness oracle. If all panes faithfully
render an incorrect annotation, the presentation remains internally consistent
but the detector result is still wrong.

`[EVALUATION NEEDED: describe the selected srcVisual artifact, engineering, or
user-study evaluation and limit the conclusion to that design.]`

Without a user study, the thesis may conclude that srcVisual implements and
tests stated synchronization and inspection requirements. It may not conclude
that the interface improves developer comprehension, speed, or accuracy.

## 9.8 Threats to validity

### 9.8.1 Construct validity

The central construct is a *source-code move*, but each evaluation observes a
proxy for that concept. BigMoveBench begins with clone labels and converts them
into synthetic before/after layouts. srcMove History observes detector output
without complete historical ground truth. srcVisual exposes annotations but
does not determine their correctness. These proxies make different aspects of
the problem measurable, but none captures developer intent directly.

Clone categories and srcMove match kinds must also remain distinct. BigCloneBench
similarity is computed over its own representations, whereas srcMove uses
srcML-derived canonical forms and bounded sequence similarity. A BigCloneBench
Type-3 label does not guarantee that srcMove should classify the pair as Type-3
under every threshold, and equal numeric similarity values need not carry the
same meaning in both systems.

The strict positive oracle requires the expected complete fragment, positional
overlap, correlated annotations, and expected match kind. This provides a clear
test but can classify an otherwise related child move or wrong-kind detection as
a failure. Results should therefore retain those secondary outcomes rather than
reporting only a binary total.

### 9.8.2 Internal validity

Synthetic wrapper construction can influence srcDiff alignment. BigMoveBench
reduces this risk through stable paths, distinct container classes, complete-
range eligibility checks, and versioned oracle logic, but the generated context
is still part of the treatment.

Threshold development creates another risk. If Type-3 thresholds or filtering
rules are tuned on the same cases used for final reporting, the evaluation will
overestimate performance. Tuning and publication selections must be frozen and
identified separately, including their seeds, strata, and content identities.

Execution failures, invalid XML, timeouts, and interrupted cases can bias a
result if they are silently omitted. The benchmark manifests must retain these
outcomes and every reported rate must state whether they remain in its
denominator. Similarly, manual review can introduce researcher judgment; any
qualitative sample requires a declared selection and review procedure.

### 9.8.3 External validity

BigCloneBench and IJaDataset primarily provide Java function fragments. The
controlled evaluation therefore cannot establish equivalent behavior for every
language supported by srcML or for arbitrary statement, class, and file-level
moves. Hand-authored multi-language regression fixtures demonstrate supported
mechanisms, but they are not population evidence.

Selected repository histories may differ in language, age, size, contributor
practice, and commit discipline. Results from those projects should be reported
as project-specific observations. Broader claims would require a declared and
defensible repository sampling frame.

Performance results are similarly specific to their workloads and environment.
Docker allocation, bind-mounted versus container-local storage, compiler and
library versions, processor topology, and background system load can all affect
the measurements.

### 9.8.4 Conclusion validity

Repeated BigCloneBench rows may refer to identical fragment contents and are
not independent observations. Deduplication and provenance prevent repetition
from masquerading as evidence breadth, but the final report must state the unit
of analysis clearly.

Pooled rates can also obscure large differences among match kinds, strength
strata, functions, projects, and fragment sizes. Results should be stratified
where the research question expects different behavior. Confidence intervals
or statistical comparisons should be chosen for a stated inferential purpose,
not added after inspecting the outcome.

Qualitative examples illustrate mechanisms and failure modes; they do not
estimate population frequency. Representative cases must be selected through a
declared process so that unusually favorable examples are not mistaken for
typical behavior.

### 9.8.5 Reproducibility

The separate repositories and generated artifacts make provenance essential.
Each publication result should identify source revisions, dirty-state
observations, workspace-lock state, executable checksums, build receipts,
dataset and workload identities, configuration, environment, and the scripts
used to produce tables and figures.

A binary located beside a source checkout is not proof that it was built from
that checkout. When a verified receipt is unavailable, the thesis must label the
source-to-binary binding as unverified rather than infer it. External datasets
must likewise be identified by version and checksum because upstream contents
or local extraction can change independently of the analysis code.

## 9.9 Practical interpretation

Within its declared scope, srcMove should be understood as an explainable
structural matcher layered on srcDiff XML. Its annotations provide evidence that
deleted and inserted constructs are related under a specific canonicalization
or similarity rule. The evidence is strongest for unambiguous, structurally
meaningful candidates and weaker for highly repeated or many-to-many groups.

Downstream tools can use the annotations to navigate, summarize, visualize, or
study changes, but they should preserve the match kind, cardinality, source
locations, and applicable limitations. Human inspection remains appropriate
for ambiguous results and for any claim about developer intent or behavioral
equivalence.

## Remaining writing tasks

- Replace every `[RESULT NEEDED]` and `[EVALUATION NEEDED]` marker with a cited
  table, figure, manifest, or explicit statement that the evaluation was not
  performed.
- Connect failure explanations to representative cases chosen by a declared
  procedure.
- Verify that every interpretation stays within the research scope established
  in Chapter 3.
- Add citations for validity terminology and any literature-derived explanation
  used in the final discussion. `[CITATIONS NEEDED]`

