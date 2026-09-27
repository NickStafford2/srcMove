# Backlog

This is the canonical place for near-term ideas and planned improvements. Keep
entries short. Move durable facts into the correct topic doc when they become
settled.

## Next

- Add `--offset` to BigCloneBench generation for deterministic benchmark slices
  such as rows 1-1000, 1001-2000, etc.
- Add the local school repository containing thesis documents once its location
  and appropriate workspace ownership are confirmed.
- Add a generated structural-context regression matrix that places the same
  moved fragment in representative class, function, method, namespace, and
  cross-file contexts. Define a finite supported context inventory instead of
  claiming to generate every syntactically possible nesting combination.

## Later

- Improve Type-2 move detection.
- Add Type-2 failure categorization using metadata and/or canonical srcML forms.
- Evaluate BigCloneEval clone matcher logic for ideas srcMove could use when
  deciding which code segment is the intended move.
- Add aggregate functionality coverage to BigMoveBench summaries. Selection
  manifests already report source-row and distinct fragment-content-case counts.
- If performance becomes a constraint again, profile current binaries and fixed
  workloads before reopening runner parallelism or archive-level concurrency.
- srcMove History: add a read-only preflight or `run --dry-run` that displays
  the definition a new analysis would freeze.
- srcMove History: add versioned CSV/JSONL exports for pair and move evidence.
- srcMove History: consider `status --watch` for passive observation of an
  analysis running in another shell.
- srcMove History: consider optional Git-diff and verbose evidence views for
  `show`; keep stored evidence usable without the source repository.
- Flesh out `expected_srcdiff_format.xml` so it demonstrates normal srcDiff
  output, or replace it with a clearer non-XML explanation.

## Questions

- What should count as one independent BigCloneBench move test: a pair row, a
  distinct text pair, or a derived clone cluster?
