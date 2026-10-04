# Backlog

This is the canonical place for near-term ideas and planned improvements. Keep
entries short. Move durable facts into the correct topic doc when they become
settled.

## Next

- Require positive relocation evidence for repeated exact content groups while
  preserving unresolved endpoint pairings. The current exception is a known
  limitation; see [location classification](architecture.md#location-classification-vocabulary)
  and `apply_correspondence_output_policy` in
  `src/move_registry/content_group_builder.cpp`.
  Define whether group eligibility requires evidence for every possible pair,
  at least one pair, or a compatible set of pairs without endpoint reuse; do not
  select pairings by document order alone. Test stationary repeats, relocated
  repeats, mixed stationary/relocated possibilities, unequal endpoint counts,
  missing context, carrying, and containment conflicts. Check group membership,
  counts, and XML/JSON agreement. Compare affected evaluation results before
  adoption; if changed before thesis submission, rerun affected experiments or
  explicitly identify results produced by the earlier implementation.
- Investigate missed same-file Type-1/Type-2 moves when no named reference
  container is available. Top-level functions outside named containers and
  constructs inside unnamed containers can lack usable container evidence;
  unresolved same-file location then blocks one-to-one reports. See
  `nearest_common_container_index` in `src/region_filter.cpp` and
  `classify_movement` in `src/movement_classifier.cpp`.
  Evaluate file-level reference containers with suitable common anchors
  (including retained functions), and structural correspondence for unnamed
  containers. Preserve the positive-relocation requirement rather than allowing
  unresolved pairs through. Test actual reordering, insertion-only line shifts,
  edits and renames in place, repeated constructs, and nesting; measure recovered
  moves and false reports before adoption. The coverage limitation follows from
  the implementation, but its frequency and the benefit of these extensions
  remain unmeasured.
- Add `--offset` to BigCloneBench generation for deterministic benchmark slices
  such as rows 1-1000, 1001-2000, etc.
- Add the local school repository containing thesis documents once its location
  and appropriate workspace ownership are confirmed.
- Add a generated structural-context regression matrix that places the same
  moved fragment in representative class, function, method, namespace, and
  cross-file contexts. Define a finite supported context inventory instead of
  claiming to generate every syntactically possible nesting combination.

## Later

- Rename the report JSON field `match_kinds` to `match_types` for the Type-1,
  Type-2, and Type-3 group counts. Coordinate the rename with JSON consumers,
  tests, and documentation, and decide how to handle schema compatibility.
- Review related JSON terminology in the same schema update (proposed names;
  current behavior is unchanged):
  - `match_kind` → `match_type`, consistent with the summary field.
  - `confidence_milli` → `selection_weight_milli`: a ranking weight, not a
    measured probability of correctness.
  - `move_pair_count` → `estimated_pair_count`: the sum of the smaller endpoint
    count in each reported group, not a count of established individual pairs.
  - Diagnostic `current_result: "move" / "not_move"` → `selected: true / false`:
    failure to select a pair does not establish that it did not move.
  - Diagnostic `shadow_change` → `location_classification`, identifying the
    relocated, stationary, restructured, or ambiguous classification.
  - Group categories `moves_many` → `repeated_equal_counts` and
    `copy_or_repeat` → `repeated_unequal_counts`: describe endpoint counts
    without implying independently established moves or copies.
- Improve Type-2 move detection.
- Explore Type-3 matching for constructs containing mixed common, deleted, and
  inserted text. The default candidate filter currently rejects such enclosing
  candidates before matching, although eligible constructs inside them can
  survive. A moved-and-edited construct may therefore be unavailable as a
  whole-construct match.
  Reconstruct separate original and modified candidates from the srcDiff
  markup, preserving each revision's structure and location context; do not
  simply admit the combined text. Require relocation evidence so ordinary
  edits in place do not become move reports. Test moved-and-edited constructs,
  edits in place, nesting, and competition with overlapping inner candidates.
  Evaluate coverage and false reports against the existing policy before
  adoption; improved accuracy is not established. This is a long-term extension,
  not a change for the thesis deadline.
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
