# Backlog

This is the canonical place for near-term ideas and planned improvements. Keep
entries short. Move durable facts into the correct topic doc when they become
settled.

## Next

- Add a BigCloneBench dedupe mode so repeated Type-1 pair rows do not inflate
  the apparent variety of tested code shapes.
- Add `--offset` to BigCloneBench generation for deterministic benchmark slices
  such as rows 1-1000, 1001-2000, etc.
- Review docs for upgrades. Generate documentation of current progress for my masters
  thesis.
- General purpose Cleanup.

## Later

- Improve Type-2 move detection.
- Add Type-2 failure categorization using metadata and/or canonical srcML forms.
- Add cross-file/archive BigCloneBench synthetic move cases.
- Decide whether BigCloneBench pair rows and distinct fragment-text cases should
  be reported as separate metrics.

## Questions

- Should Type-2 pass rate be treated as a strict required pass suite or as a
  research metric until Type-2 detection improves?
- What should count as one independent BigCloneBench move test: a pair row, a
  distinct text pair, or a derived clone cluster?
