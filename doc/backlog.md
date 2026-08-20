# Backlog

This is the canonical place for near-term ideas and planned improvements. Keep
entries short. Move durable facts into the correct topic doc when they become
settled.

## Next

- Code review of the BigCloneBench runner and oracle
- Add `--offset` to BigCloneBench generation for deterministic benchmark slices
  such as rows 1-1000, 1001-2000, etc.
- Review docs for upgrades. Generate documentation of current progress for my masters
  thesis.
- Document why `examples/` exists: it contains srcDiff/srcMove example outputs
  consumed by `../srcVisual` to render srcDiff/srcML output in a web UI. Keep the
  checked-in outputs and the ability to regenerate them until they move to
  `srcVisual`. Decide whether `build_example.sh` should be removed, replaced, or
  documented as legacy.
- General purpose cleanup.

## Later

- Improve Type-2 move detection.
- Add Type-2 failure categorization using metadata and/or canonical srcML forms.
- Evaluate BigCloneEval clone matcher logic for ideas srcMove could use when
  deciding which code segment is the intended move.
- Add cross-file/archive BigCloneBench synthetic move cases.
- Add BigCloneBench coverage reporting that summarizes row counts, distinct raw
  text-pair counts, and functionality coverage across a run.
- Decide whether BigCloneBench pair rows and distinct fragment-text cases should
  be reported as separate metrics.
- Flesh out expected_srcdiff_format.xml. it should show srcdiff normal output. 
  Maybe redesign to not be xml? think about the best way to do this. 

## Questions

- Should Type-2 pass rate be treated as a strict required pass suite or as a
  research metric until Type-2 detection improves?
- What should count as one independent BigCloneBench move test: a pair row, a
  distinct text pair, or a derived clone cluster?
