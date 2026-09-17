# Master's Thesis Working Draft

This directory contains the working draft for Nicholas Stafford's master's thesis
on `srcMove` and its companion visualization system, `srcVisual`. `srcMove` is
the primary research contribution. `srcVisual` is a supporting contribution
that makes structured differences and cross-file move annotations inspectable.

Only thesis-quality material belongs here. Scratch notes, unverified ideas,
temporary benchmark observations, and implementation handoffs belong elsewhere
in `doc/user-notes/`, `doc/handoffs/`, or the relevant backlog.

## Working thesis statement

Structured information already present in srcDiff XML can be used to recover
useful source-code move relationships without replacing the underlying diff
engine. A deterministic post-processing pipeline can identify exact,
consistently renamed, and bounded-similarity moves—including moves across
files—while preserving the srcDiff document for downstream inspection in
srcVisual.

This is a working claim, not a conclusion. Its final wording must be limited to
what the frozen evaluation actually demonstrates.

## Draft chapter structure

1. [Abstract](00-abstract.md)
2. [Introduction](01-introduction.md)
3. [Background and Related Work](02-background-and-related-work.md)
4. [Research Questions and Scope](03-research-questions-and-scope.md)
5. [srcMove](04-srcmove.md)
6. [BigMoveBench](05-bigmovebench.md)
7. [srcVisual](06-srcvisual.md)
8. [srcMove History](07-srcmove-history.md)
9. [Performance and Scalability](08-performance-and-scalability.md)
10. [Discussion and Threats to Validity](09-discussion-and-threats.md)
11. [Conclusion and Future Work](10-conclusion-and-future-work.md)

The middle chapters are organized around the major software and research
contributions rather than placing all implementation in one chapter and all
results in another. Each contribution chapter should answer the same basic
questions: what problem did this artifact solve, how was it designed and
implemented, how was it evaluated, what did the evaluation show, and what are
its limitations?

The final university template may split background from related work or require
a separate general methodology chapter. Those formatting decisions do not
change the contribution-centered argument.

## Contribution map

| Contribution | Primary question | Placement |
| --- | --- | --- |
| srcMove | Can structured deletion/insertion regions be classified and annotated as source-code moves? | Chapter 4 |
| BigMoveBench | How can detection, classification, and whole-fragment rejection be evaluated reproducibly at scale? | Chapter 5 |
| srcVisual | How can structured differences and cross-file move relationships be inspected coherently? | Chapter 6 |
| srcMove History | What move evidence is observable across real adjacent repository revisions and endpoint contrasts? | Chapter 7 |
| Performance infrastructure | What does the toolchain cost, where is time spent, and how does history analysis scale? | Chapter 8 |
| srcReader improvements | What general reader/writer capabilities were required to implement srcMove correctly? | Section 4.9 |

This structure can still be collapsed later if the university expects a
traditional system/method/results organization. Keeping the artifacts separate
now makes their individual research questions and evidence requirements visible
and prevents BigMoveBench, srcMove History, or the performance work from being
reduced to implementation footnotes.

## Quality gate

Material is ready to enter this directory only when it satisfies all applicable
rules below:

- Every technical claim is either verified against the implementation and its
  canonical documentation or clearly labeled as proposed work.
- Every quantitative claim names its population, unit, denominator, selection
  policy, tool revision, and result artifact.
- Benchmark results come from frozen, reproducible manifests. Historical local
  runs are not silently promoted to final thesis evidence.
- BigCloneBench-derived cases are described as synthetic moves created from
  clone pairs, not as historical move ground truth or general precision/recall.
- srcDiff-ineligible cases are reported separately from srcMove misses.
- Tuning data and final evaluation data are visibly separated.
- Claims about real repository histories are observational unless a defensible
  ground-truth oracle is available.
- Claims about srcVisual usability require a user study or an appropriately
  limited engineering evaluation. Screenshots alone do not establish usability.
- Planned features are never written in the present tense.
- Primary literature and original project/data documentation are preferred over
  secondary summaries.
- Prose advances the thesis argument; repository operation instructions remain
  in the canonical project documentation and are linked rather than copied.

## Source-of-truth boundaries

These files organize the thesis argument; they do not replace technical
documentation. Verify current behavior against:

- [`doc/architecture.md`](../../architecture.md) for the srcMove pipeline,
  matching rules, output, and limitations
- [`bigMoveBench/docs/methodology.md`](../../../bigMoveBench/docs/methodology.md)
  for synthetic benchmark construction and interpretation
- [`benchmarking/README.md`](../../../benchmarking/README.md) for benchmark and
  provenance boundaries
- [`srcmove_history/docs/README.md`](../../../srcmove_history/docs/README.md) for
  repository-history analysis
- [`srcVisual/README.md`](../../../../srcVisual/README.md) and
  [`srcVisual/docs/Rules.md`](../../../../srcVisual/docs/Rules.md) for the
  visualization system

If a chapter outline conflicts with any of those documents, investigate the
implementation and correct the outline. Do not create a second technical source
of truth here.

## Editing convention

The chapter files are substantive first drafts, not final claims. They combine:

- thesis prose that can be refined into the submitted document
- explicit scope and interpretation boundaries
- placeholders such as `[CITATION NEEDED]` and `[RESULT NEEDED]`
- evidence checklists for experiments, figures, artifacts, and unresolved
  decisions

Use `TODO` only for a concrete missing item. Cite a stable artifact or source
when resolving it. Never remove a result placeholder by substituting an
exploratory number. Remove all drafting instructions before exporting the
thesis.
