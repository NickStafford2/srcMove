# Chapter 5: BigMoveBench

## 5.1 Chapter purpose

BigMoveBench is the evaluation system developed for srcMove. It transforms
evidence from BigCloneBench into controlled cross-file move cases, preserves the
identity and provenance of every transformation stage, and applies explicit
oracles to srcDiff and srcMove. BigMoveBench is not a new ground-truth
history of moves. Instead, it makes a large clone corpus usable for repeatable
questions about whole-fragment detection, match-kind classification, and
rejection.

The distinction is fundamental. BigCloneBench labels pairs of Java functions as
clones or known false positives; it does not assert that a developer moved one
function to the location of the other. BigMoveBench constructs that edit. A
reported pass rate therefore measures performance on a declared population of
synthetic moves derived from clone pairs. It must not be described as general
move-detection accuracy, historical-move recall, or precision.

This chapter addresses four questions:

1. How can a large clone corpus be transformed into controlled cross-file move
   cases without treating clone pairs as historical edits?
2. How effectively does srcMove detect and correctly classify eligible Type-1,
   Type-2, and declared Type-3 synthetic moves?
3. How often does srcMove avoid linking the complete fragments in a declared
   known-false-positive population?
4. How can inputs, exclusions, failures, tools, and results remain auditable
   across a large and potentially interrupted evaluation?

## 5.2 Why a dedicated benchmark was needed

Small regression fixtures are essential for testing individual rules, but they
are written by the implementer and cover a deliberately narrow set of examples.
They cannot reveal how often the detector succeeds across a large and varied
external corpus. Conversely, a clone corpus cannot be passed directly to a move
detector because it contains pairs of fragments rather than before/after
revisions. A defensible evaluation therefore needs a conversion whose behavior
is explicit, deterministic, and inspectable.

The conversion introduces additional failure boundaries. A source range may be
unavailable or malformed. A generated wrapper may influence srcDiff's
alignment. srcDiff may produce valid XML without exposing the complete payload
as deletion and insertion regions. srcMove may fail to execute, detect only a
child construct, report the intended whole fragment under the wrong match kind,
or satisfy the complete oracle. Treating every non-pass as the same kind of
miss would attribute failures to the wrong component.

BigMoveBench was built to retain those distinctions. It separates dataset
compilation, deterministic selection, generated inputs, srcDiff output,
srcMove execution, and scoring. That separation supports resumption and reuse,
but more importantly it makes the experimental claim traceable back to its
source data and oracle.

## 5.3 Dataset model

BigMoveBench uses the BigCloneBench database together with the Java source files
in IJaDataset. Function records identify a source file and line range. Positive
pair records connect two function identifiers and retain clone category,
functionality, line similarity, token similarity, size, and other dataset
metadata. Known false positives are stored separately and have their own
selection fields.

There are several distinct units that must not be confused:

- a **source row** is an upstream database record;
- a **function fragment** is the extracted text addressed by a function row;
- a **content pair** is an unordered pair of extracted fragment byte strings;
- a **selection frame** is BigMoveBench's execution identity plus all upstream
  rows that contribute to it; and
- a **benchmark case** is the directed synthetic edit generated from a selected
  frame.

Many upstream rows can resolve to the same extracted content pair. Reporting
row counts alone can therefore make a population appear more diverse than the
actual inputs executed by srcMove. The default deduplication unit is the exact
unordered fragment-content pair, while all contributing rows and their
multiplicity remain attached as provenance. Row-based execution remains useful
for audits, but it answers a different question.

BigCloneBench's Type-1, Type-2, and Type-3 labels are useful external strata;
they are not definitions of srcMove's match kinds. BigCloneBench similarity is
computed over its own normalized representations, whereas srcMove operates on
srcML-derived exact, normalized, and bounded-LCS representations. The
evaluation can test whether these categories align in practice, but it must not
assume that they are interchangeable. This is especially important for Type-2:
BigCloneEval reports a most-generous Type-2 category together with blind and
consistent subsets, while srcMove implements the consistent variant defined in
Section 2.3.3. A final Type-2 evaluation must therefore identify which subtype
each selected pair represents and report consistent and blind cases separately.
If the available benchmark metadata cannot reproduce that distinction, the
study must state the limitation rather than treating every BigCloneBench Type-2
pair as an expected srcMove `type2` match.

### 5.3.1 BigCloneBench, BigCloneEval, and BigMoveBench

BigCloneBench, BigCloneEval, and BigMoveBench have related inputs but different
experimental units. BigCloneBench supplies a graph of labeled relationships
among fragments in IJaDataset. In the standard BigCloneEval workflow, a clone
detector analyzes the source corpus, usually reusing parsed or indexed fragment
representations, and emits detected pairs. BigCloneEval imports those detections
and matches them against the reference relationships. Millions of benchmark
relationships therefore do not normally imply millions of independent detector
process executions.

BigMoveBench asks a different question and performs different work. Each
deduplicated relationship selected for execution becomes an independent
synthetic before/after edit. The current runner materializes that edit, invokes
srcDiff, applies the semantic eligibility gate, invokes srcMove when eligible,
and scores and journals the result. A complete Type-3 census would consequently
execute millions of two-tool pipelines rather than one corpus-level detector
run. Its elapsed time cannot be compared directly with a paper that reports one
indexed clone-detection pass over IJaDataset.

| Dimension | BigCloneBench with BigCloneEval | BigMoveBench |
| --- | --- | --- |
| Reference unit | Labeled relationship between existing fragments | Directed synthetic before/after case derived from a relationship |
| Detector input | Source corpus or deterministic corpus partitions | One generated two-file revision pair per case |
| Typical reuse | Parsing, tokenization, and indexes reused across the corpus | Immutable wrapper objects are reused, but srcDiff and srcMove execute per case |
| Evaluation | Match imported detector output against reference pairs | Check upstream eligibility, whole-fragment identity, position, text, and match kind |
| Primary claim | Clone-detector recall for a declared reference population | Synthetic move detection and classification for a declared generated population |
| Runtime meaning | Corpus analysis plus import and reference matching | Sum of generation materialization, two tool stages, validation, scoring, and persistence |

This difference is not merely an implementation detail. It prevents a
BigMoveBench case count from being interpreted as though it were the number of
source fragments analyzed by a conventional clone detector, and it motivates a
declared sampling design when a full per-relationship census is not practical.

**TODO (citations):** Cite the primary BigCloneBench, BigCloneEval, IJaDataset,
clone-taxonomy, and scalable clone-detection publications. Support the workflow
comparison above from the primary BigCloneEval description rather than from
tool marketing or elapsed-time tables alone. Record the exact local dataset
release and checksum used for the final study.

## 5.4 Staged, content-addressed architecture

The supported workflow is:

```text
compile external dataset
        -> select execution frames
        -> publish immutable benchmark cases and shared generated objects
        -> materialize one case in a reusable scratch archive
        -> run srcDiff and apply the semantic eligibility gate
        -> run srcMove in results-only mode
        -> resolve result XPaths in the admitted srcDiff XML
        -> score and commit one logical attempt
        -> derive summaries from the execution journal
```

Compilation imports the external H2 data into a srcMove-owned SQLite catalog,
extracts referenced Java ranges into a content-addressed fragment store, and
builds indexes used by later stages. Selection reads this sealed catalog rather
than repeatedly querying H2. It publishes the requested pair set, role, sampling
or census policy, deduplication rule, and contributing evidence as an immutable
selection artifact.

Benchmark-case publication converts selected frames into rows that reference
content-addressed old/new wrapper objects. The case database records the exact
fragment texts, expected generated line ranges, direction, wrapper version, and
oracle configuration. It does not permanently expand every case into four Java
files. During execution, the serial runner links one case's objects into stable
source and destination paths in a reusable scratch archive, then clears that
archive before the next case.

After srcDiff admission and semantic eligibility checks, srcMove runs with
`--results-only`. BigMoveBench retains `results.json` rather than annotated
srcMove XML. Each result contains the move identity, classification, source and
destination text, and XPaths needed by the oracle. The oracle resolves those
XPaths against the already admitted srcDiff XML, preserving the position check
without generating a second annotated XML document. One SQLite transaction
commits the case outcome and its tool evidence; `summary.json` and `cases.csv`
are derived reports rather than independent sources of truth.

This separation prevents a change in the detector from silently regenerating a
different population. It also lets an investigator inspect a failure at the
appropriate boundary: selection evidence, benchmark-case definition, generated
objects, admitted srcDiff XML, srcMove JSON, or the oracle's classification.
The former expanded snapshot/corpus workflow was removed after small- and
medium-profile equivalence checks. The database-backed runner is now the single
supported execution architecture.

**TODO (figure):** Draw the artifact graph, showing which identities are
content-derived, which runs are append-only, and where external data, srcDiff,
srcMove, and the scoring oracle enter.

## 5.5 Selection, deduplication, and conflicts

A thesis run must either enumerate a precisely defined eligible population or
draw a seeded sample from a declared frame. Ordinary samples use deterministic
SHA-256 ranks. Type-3 samples stratify the conservative external similarity

```text
min(similarity_line, similarity_token)
```

into four bands: at least `.90`, `[.70, .90)`, `[.50, .70)`, and below `.50`.
Quota is allocated across those bands before deterministic ranking within each
band. This produces coverage of very different similarity strengths, but an
unweighted rate over a balanced sample is not an estimate of population recall.

Clone pairs are unordered, while a synthetic edit is directional. Under the
default content-pair deduplication policy, BigMoveBench chooses one canonical
direction from fragment hashes and records reverse rows as nonexecuted evidence.
Every final report must state whether it used this policy, preserved database
direction, or executed both directions. Direction can affect wrapper text,
srcDiff alignment, and detector behavior.

A more subtle issue arises when the same unordered pair of extracted fragment
contents occurs under both a positive and known-false-positive label. This does
not necessarily mean that BigCloneBench assigned contradictory labels to the
same function pair; different files, projects, functions, or contexts can
produce identical extracted text. The synthetic wrapper removes that context,
however, so it cannot defensibly assign opposite oracles to the same generated
input.

BigMoveBench excludes these content identities from scored selections before
sample ranking or census counting. It does not erase the conflict. The complete
evidence is retained in `label-conflicts.jsonl`, the pair-set-specific exclusion
is recorded in `exclusions.jsonl`, and the selection manifest reports affected
frame and row counts. This policy makes the abstraction boundary explicit and
keeps the requested sample size from being silently reduced after selection.

No token, confidence, or judgment threshold is silently added to the positive
selection. Known false positives use their declared judge and confidence rules,
and their token size remains reporting metadata rather than an eligibility
filter. Every inclusion and exclusion rule must be frozen in the final manifest
rather than reconstructed from prose.

## 5.6 Synthetic cross-file move construction

For each selected positive frame, BigMoveBench extracts the first function
fragment and the second function fragment from IJaDataset. It then creates two
revisions with the same relative paths:

```text
old/source/input.java       contains fragment A
old/destination/input.java  contains an empty destination class

new/source/input.java       contains an empty source class
new/destination/input.java  contains fragment B
```

The source and destination use distinct, stable wrapper classes. Because both
files exist in both revisions, srcDiff compares corresponding source files and
exposes a deletion in one and an insertion in the other. Distinct class wrappers
also reduce the risk that the containers themselves are interpreted as the
moved payload. Generated class names derive from content identity, making the
case repeatable.

For Type-1 input, A and B are expected to supply exact evidence after srcMove's
formatting and comment treatment. Type-2 cases may differ in names or literal
values while preserving the declared normalized structure. Type-3 cases supply
externally labeled similarity strata for observation of the bounded-similarity
matcher. In every case, the benchmark asks about the complete generated
fragment; a smaller shared child is a different detection event.

This construction improves control at the cost of realism. It does not preserve
the original class, imports, neighboring members, build system, or edit history.
Those omissions are why the resulting cases are synthetic and why Chapter 7
uses repository histories for a complementary observational analysis.

**TODO (figure):** Include one compact old/new archive example with the expected
deleted and inserted line ranges highlighted.

## 5.7 The srcDiff eligibility boundary

Well-formed srcDiff XML is not sufficient evidence that srcMove received the
case that BigMoveBench intended to test. srcDiff can legally align a generated
revision in a way that fails to expose one complete payload. Since srcMove only
post-processes the regions in that XML, counting such a case as a srcMove miss
would conflate upstream candidate availability with detector behavior.

Before srcMove evaluation, a versioned semantic eligibility check examines the
position-bearing srcDiff document. On each side, it finds deletion or insertion
regions and aggregates descendant `pos:start` and `pos:end` line numbers. A case
is eligible only if one deletion region covers the complete generated source
range and one insertion region covers the complete generated destination range.
The check asks whether the necessary candidate evidence exists; it does not ask
whether srcMove matched it.

The final accounting must preserve at least these outcomes:

1. generation, source extraction, or srcDiff failed;
2. srcDiff produced valid XML but did not expose the complete pair;
3. srcMove failed or produced invalid results on eligible input;
4. srcMove completed but missed the complete pair or assigned the wrong kind;
5. srcMove satisfied the identity, position, text, link, and match-kind oracle.

Two denominators are consequently useful. An end-to-end rate over generated
cases measures the behavior of the complete synthetic pipeline. A conditional
rate over srcDiff-eligible cases isolates srcMove's behavior given the evidence
it is designed to consume. Both are legitimate if labeled; neither should be
silently substituted for the other.

**TODO (figure):** Create a flowchart separating upstream failure,
srcDiff-ineligible input, srcMove execution failure, detector outcome, and
oracle pass.

## 5.8 Positive and negative oracles

### 5.8.1 Positive detection and classification

A positive case passes only when one reported move links both complete generated
fragments and reports the expected match kind. Type-1 expects `type1`, Type-2
expects `type2`, and the declared Type-3 experiment expects `type3`. Position
evidence is obtained by resolving that result's source and destination XPaths
against the admitted srcDiff XML. Position evidence from different reported
moves cannot be combined to manufacture a pass.

The deletion raw text must match the expected source fragment and the insertion
raw text must match the expected destination fragment after wrapper-indentation
normalization. Type-2 and Type-3 do not require the two sides to equal each
other. The resolved deletion and insertion nodes must overlap the expected
generated ranges. Other reported moves do not invalidate the intended match,
but they are retained as diagnostic evidence.

Text comparison is strict except for a narrowly reported repair of obvious
replacement-character encoding damage. A result that passes only under this
tolerance is distinguished from a strict pass. The tolerance does not ignore
normal differences in names, comments, whitespace, or source text.

Detection with the wrong match kind is not a strict pass. It is nevertheless a
valuable separate outcome because it distinguishes failure to find the payload
from disagreement about its classification. Type-3 results are currently
observational, and an evaluation-role Type-3 selection is rejected until a
held-out partition is implemented. That restriction prevents threshold tuning
cases from being presented as independent final evidence.

### 5.8.2 Whole-fragment rejection

Known false positives use the same generated archive and srcDiff eligibility
check, but their oracle is negative: no single reported move may connect the
complete first fragment to the complete second fragment. A result containing no
moves passes. A result containing only smaller child moves also passes and is
recorded with an incidental-move diagnostic, because the upstream label concerns
the complete function pair and does not claim that the functions share no
subtrees.

This experiment measures whole-fragment rejection for the declared known-false-
positive population. It is not general precision and does not produce a
population false-positive rate for arbitrary source changes. Its cases, counts,
and rate therefore remain separate from positive detection-and-classification
results.

## 5.9 Resumability and provenance

Large evaluations must survive interruption without changing the experiment.
BigMoveBench gives compiled datasets, selections, generated objects, and
benchmark-case databases stable identities derived from their inputs and
policies. It records artifact hashes and validates them at stage boundaries.
Evaluation runs are append-only rather than content-addressed because two
executions over the same inputs are distinct observations.

Each process invocation records bounded logs, completion status, timeout
handling, and output validation. The runner commits one logical attempt per
case to SQLite, seals unfinished attempts as interrupted, and skips already
committed terminal attempts unless a retry policy is requested. Retries append
new attempts rather than overwriting earlier evidence. The execution database
is the recovery source of truth; summaries and CSV files can be regenerated
from it.

For publication, provenance must connect every number to the external dataset,
selection request, generated-object and benchmark-case identities, admitted
srcDiff evidence, srcMove binary, oracle version, source revisions, build
receipts, and execution environment. Development runs already retain many of
these manifests and summaries, but the final archive must be verified as a
publication artifact rather than assumed to be complete because a local run
finished successfully.

**TODO (publication gate):** Specify and execute archive verification, including
checksums for the dataset, H2 driver, selected source files, executables,
manifests, result databases, summaries, and environment metadata.

## 5.10 Final evaluation design

The final design should be frozen before results are inspected. For every pair
set, record:

- the dataset release, checksum, and compiled-catalog identity;
- the selection role, population definition, exclusions, and deduplication
  policy;
- census or sample design, seed, direction rule, and Type-3 strata;
- the separation between tuning and evaluation cases;
- wrapper, eligibility-oracle, and scoring-oracle versions;
- srcML, srcDiff, srcReader, and srcMove revisions and executable checksums; and
- operating system, hardware, build configuration, timeouts, and resource
  limits relevant to reproduction.

The population flow should report counts for upstream rows, distinct content
pairs, conflict exclusions, unavailable fragments, selected frames, generated
cases, srcDiff-valid cases, srcDiff-eligible cases, srcMove executions, and
scored outcomes. Functionality and project coverage should accompany case counts
where they help characterize diversity. Repeated rows attached to one frame are
provenance, not independent executions.

Type-1, Type-2, Type-3, and known-false-positive experiments answer different
questions and should have separate tables. For sampled proportions, confidence
intervals are appropriate only when they follow from the actual selection
design. A balanced Type-3 strength sample needs stratum-specific reporting or
population weights; its raw aggregate must not be presented as population
recall.

The execution design also affects the feasible population. BigCloneEval can
compare one imported detector result set against millions of reference
relationships, whereas BigMoveBench presently invokes srcDiff and srcMove for
every selected relationship. Unless bounded parallel execution or a batch
interface is validated without changing the oracle, the final Type-3 study
should use a frozen probability sample sized for the intended stratum-level
estimates rather than assume that the complete multimillion-case census is the
only rigorous design. The sample-size justification, finite-population
correction if applicable, and any population weighting belong in the final
method, not in post-result interpretation.

BigMoveBench data should not double as the performance workload. Cached artifacts
and many small synthetic cases answer detection questions, while Chapter 8 uses
independent, pre-existing srcDiff XML workloads to measure runtime and scaling.

BigMoveBench can also support a future tuning study for Type-3 similarity,
thresholds, approximate-retrieval limits, and parent-versus-child ranking. That
use requires a frozen separation among tuning, validation, and final evaluation
cases. A fitted score remains a ranking or confidence score unless calibration
is evaluated on held-out labeled data. Even then, the interpretation is limited
to the synthetic BigMoveBench population and its wrapper construction. The
benchmark cannot by itself establish that a score of `0.87` means an 87 percent
chance of a genuine historical developer move; that claim would require an
independent historical move oracle.

## 5.11 Results plan

No exploratory or historical run is promoted here as the final thesis result.
The completed chapter should lead with the population flow, then report strict
classification, whole-fragment detection regardless of kind, and diagnostic
failure classes. Each percentage must display its numerator and denominator.

### 5.11.1 Positive synthetic cases

| Pair set | Selected | srcDiff eligible | Strict expected-kind pass | Whole-fragment detected | Wrong kind | Miss | Tool/oracle error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Type-1 | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| Type-2 | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| Type-3: `>= .90` | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| Type-3: `[.70, .90)` | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| Type-3: `[.50, .70)` | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| Type-3: `< .50` | TODO | TODO | TODO | TODO | TODO | TODO | TODO |

**TODO (results):** Populate this table only from the frozen publication
manifests. State whether each rate is end-to-end or conditional on srcDiff
eligibility. Report Type-3 as observational unless the held-out evaluation gate
has been completed.

### 5.11.2 Known-false-positive cases

| Selected | srcDiff eligible | Whole-fragment rejected | Whole-fragment accepted | Incidental child moves | Tool/oracle error |
| ---: | ---: | ---: | ---: | ---: | ---: |
| TODO | TODO | TODO | TODO | TODO | TODO |

**TODO (results):** Report whole-fragment rejection separately from all positive
rates. Do not rename it precision or combine it into an accuracy score.

### 5.11.3 Failure analysis

Aggregate rates should be accompanied by a declared failure analysis. Useful
categories include raw-identical misses, raw-different misses, complete payloads
reported under the wrong kind, child-only detections, text mismatch,
srcDiff-ineligible cases, tool failure, and oracle validation failure. Examples
must be chosen by a reproducible rule—such as every failure in a small census or
a seeded sample within each class—rather than selected only because they make the
system look favorable.

**TODO (analysis):** Define the example-selection procedure before reading the
final failures, preserve the selected case identifiers, and include both
representative successes and failures.

## 5.12 Threats to validity and limitations

The principal construct-validity threat is the conversion from clone
similarity to move similarity. The benchmark establishes that a known pair was
placed in a deletion/insertion scenario; it does not establish that such an edit
occurred historically or that a developer would call it one move. Type labels
from BigCloneBench and match kinds from srcMove also use related but different
representations.

The corpus is Java-based, so conclusions do not automatically generalize to all
languages supported by srcML. Extracted functions may depend on imports, class
members, or surrounding context that the wrappers omit. The files generally do
not need to compile for srcML processing, but extraction and wrapper artifacts
can still affect srcDiff alignment. The explicit eligibility boundary measures
rather than eliminates this threat.

Content-pair deduplication reduces repeated executions but also changes the
statistical unit from upstream rows to unique payloads. Canonical direction tests
one of two possible synthetic edits. Known-false-positive labels support only a
whole-pair rejection question, not the claim that no legitimate child move
exists. Type-3 conclusions depend on both the external strength bands and
srcMove's fixed threshold, and tuning on the evaluation population would bias
those conclusions.

Finally, reproducibility infrastructure reduces accidental variation but cannot
make the oracle broader than its definition. BigMoveBench provides controlled,
auditable evidence about synthetic whole-fragment cases. Repository-history and
performance chapters are needed to address behavior on real revision sequences
and execution cost.

## 5.13 Evidence still required for the final chapter

- **TODO (citations):** Add primary references for BigCloneBench, BigCloneEval,
  IJaDataset, clone categories, benchmark design, and statistical reporting.
- **TODO (dataset):** Freeze and cite the exact external database, source tree,
  compiled catalog, and checksums.
- **TODO (methods):** Freeze selection roles, exclusions, seeds, directions,
  oracle versions, the Type-3 tuning/evaluation boundary, and the statistical
  justification for any Type-3 sample in place of the full census.
- **TODO (figures):** Produce the artifact graph, synthetic archive example,
  eligibility flowchart, and population-reduction diagram.
- **TODO (results):** Run and archive the publication evaluations, then populate
  Section 5.11 from their manifests without merging unlike pair sets.
- **TODO (release):** Record how another researcher can obtain the upstream data
  and verify the archived artifacts without relying on this workstation's
  mutable cache.

The canonical operational and methodological details remain in the
[`BigMoveBench workflow guide`](../../../bigMoveBench/README.md) and
[`conversion methodology`](../../../bigMoveBench/docs/methodology.md). This
chapter should explain and defend the research design rather than duplicate the
commands in those documents.
