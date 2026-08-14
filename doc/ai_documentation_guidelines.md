# AI Documentation Guidelines

Future AI agents should improve this repository's documentation, codebase, and AI
tooling as part of normal work. Do it incrementally and keep every fact in one
clear home.

The purpose of this document is to encourage recursive self improvement. We want
the next AI to read the docs with a better, more concise understanding. We do not
Want endless bloat. Do not write to much or too little. Think about if this is
something a future reader would need to know.

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
- `doc/technical_summary.md`: architecture and implementation overview
- `doc/srcDiff_notes.md`: srcDiff behavior, formats, and quirks
- `doc/bigclonebench_notes.md`: BigCloneBench/IJaDataset setup and database facts
- `doc/bigclonebench_srcmove_conversion.md`: converting BigCloneBench clone pairs
  into srcMove move tests
- `tests/README.md`: correctness-test entry points and suite behavior
- `benchmarks/**/README.md`: benchmark-specific setup, methodology, and runners
- `scripts/`: remaining reusable project automation that future agents should run instead of
  retyping long command sequences

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
