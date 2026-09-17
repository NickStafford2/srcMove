# Chapter 3: Research Questions and Scope

The thesis evaluates several artifacts that share a toolchain but answer
different questions. A synthetic benchmark can test controlled detection and
classification; it cannot establish how often moves occur in practice. A
repository-history study can describe detected events; without an independent
oracle, it cannot establish complete recall. Performance measurements can
locate costs on frozen workloads; they cannot establish universal scaling. This
chapter states those questions and boundaries before presenting results.

## 3.1 Unit of analysis and pipeline boundary

The primary experimental unit in BigMoveBench is a generated before/after case
derived from one selected fragment-content pair. The intended payload consists
of the complete deleted source fragment and complete inserted destination
fragment. The end-to-end toolchain has two distinct opportunities to fail:

1. srcDiff may fail to produce valid XML or may produce valid XML without
   exposing complete usable deletion and insertion regions; or
2. given eligible input, srcMove may fail to link and correctly classify the
   complete payloads.

Both outcomes matter, but they answer different questions. The final report
therefore needs an end-to-end result over generated cases and a conditional
srcMove result over cases satisfying the versioned eligibility oracle. Cases
excluded by declared dataset, extraction, or validity rules must be counted
separately rather than disappearing from denominators.

The unit changes in later studies. Whole-fragment known-false-positive pairs are
the unit for rejection behavior. Named srcDiff XML files and repository-history
windows are the units for performance. Adjacent revision pairs and reported
move groups are the units for history observations. These units must not be
combined into one accuracy measure.

## 3.2 RQ1: Synthetic detection and classification

> **RQ1:** How effectively does srcMove detect and correctly classify synthetic
> cross-file moves whose payloads are drawn from declared Type-1, Type-2, and
> Type-3 BigCloneBench strata, both end to end and conditional on srcDiff
> exposing the complete payloads as eligible candidates?

RQ1 tests whether the implemented categories recover an intended whole-fragment
relationship under controlled relocation. A case passes only if one reported
move links both complete generated texts, its XML annotations overlap the
expected source ranges, and its match kind agrees with the declared oracle.
Detecting a smaller shared child or assigning the wrong kind is diagnostic
evidence, but it is not a strict pass.

The final evaluation should report for every declared stratum:

- selected, generated, excluded, failed, invalid, srcDiff-ineligible,
  srcDiff-eligible, executed, and scored case counts;
- strict end-to-end pass count and rate over the stated generated-case
  denominator;
- conditional detection-and-classification count and rate over eligible cases;
- confidence intervals selected before inspecting the final result;
- relevant size, similarity, project, or functionality strata when these are
  part of the frozen design; and
- failure categories separating missing input evidence, missed relationships,
  incomplete-fragment matches, and classification errors.

BigCloneBench Type-3 similarity and srcMove Type-3 similarity are not
interchangeable scores. If Type-3 is included, results should be reported by a
declared BigCloneBench strength band, and score agreement should use an
appropriate association or error analysis rather than assume that equal numeric
values share a definition.

TODO: Freeze the Type-1, Type-2, and Type-3 populations, sampling or census
policy, deduplication key, direction policy, confidence interval method, and
treatment of repeated functionality groups.

## 3.3 RQ2: Whole-fragment rejection behavior

> **RQ2:** How often does srcMove avoid linking complete synthetic fragment
> pairs drawn from the declared BigCloneBench known-false-positive population?

RQ2 tests a narrower behavior than general precision. Each selected negative
pair is converted into the controlled cross-file shape used for positive cases.
The outcome is whether srcMove emits one relationship linking both complete
intended fragments. Incidental matches among smaller child constructs are not
automatically failures because the source fragments may legitimately share
those constructs.

The report should include the frozen negative selection and deduplication
policy, the count for which srcDiff exposed both complete payloads, the whole-
fragment rejection count and rate, and an analysis of accepted complete pairs.
It must not label this result “precision” unless the final experiment samples
from detector-reported positives and applies a defensible oracle to them.

TODO: Freeze the known-false-positive selection, direction, eligibility, and
whole-fragment scoring rules before the final run.

## 3.4 RQ3: Performance and scaling

> **RQ3:** What runtime, peak-memory, throughput, and parallel-scaling behavior
> does the srcMove toolchain exhibit on frozen srcDiff workloads and
> repository-history windows?

RQ3 treats performance as a measured property of named artifacts and
environments. The study should separate at least three costs:

1. srcDiff generation of input XML;
2. srcMove parsing, candidate construction, matching, and annotation; and
3. srcMove History orchestration across repository revisions.

srcMove exposes coarse pipeline timings, while the benchmark infrastructure can
record external wall time and resource observations. Reports should pair input
size with structural measures such as diff-region and candidate counts because
XML byte size alone does not describe matching work. Repeated trials should
state warm-up, cache, ordering, and aggregation policies. Comparisons between
builds should use paired or interleaved measurements where possible and report
variability as well as central tendency.

Parallel history analysis must be interpreted within the tested allocation. A
throughput plateau or slowdown may arise from CPU, memory, storage, process
startup, container allocation, or the mix of revision pairs. The thesis should
identify the tested knee and supporting evidence without generalizing it to all
repositories or machines.

TODO: Freeze machines, container resources, executable revisions, workloads,
repetitions, ordering, resource metrics, and statistical summaries.

## 3.5 RQ4: Repository-history observations

> **RQ4:** What move patterns does srcMove report across selected adjacent
> repository revisions, and what reported evidence is absent when the same
> history is represented only by a distant endpoint comparison?

RQ4 motivates srcMove History as more than a batch runner. Adjacent analysis
preserves the sequence in which changes become visible to the differencing
toolchain, whereas an endpoint comparison collapses intermediate states. The
study may report distributions of match kinds, group structures, files crossed,
fragment sizes, or revisions containing detected events. A focused contrast can
show examples present in adjacent comparisons but absent from endpoint output,
or vice versa.

Unless a complete independent oracle is introduced, these are observations
about srcMove output. They do not estimate true move prevalence, false-negative
rate, or historical origin. Manual inspection can support qualitative examples
but must state its sampling and review procedure.

TODO: Define repository selection, revision windows, exclusions, endpoint
contrasts, measures, and manual-inspection protocol. If the study is too small
to answer RQ4, retain srcMove History as an artifact and move the empirical
question to future work.

## 3.6 Supporting artifact question: srcVisual

> **Artifact question:** How does srcVisual expose the annotated XML, source,
> file ownership, and directional move relationships needed to inspect srcMove
> output coherently?

This calls for an engineering account of information requirements and design
traceability. Relevant evidence includes support for archive and single-file
input, preservation of source metadata through backend processing, derivation
of all views from one final payload, synchronization between XML, tree, source,
diff, and move views, and inspection of cross-file relationships.

A functional demonstration is not a usability study. If no user study is
conducted, the conclusion should be limited to implemented capabilities and
verified consistency properties. It should not claim improved comprehension,
reduced review time, or ease of use.

TODO: Decide whether srcVisual receives a requirements-based engineering
evaluation, a formal user study, or descriptive artifact validation only.

## 3.7 Scope boundaries

### Technical boundaries

- srcMove consumes srcDiff XML and does not generate its own base edit script.
- Detection is limited by evidence exposed by srcDiff and by srcMove's candidate
  policy.
- Default candidates are statement-sized or larger. Fragment-mode results must
  be identified separately.
- Type-1, Type-2, and Type-3 are operational srcMove categories. Type-2 and
  Type-3 do not prove semantic equivalence, behavior preservation, binding
  identity, or developer intent.
- Type-4 semantic moves are unsupported.
- Ambiguous many-to-many and unequal-count groups are classified but not fully
  disambiguated into unique historical pairings.
- srcMove is deterministic for fixed input, implementation, and configuration;
  this does not imply its classification is uniquely correct.

### Empirical boundaries

- The controlled benchmark uses Java fragments because BigCloneBench and
  IJaDataset are Java-based. Implementation support does not establish
  cross-language empirical generality.
- Synthetic clone-derived cases test matching under controlled relocation; they
  are not samples of historical developer moves.
- BigCloneBench rows, distinct content pairs, and functionality coverage are
  different units and must be reported separately where relevant.
- Known-false-positive rejection is not general detector precision.
- Repository-history results are observational without an independent oracle.
- Tuning and final evaluation data must be separate and identifiable.
- Historical local runs may motivate experiments but are not silently promoted
  to final thesis evidence.

### Artifact boundaries

- srcVisual supports inspection but does not validate detector correctness.
- Screenshots demonstrate interface state, not usability.
- Security hardening and public hosting of srcVisual are future engineering
  concerns unless explicitly evaluated.
- srcReader changes are enabling work in the srcMove chapter, not a separate
  research question.

## 3.8 Traceability from questions to evidence

| Question | Primary artifact | Required evidence | Principal limitation |
| --- | --- | --- | --- |
| RQ1 | BigMoveBench positive strata | Frozen manifests, eligibility outcomes, strict oracle results | Synthetic Java fragment pairs |
| RQ2 | BigMoveBench known false positives | Frozen negative manifests and whole-fragment outcomes | Not general precision |
| RQ3 | Performance and history-scaling suites | Named workloads, repeats, environment and executable provenance | Workload- and machine-specific |
| RQ4 | srcMove History | Adjacent-revision outputs, endpoint contrasts, declared inspection procedure | Observational without full oracle |
| Artifact question | srcVisual | Requirements traceability and verified synchronized views | No human-factors claim without a study |

Every result table in Chapters 5, 7, and 8 should identify the question it
answers, its unit, denominator, and source manifest or artifact.

## 3.9 Decisions required before final evaluation

- TODO: Freeze the research-question wording before examining publication-run
  results.
- TODO: Create a metric-to-question map covering every planned table and figure.
- TODO: Predeclare selection, exclusion, eligibility, deduplication, direction,
  and scoring rules for BigMoveBench.
- TODO: Predeclare performance workloads, repetitions, summaries, and resource
  allocation.
- TODO: Decide whether RQ4 and the srcVisual artifact question have sufficient
  evidence to remain in the final thesis.
