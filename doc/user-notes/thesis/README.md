# Master's Thesis Working Draft

This directory contains the working draft for Nicholas Stafford's master's thesis
on `srcMove` and its companion visualization system, `srcVisual`. `srcMove` is
the primary research contribution. `srcVisual` is a supporting contribution
that makes structured differences and cross-file move annotations inspectable.

The thesis is currently in a seven-day completion effort. The maintained
[Seven-Day Thesis Completion Plan](seven-day-plan.md) defines the deadline
strategy, working boundaries, completion gates, rolling state, and recursive
improvement protocol for every human or AI work session.

Only thesis-quality material belongs here. Scratch notes, unverified ideas,
and temporary benchmark observations belong in `doc/user-notes/`. Concrete
unfinished implementation tasks may use `doc/handoffs/`; broader unresolved
work belongs in the relevant backlog.

## Working thesis statement

Structured information already present in srcDiff XML can be used to recover
useful source-code move relationships without replacing the underlying diff
engine. A conservative deterministic post-processing pipeline can prioritize
exact and consistently renamed moves—including moves across files—while
admitting only high-confidence Type-3 near misses and preserving the srcDiff
document for downstream inspection in srcVisual.

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

## Structure and design decisions

- The thesis is contribution-centered because srcMove, BigMoveBench, srcVisual,
  and srcMove History answer different questions and require different evidence.
  A single implementation/results split would obscure those boundaries.
- srcMove is the primary contribution. srcVisual supports inspection, while
  srcReader changes remain part of the srcMove implementation story unless the
  evidence later supports a separate contribution claim.
- The proposed move taxonomy currently lives in background and related work so
  it can define terms before the srcMove chapter. It may become a separate
  chapter if the literature review and validation plan establish it as an
  independent conceptual contribution.
- BigMoveBench has its own chapter because synthetic benchmark construction and
  oracle validity require explanation separate from detector implementation.
- srcMove History remains distinct from BigMoveBench because it provides
  observational evidence from real revisions rather than labeled accuracy data.
- Performance remains a separate chapter so runtime and scalability claims are
  not confused with detection quality.
- Repository documentation is the source of truth for current software
  behavior. The thesis selects and interprets that behavior in support of its
  research argument.

## Contribution map

| Contribution | Primary question | Placement |
| --- | --- | --- |
| Move taxonomy | How should source-code moves be classified independently of one detector, dataset, or implementation? | Section 2.3 |
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

## Current thesis work

The [Seven-Day Thesis Completion Plan](seven-day-plan.md) is the canonical source
for current priorities, completion gates, risks, and next-session state. Update
that plan in place after each substantial work session rather than maintaining a
second task list here.

Use the [Thesis Review Guide](review_guide.md) for structural, evidence, clarity,
and style reviews. Chapter-specific TODOs remain in their relevant files.

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
- Novelty claims for the move taxonomy require a dedicated literature review;
  similarity to clone terminology must be acknowledged without conflating
  clones and moves.
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
