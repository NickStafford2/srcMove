# Thesis Review Guide

This guide is for focused human or AI review of the thesis draft. It records the
standard for evaluating the whole document without turning a temporary editing
handoff into permanent task state. The thesis structure, design decisions, and
current work list remain in the [thesis README](README.md).

## Review objective

Improve clarity, simplicity, organization, evidence discipline, and natural
academic voice. Do not invent citations, experimental results, novelty claims,
implementation behavior, or conclusions. Preserve explicit placeholders when
the required evidence does not yet exist.

Reviewers should read the complete draft before recommending broad structural
changes. A chapter can sound polished in isolation while duplicating another
chapter or depending on a definition that appears too late.

## Required context

Before changing technical claims, consult the canonical source appropriate to
the subject:

- [`doc/architecture.md`](../../architecture.md) for srcMove behavior
- [`bigMoveBench/docs/methodology.md`](../../../bigMoveBench/docs/methodology.md)
  and its [execution guide](../../../bigMoveBench/docs/execution.md)
- [`benchmarking/README.md`](../../../benchmarking/README.md) for evaluation and
  provenance boundaries
- [`srcmove_history/docs/README.md`](../../../srcmove_history/docs/README.md)
- [`srcVisual/README.md`](../../../../srcVisual/README.md) and
  [`srcVisual/docs/Rules.md`](../../../../srcVisual/docs/Rules.md)

The thesis may explain why a design matters, but it must not become a competing
operational manual. When draft prose and implementation documentation disagree,
investigate before deciding which one is wrong.

## Review sequence

### 1. Structural audit

Create a compact map of each chapter's purpose, main claim or question, required
evidence, dependencies, and duplicated material. Check that concepts appear in
the order a new reader needs them and that each research question maps to a
method, result location, and discussion or conclusion.

Pay particular attention to the boundaries among:

- the general move taxonomy and srcMove's operational classifier;
- BigCloneBench relationships and BigMoveBench synthetic moves;
- detector behavior and benchmark behavior;
- synthetic evaluation and repository-history observations; and
- srcMove's primary contribution and the supporting srcVisual and srcReader
  work.

Recommend chapter moves or splits only when they improve the overall argument,
not merely because another organization is possible.

### 2. Evidence and claim audit

For every quantitative or comparative claim, verify the population, unit,
denominator, selection policy, exclusions, tool revision, and retained result
artifact. Keep these limits explicit:

- BigMoveBench cases are synthetic moves derived from clone relationships, not
  historical move ground truth or general precision and recall.
- srcDiff semantic ineligibility is distinct from a srcMove miss.
- Type-3 results remain observational until a frozen held-out evaluation design
  supports a stronger interpretation.
- Repository-history detections are observational without an independent
  oracle.
- Type-4 belongs to the proposed taxonomy but is not implemented by srcMove.
- srcVisual usability or comprehension claims require an appropriate study.
- Performance claims apply only to the recorded workload, revisions, machine,
  storage, and container allocation.

Do not replace `[CITATION NEEDED]`, `[RESULT NEEDED]`, or similar markers with a
plausible statement. Resolve them only with the required source or evidence.

### 3. Chapter editing

Edit for argument and paragraph order before polishing individual sentences.

- Define terms before using them.
- Prefer concrete examples when an explanation remains abstract.
- Separate what the system does from why it was designed that way.
- Use the shortest wording that preserves the technical meaning and validity
  boundary.
- Remove repeated explanations after establishing one canonical home.
- Move repository instructions, exhaustive implementation detail, and raw notes
  out of the thesis when they do not advance its argument.

Preserve useful TODOs and evidence gates. A visibly unfinished but honest
section is preferable to fluent unsupported prose.

### 4. Cross-chapter integration

Audit the complete draft for:

- consistent definitions and Type-1 through Type-4 terminology;
- consistent names for regions, candidates, groups, cases, pairs, and workloads;
- one home for each methodological warning;
- chapter numbering, figures, tables, citations, and cross-references;
- repeated examples or conclusions;
- transitions among srcMove, BigMoveBench, srcVisual, srcMove History, and
  performance; and
- agreement between the abstract, research questions, results, limitations,
  and conclusion.

The proposed move taxonomy deserves special scrutiny. Distinguish move identity
from similarity, transformation type from detector implementation, and moves
from copies, splits, merges, clones, and coincidental similarity. Do not claim
novelty without a systematic literature review. Consider whether definitions
need decision rules, counterexamples, an annotation guide, or inter-rater
validation.

### 5. Natural-voice audit

The draft should sound like a careful software-engineering researcher, not a
product description or generated chapter template.

- Remove generic openings and miniature tables of contents that do not aid
  navigation.
- Avoid promotional adjectives and unsupported certainty.
- Replace strings of abstract nouns with direct verbs.
- Avoid repeating formulaic transitions such as “this distinction is
  important.”
- Vary sentence and paragraph rhythm naturally.
- Keep one deliberate thesis voice rather than alternating mechanically among
  first person, passive voice, and “this thesis.”

Read revised paragraphs as continuous prose. If they sound like policy text,
marketing, or a template, revise them again.

## Review deliverable

A focused review should leave:

1. concise findings ordered by importance;
2. edits that are traceable and limited to the review's declared scope;
3. unresolved questions or evidence requirements in the thesis README or the
   relevant chapter, not in a permanent handoff;
4. no fabricated citations or results; and
5. valid local links and a clean `git diff --check` result.

Multiple reviewers may work on non-overlapping chapters, but one final
integration pass must reconcile terminology, structure, and duplicated claims.
