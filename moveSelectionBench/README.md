# Move-selection semantic benchmark

This suite measures the parent/child, nesting, `diff:common`, ambiguity, and
cross-Type decisions that the redesign is intended to improve. It complements
rather than replaces BigMoveBench and the performance runner:

- this suite asks whether a build chose the intended *explanation* of a move;
- BigMoveBench measures detection and Type-1/2/3 classification over a larger
  clone-derived population;
- `performance/` measures time, memory, and internal work over fixed inputs.

Every catalog case declares a `status`: an accepted `contract` or an
exploratory `hypothesis`. Normal benchmark runs record every semantic miss as
an observation so variants can be compared. The deterministic test suite runs
contracts with `--contracts-only --enforce-contracts`, making a contract miss a
test failure. Tool crashes, timeouts, malformed output, and invalid XML are
always hard failures.

The current catalog contains accepted contracts; the `hypothesis` status is
available for future questions that have not yet earned regression status.
This benchmark's status is independent of BigMoveBench's observational Type-3
population recall.

The separate `shadow_contracts.json` catalog is the reviewer-owned oracle for
the correspondence classifier and unique Type-1 production policy. Each entry
records five independent parts:

- the required srcDiff delete/insert precondition and Type-1 cardinality;
- the structural context observations the future extractor must produce;
- the expected classification;
- its stable machine-readable reason; and
- the expected Type-1 production disposition.

The move-selection unit suite validates the catalog schema and verifies the
declared srcDiff endpoint counts. Most inputs are small checked-in srcDiff XML
fixtures. The `nodiscard_signature_and_unwrap` case is regenerated from its
checked-in source pair so an upstream srcDiff alignment change cannot let the
contract pass without exposing the exact return as both deleted and inserted.
Raw path incompatibility without a reliable wrapper interpretation remains
`ambiguous`; paths alone never establish relocation or restructuring.

### Type-1 adoption baseline

The Phase 3 production oracle records `move` only for a unique Type-1
correspondence classified as `relocated`; all other unique classifications are
`not_move`. Non-1x1 exact groups explicitly retain existing group policy. At
the srcMove 0.4.0 pre-adoption baseline, seven of the eleven unique contracts
disagree with that policy because current selection emits them as moves:

- `stationary_line_shift`;
- `nodiscard_signature_and_unwrap`;
- `nodiscard_signature_only`;
- `wrapper_added`;
- `wrapper_removed`;
- `incompatible_paths_without_reliable_wrapper_interpretation`; and
- `missing_anchor_ambiguity`.

Every disagreement is expected to change from `move` to `not_move`. The three
positive relocation contracts and the parent-carried child already agree with
the adoption policy. The repeated 2x2 contract remains outside the unique-pair
gate. The focused test seals this pre-adoption disagreement set so Phase 3.1
cannot redefine its oracle from the implementation's output. After adoption,
the same test requires the disagreement set to be empty.

The Phase 3.0 checked-in XML and source-regression inventory was rerun with
diagnostics, using each suite's production granularity. Before source-fixture
normalization it contained 37 selected unique Type-1 correspondences and seven
non-1x1 Type-1 groups:

| Category | Count | Cases |
| --- | ---: | --- |
| Supported relocation | 14 unique | XML: `archive_cross_file_same_text`, `archive_whole_file_split_structural`, `position`; source: `complex`, `file_split`, `from_deleted_file`, `renamed_file`, `renamed_file_2`, `to_new_file`, `to_new_file_comment_change`, `to_new_file_ws_change` |
| Insufficient context | 14 unique | `1x1_basic`, `archive_2_files`, `child_construct_is_fallback_when_diff_wrapper_text_does_not_match`, `diff_ws_equivalent`, `do_not_annotate_diff_wrapper_when_child_construct_moves`, `large_text_same`, `nested_diff`, `pre_marked_move`, `pre_marked_move_small`, `single_structural_child_in_wrapper`, `spacing_variation`, `two_independent_groups` |
| Fixture filename artifact | 9 unique | `blocks_swapped`, `function_call_reorder`, `function_content`, `lines_swapped`, `lines_swapped_many`, `simple_cross_block`, `standalone_function` |
| Existing non-1x1 policy | 7 groups | XML: `1x2_basic`, `2x1_basic`, `2x2_same`, `2x3_same`; source: `complex`, `standalone_blocks`, `standalone_blocks_function` |

### Phase 3.2 normalized source inventory

The source runner now copies every single-file pair beneath separate generated
revision roots, using `source.<ext>` as the same logical relative filename on
both sides. It also compares ordinary JSON from normal annotated output with
`--results-only`. A diagnostic rerun manually audited the nine unique Type-1
correspondences whose earlier classification depended on
`original.cpp|modified.cpp`:

| Normalized evidence | Count | Cases and outcome |
| --- | ---: | --- |
| Different mapped semantic container | 3 | `function_content` (both literal correspondences) and `simple_cross_block`; remain moves |
| Same mapped container and anchor interval | 1 | `function_call_reorder`; structural child is stationary and not independently selected |
| Insufficient structural context | 5 | `blocks_swapped`, `lines_swapped`, both `lines_swapped_many` correspondences, and `standalone_function`; no unique Type-1 move |

Four golden files therefore change move membership:
`blocks_swapped` (one to zero), `lines_swapped` (one to zero),
`lines_swapped_many` (two to one), and `standalone_function` (one to zero).
The remaining reviewed relocation goldens stay positive. Directory comparison
also changes single-file archive XPaths from `/src:unit[1]` to
`/src:unit[@filename='source.cpp']`; `function_call_reorder`,
`function_content`, `reorder_function_specifiers`, `simple_cross_block`,
`standalone_blocks`, and `standalone_blocks_function` receive only the
corresponding serialization or selected-wrapper expectation update.

Normalization exposes repeated wrapper candidates around `foo();` in
`function_call_reorder` and `int i = 1;` in `lines_swapped_many`. Their reviewed
structural-child correspondences are respectively stationary and ambiguous,
but the existing non-1x1 exact-group path still emits one non-overlapping
wrapper endpoint pair in each case. Those two groups remain intentionally
outside the unique Type-1 gate; changing them here would alter the deferred
non-1x1 policy. The normalized inventory is therefore 17 positively supported
unique relocations (the prior 14 plus three), 20 reviewed unique conservative
non-moves (the prior 14 insufficient-context correspondences plus these six),
and nine non-1x1 exact groups (the prior seven plus the two newly exposed
wrapper groups).

The insufficient-context XML cases primarily protect matching, wrapper, and
serialization mechanics. Their existing move goldens are not positive
relocation evidence. Phase 3.2 must review them individually before removing
or strengthening their move expectations. The inventory counts selected
correspondences, so `archive_2_files` and `two_independent_groups` each
contribute two; `archive_whole_file_split_structural` contributes two supported
cross-file relocations; `complex` contributes three unique relocations plus one
unchanged non-1x1 group.

Move-selection catalog fixtures that test hierarchy, ownership transitions,
and cross-type competition now use explicit `source|destination` revision
filenames when their required Type-1 result is intended to be a relocation.
This supplies positive file evidence while leaving the construct topology
under test unchanged. It applies to `nested_exact_parent_over_child`,
`nested_near_miss_parent_over_exact_child`,
`independent_children_not_false_parent`,
`mixed_parent_rejected_inner_survives`,
`deep_nesting_has_no_two_level_limit`, `delete_common_transition`,
`insert_common_transition`, `delete_insert_transition`,
`insert_delete_transition`, `children_utility_over_weak_parent`,
`shared_delete_stronger_edge`, and
`coherent_type3_parent_over_partition`.

## Retained Notepad++ shadow evaluation

The retained evaluation uses Notepad++ commit
`e59774add26b0130d38aaf722aceb0259ccc0078` and parent
`bf9f8b4c9549dadd23f483190dd1e1e4707da3ea`, limited to
`scintilla/src/Document.h`. The ignored evidence directory is
`benchmark-results/correspondence-baseline-notepadpp/`. Its `before.tar` and
`after.tar` snapshots have SHA-256 values
`8e1523139afd8c16f981abe130920853dd43a5e77a7d38e0809d4387742a47d0`
and `27e5eb5de83440dc10e74e743c646e1f0f538627f8ab3cdc02b51e3bb1b16049`.
The contained files exactly match the corresponding Git objects, with hashes
`6f7661ebeb0b85588961b6c3518f65560ab67725d37b9b3e36b4c71ac7389e01`
and `517d37ed54f5bca008afe2e0c9eb78d0d7aecc6b30f4305e7f0cb24ab8eba22c`.

Regenerate srcDiff from the two extracted directory roots rather than using a
direct file comparison. The directory comparison records the shared logical
child filename `scintilla/src/Document.h`; a direct comparison embeds distinct
temporary `before` and `after` prefixes in `unit@filename`, which would
incorrectly appear to the classifier as positive cross-file evidence. The
retained normalized srcDiff is `shadow-srcdiff.xml`, SHA-256
`2c1221226aef346a7a4511d3725f836a6ea8ebfbe8da0ca1ca1f2a2c2129632e`.

At srcMove commit `5c634c88691ecb9d6c846d02c83f189a0ba9a4d9`, the normalized comparison
produces 12 current move groups, all Type-1, matching the retained baseline
count. The evaluated release build has artifact SHA-256
`de59e645da199d3ff912677cb073f0bcb23c053f8be13f1f1a8a05cb228b0be5`
and build receipt
`build-receipt-sha256-0f2da449b93686ca0a3f52f89aeec81b706143672d6e07f277a6cbf7c1ed257e`
(Clang 18.1.3, C++17, srcReader
`b4b2a88fca88e5dae40fd181f2666961e3ce01dc`). The srcDiff regeneration used
srcdiff 0.1.0 at commit `f48b8180e0c2e9d07e098553d96ed3895676bfdc`.
Diagnostics contain 17 unique Type-1 correspondences: 12 selected by
current move detection and five rejected by current selection. All 17 shadow
classifications are `ambiguous/insufficient_context` because srcDiff serializes
their enclosing constructs exclusively and exposes no reliable mapped semantic
container. Therefore the measured current-versus-shadow disagreement is 12
`move` versus `ambiguous` records; the five unselected records remain
non-relocation observations. This evaluation does **not** establish that those
12 are stationary or restructured. The small reviewed contracts provide that
interpretive evidence; the real comparison demonstrates the conservative
fallback when srcDiff lacks sufficient common structure.

Run the current build:

```bash
python3 moveSelectionBench/benchmark.py \
  --variant current=build/srcMove \
  --run-id current-characterization
```

Compare a redesign with a baseline:

```bash
python3 moveSelectionBench/benchmark.py \
  --variant baseline=/path/to/baseline/srcMove \
  --variant candidate=/path/to/candidate/srcMove \
  --baseline baseline \
  --run-id parent-aware-selection
```

The append-only run directory contains a provenance manifest, sealed attempt
records and logs, per-case semantic outcomes, profiler metrics, a summary, and
baseline-to-candidate transition counts. Do not report only a pass total: review
the individual rationale and forbidden interpretations for changed cases.

## Adding cases

Add one isolated srcDiff XML input under `cases/` and one catalog entry. A
required expectation says that a move pair should exist. A forbidden
expectation says that an interpretation should not be selected. Raw text is
compared after whitespace normalization; match kinds remain explicit.

Archive fixtures declare `"input_shape": "archive"`; single-file fixtures may
omit the field. Set `"verify_results_only_equivalence": true` when a case must
also confirm that normal and `--results-only` executions select identical move
endpoints and match kinds.

Cases with no required moves are useful negative controls. Keep uncertain
examples as `hypothesis` cases. Change the status to `contract` only after the
expected behavior has been reviewed and accepted; contracts run under
`make test`.

Type-1 classifier contracts belong in `shadow_contracts.json`. Add a
single-purpose input under `shadow_cases/`, declare the exact srcDiff
precondition, fill every context dimension, select a classification reason and
production disposition from the stable vocabulary enforced by
`shadow_contracts.py`, and keep expected output independent of current results.
A source-level alignment regression should use an `original`/`modified` pair
and be generated by the test instead of checking in a large real-world srcDiff
artifact.
