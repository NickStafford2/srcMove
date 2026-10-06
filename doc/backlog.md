# Backlog

This is the canonical place for near-term ideas and planned improvements. Keep
entries short. Move durable facts into the correct topic doc when they become
settled.

## Next

- Fix the two failing historical Type-3 reporting checks. In
  [the historical Type-3 test](../tests/behavior/test_type3_historical_contracts.py),
  `test_reported_moves_match_source_oracles` now requires srcMove not to report
  the `warp_in_place` constructs (`affine_worker` and `affine_try`) as moves,
  following their [source judgments](../tests/fixtures/selection/type3_history_contracts.json).
  Both checks fail as of October 4, 2026. Retain the source fixtures and judgments;
  do not change expectations to accept the incorrect reports. Address the
  underlying Type-3 policy, which currently permits selection without positive
  relocation evidence. Check genuine relocated Type-3 cases as well as edits
  in place and missing context; unresolved location is not proof of stationary
  code. Preserve historical run records, and rerun affected evaluations when
  reporting behavior changes.
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

- Review greedy proposal selection, which can retain one proposal that blocks
  several compatible proposals with a larger combined ranking score. See
  `build_content_groups` in `src/move_registry/content_group_builder.cpp` and
  `proposal_rank_better` in `src/move_registry/selection_policy.cpp`.
  Retain concrete competing-proposal examples and compare bounded local
  reconsideration with the current policy. Review the inactive descendant-bundle
  rule and interactions with repeated-group membership and relocation evidence.
  Preserve candidate-reuse and containment constraints. Evaluate historical
  correspondence quality, reported granularity, and runtime, not just total
  score: maximizing the current heuristic can also favor excessive fragmentation.
  The limitation is established by the procedure; its frequency and the benefit
  of a replacement remain unmeasured.
- Review remaining JSON terminology (proposed names; current behavior is unchanged):
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
- Extend continuing-name corroboration beyond standalone declarations. Current
  checks reject contradictions and mark unsupported changed-name declarations
  tentative with lower ranking weight, but
  larger isolated normalized matches still lack independent identity support;
  see [the architecture](architecture.md#location-classification-vocabulary).
- Investigate the existing `coherent_type3_parent_over_partition` selection
  contract miss without weakening its whole-function target. Before and after
  the continuing-name slice, the parent verifier matches only 59/80 tokens and
  1/9 lines; no parent proposal reaches selection. The fixture and source oracle
  remain in `moveSelectionBench`. Check normalization stability and verifier
  coverage with both true transfers and unrelated same-shaped functions.
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


- Investigate whole-fragment scoring in BigMoveBench. Each constructed case specifies one expected fragment on each side. Verify whether the scorer should require each fragment’s matching text and source position to belong to the same reported endpoint, and whether it should also verify the expected file path. Add a regression case where a group satisfies the current checks using different endpoints. Compare current and proposed scoring on retained results before changing the oracle. Preserve valid groups containing additional fragments; do not assume every detected move must be one-to-one.

## Questions

- What should count as one independent BigCloneBench move test: a pair row, a distinct text pair, or a derived clone cluster?
