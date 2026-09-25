# Seven-Day Thesis Completion Plan

## Goal

Produce one submission-ready master's thesis within seven days. It combines
four bodies of work that may later become separate papers:

1. srcMove, the primary contribution;
2. BigMoveBench;
3. srcVisual; and
4. srcMove History.

Performance and provenance support the four contributions. The move taxonomy
should remain only as prominent as its literature support and validation allow.

Keep this plan brief and current. Replace stale information instead of appending
a session diary. Record a fact once and link to its canonical home.

## Working boundary

`doc/user-notes/thesis/` is the working home for thesis chapters, thesis-wide
decisions, and completion state. Other files in `doc/user-notes/` are scratch
material until deliberately integrated.

The thesis interprets software behavior but does not define it. Verify technical
claims using the canonical sources linked from the [thesis README](README.md).
Update those sources when software facts change; do not create a second technical
description here.

The copied `university-provided-classicthesis-template` directory contains
generic ClassicThesis 4.8, not verified university requirements. Do not assume
it defines required margins, front matter, or submission rules.
The professors report that the required format has remained stable for roughly
ten years and is enforced strictly. Obtain the actual specification or a recent
accepted thesis before adapting this generic bundle.

## Frozen priority

Until thesis submission, cleanup and stabilization take precedence over new
features and experimental development. srcMove will become deliberately
conservative: Type-1 and Type-2 moves are the primary results; Type-3 is limited
to high-confidence near misses. Define the exact acceptance rule before changing
code—do not infer a threshold from this statement.

Only the minimal implementation changes and regression verification needed for
that priority are in scope. Defer broader algorithm work and new experiments
until after submission. If existing evidence cannot support a thesis claim,
narrow the claim rather than starting an unplanned study.

## Definition of done

- The four contributions form one argument rather than four disconnected papers.
- Research questions, methods, results, discussion, abstract, and conclusion agree.
- srcMove emphasizes reliable Type-1 and Type-2 detection and reports only
  narrowly accepted, high-confidence Type-3 near misses.
- Technical claims match identified revisions.
- Quantitative claims identify their population, unit, denominator, selection,
  exclusions, tool revision, and retained evidence.
- Synthetic, historical, visualization, and performance evidence remain distinct.
- Required citations, figures, tables, and cross-references are complete.
- Draft notes and placeholders are resolved or stated as limitations.
- The verified university LaTeX format builds reproducibly and the final PDF
  passes content and visual review.

## Seven-day sequence

1. **Stabilize:** clean up existing work, audit stale claims and unfinished code,
   and freeze the smallest conservative srcMove behavior needed for submission.
2. **Adjust srcMove:** prioritize Type-1 and Type-2, restrict Type-3 to a defined
   high-confidence near-miss rule, and add focused regression coverage.
3. **Correct system chapters:** reconcile srcMove, BigMoveBench, srcVisual, and
   srcMove History with the frozen implementations and available evidence.
4. **Complete related work:** add primary sources, build the comparison, and narrow
   taxonomy or novelty claims to what the review supports.
5. **Write findings:** use validated existing artifacts, narrow unsupported
   claims, answer each research question, then rewrite the abstract and conclusion.
6. **Integrate and typeset:** remove repetition, normalize terminology, generate
   figures and tables, and build the complete thesis in the verified format.
7. **Final review:** inspect every page, verify claims and references, remove all
   draft residue, rebuild cleanly, and preserve the submission package.

## Recursive improvement loop

Each session should make the next session easier.

1. Read this plan, the thesis README, the relevant complete chapters, and the
   canonical technical sources they depend on.
2. Choose the highest-priority task that advances the seven-day sequence.
3. Fix structure, facts, and evidence before polishing sentences. Never invent a
   citation, result, implementation detail, or conclusion.
4. When a recurring obstacle is discovered, improve the relevant instruction or
   canonical document. Remove obsolete guidance rather than layering on a caveat.
5. End by replacing the rolling state below with the completed decision, current
   blocker, and single best next action. Validate links and run `git diff --check`.

## Rolling state

**Updated:** 2026-09-25
**Phase:** cleanup and conservative srcMove adjustment.

**Immediate priorities:**

1. define the smallest defensible high-confidence Type-3 acceptance rule;
2. implement and verify the conservative behavior without adding new features;
3. update canonical architecture documentation and thesis claims to match;
4. continue repository and thesis cleanup, then verify the university format.

**Audit finding:** Type-3 currently accepts a line or token LCS ratio of at least
0.70 and competes with exact and Type-2 proposals in one utility ranking. The
conservative rule must define both a higher acceptance boundary and whether
Type-1/Type-2 evidence receives absolute precedence.

**Main risks:** “high confidence” is not yet operationally defined; system
chapters are stale; the format is unverified; and existing evidence may require
narrower claims.

**Next session:** start with the first unresolved priority unless the user changes
direction. Update this section in place; do not add another status section.
