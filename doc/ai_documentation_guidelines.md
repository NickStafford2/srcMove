# Documentation Maintenance and Recursive Improvement

Future AI agents should improve this repository's documentation, codebase, and AI
tooling as part of normal work. Do it incrementally and keep every fact in one
clear home.

The purpose is recursive improvement: each substantial investigation should
leave the repository easier for the next human or AI to understand. That does
not mean recording every action or preserving every task brief. Keep information
that will save future investigation, remove material superseded by current
behavior, and prefer a concise source of truth over accumulated history.

## Core Rule

Write each durable piece of information once, in the most specific place where a
future reader would expect to find it. Link to that source instead of repeating
the same explanation in multiple files.

## When To Update Docs

Suggest or make a documentation update when you discover:

- a workflow that took investigation to understand
- a command sequence that future agents are likely to need
- a non-obvious srcMove, srcDiff, or srcML behavior
- a test convention, fixture format, or benchmark mapping
- an architectural decision or limitation that affects future work
- a recurring user preference about how work should be done
- an improvement to AI tooling, scripts, handoffs, or repo navigation

Keep the update close to the work. For example, benchmark conversion belongs in
benchmark docs, test fixture rules belong in test docs, and broad AI workflow
rules belong in this file.

Documentation cleanup is also improvement. When behavior changes, correct or
remove stale plans, commands, examples, and links as part of the same work.

## Avoid Duplication

Before adding documentation:

1. Search for the topic with `rg`.
2. Prefer editing the existing canonical doc over creating a new one.
3. If a second location needs the information, add a short link to the canonical
   doc instead of restating the content.
4. If two docs already repeat the same idea, consolidate when the change is
   small and clearly in scope.

Do not rewrite large docs just to improve style. Make focused edits that add or
correct durable information.

## Choosing The Right Location

Use these homes unless a more specific file already exists:

- `README.md`: user-facing overview, build/run basics, major project status
- `doc/README.md`: documentation map and where-to-look index
- `doc/architecture.md`: architecture and implementation overview
- `doc/srcDiff_notes.md`: srcDiff behavior, formats, and quirks
- `bigMoveBench/docs/bigclonebench.md`: BigCloneBench/IJaDataset setup and database facts
- `bigMoveBench/docs/methodology.md`: converting BigCloneBench clone pairs
  into srcMove move tests
- `tests/README.md`: correctness-test entry points and suite behavior
- suite-specific `README.md` files: benchmark setup, methodology, and runners
- `doc/backlog.md`: unresolved ideas that do not yet justify a design document
- `doc/user-notes/thesis/README.md`: thesis structure, design rationale, and
  thesis-wide work still needed
- `doc/user-notes/thesis/review_guide.md`: how to review the thesis without
  inventing evidence or duplicating technical documentation
- `scripts/`: reusable project automation that future agents should run instead
  of retyping long command sequences

If no clear home exists, create a narrowly named doc and add exactly one pointer
to it from `doc/README.md`.

## How To Write For Future Agents

Prefer concise, operational notes:

- what the fact is
- why it matters
- where the relevant files live
- which command verifies it
- what should not be assumed

Mark uncertainty explicitly. Do not convert a one-off observation into a rule
unless it has been verified or the limitation is important enough to preserve.

## Plans and handoffs

A plan is useful when future implementation still depends on non-obvious design
constraints or decision gates. Keep it clearly labeled as proposed or dormant,
and update its status when implementation changes its assumptions. Delete a plan
when all useful behavior and rationale have moved into canonical documentation.

Use `doc/handoffs/` only for a concrete unfinished task that a future session is
expected to resume. A useful handoff states the objective, current evidence,
scope boundaries, relevant files, unresolved decisions, and verification. It
must not become the only source for durable architecture or user intent.

When a task finishes:

1. move verified behavior and rationale into the canonical topic document;
2. move genuinely unresolved follow-up work into the backlog or a maintained
   plan;
3. delete the completed handoff rather than archiving it indefinitely; and
4. check for links that still point to the removed task state.

Do not delete a large plan or handoff merely because its immediate task ended.
First identify any reusable constraints, rejected alternatives, evidence rules,
or future ideas that do not exist elsewhere.

## Review checklist

For a focused documentation cleanup:

1. inventory documentation and inbound links;
2. classify each file as canonical behavior, maintained plan, exploratory note,
   active handoff, or obsolete task state;
3. compare behavior claims and commands with the current implementation;
4. consolidate duplicate durable facts into one home;
5. preserve useful unresolved work before deleting its old container;
6. validate local links and run `git diff --check`; and
7. summarize material deletions so the user can review what was intentionally
   retired.

## Self-Improvement Loop

At the end of non-trivial work, future AI agents should ask themselves:

- Did I learn something that would save the next agent investigation time?
- Is there already a canonical place for that knowledge?
- Can I add the knowledge without repeating existing docs?
- Did I create a script or command sequence that should become reusable tooling?
- Did I leave generated files, caches, or ignored scratch output that should be
  cleaned up or clearly reported?

Apply small improvements immediately when they are low risk. If the improvement
is broad, propose it instead of mixing it into unrelated code changes.
