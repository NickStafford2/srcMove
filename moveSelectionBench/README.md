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
serialization mechanics. Their former move goldens were reviewed during
adoption and now conservatively expect zero moves. The inventory counts
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

## Type-2 observation baseline

Phase 4.0 uses `type2_contracts.json` and `type2_cases/` as an independent
location oracle. The twelve contracts cover cross-file/container movement,
reordering, identifier/literal edits in place, wrapping, missing context,
repeated normalized groups, and movement inside edited parents. A selected
parent can explain a relocated child without selecting that child separately.
The tests check actual selection against output, deterministic diagnostic order,
and normal/results-only equivalence. Future production expectations are not
inferred from current results. Type-2 classification remains observation-only.

The preserved baseline executable is the clean Phase 3 build from `1cb7b81`,
SHA-256 `c0f92dc3d31be954f98418d5914970af1190d44fa691661319bdf47c0c78e491`.
The Phase 4.0 candidate is an uncommitted working-tree build based on `6538ed7`;
its executable SHA-256 is
`fd33b41a1dd875b9856d88ced97cf410fbeae4825f64663396879312c06aa8f1`.
Its receipt and the audit record identify the executable and source state.
Ignored `build/phase4-baseline/` retains the baseline executable/receipt,
`audit.py`, `audit-report.json`, and per-case outputs. The final candidate receipt,
working-tree patch/new-file snapshot, and verification record are retained there
as well. The full 13-step Docker `make test` passed; the focused move-selection
suite passed again after strengthening the selected-parent assertion.

All 157 currently discovered fixtures were compared: 41 XML, 21 source, 75
policy, and 20 move-selection cases. Generated source/policy inputs were used
only for currently discovered cases. Normal JSON and annotated XML were
byte-identical between baseline and candidate. Opt-in diagnostics preserved
ordinary results, Type-1 records and ordering, and all other existing diagnostic
evidence; normal and results-only ordinary results agreed. Every correspondence's
`current_result` agreed with its selected match kind and endpoint pair.

The inventory has 24 unique Type-2 observations: 13 ambiguous for insufficient
context, nine relocated across files, one relocated across a stable sibling,
and one stationary in its anchor interval. Of the 18 currently selected Type-2
pairs, six have positive relocation evidence and twelve are ambiguous:

| Existing selection | Count | Observation and review |
| --- | ---: | --- |
| Four policy transfers | 4 | Cross-file relocations remain supported |
| Source `reorder_function_specifiers` | 1 | Same-file crossed-sibling relocation remains supported |
| `coherent_type3_parent_over_partition` | 1 | Explicit cross-file relocation remains supported |
| XML positives listed in the Type-2 handoff | 10 | Insufficient location context; normalization/mechanics examples, not independently established historical moves or false moves |
| `unique_parent_over_repeated_children`, `coherent_type2_parent_over_partition` | 2 | Hierarchy mechanics without positive location context |

The twelve ambiguous selections would become ineligible under the proposed
gate; that is a policy-impact estimate, not a measured accuracy gain. Four
additional relocated Type-2 child observations lose selection to containing
Type-2 functions and are not four missed historical moves. The adjacent local
replacement guard is stationary. The six XML Type-2 guards remain zero-move
cases with no unique Type-2 observations.

### Historical coverage and remaining acceptance gap

Before inspecting detector output, a bounded convenience sample was reviewed
from local Notepad++ history. It is exploratory and not a representative or
held-out precision/recall benchmark:

- `c5094fee8b08e306fb030c14b265edee5c2beff4` (parent
  `d9c24ad78f17adc6b16d30111b126b2e7513d8fa`): fourteen renamed switch handlers
  transfer between `NppCommands.cpp` and `NppBigSwitch.cpp`; two reviewed
  `TabBar.cpp` call edits remain in place. All fourteen handlers have selected
  body representatives; no selected move touches those TabBar edits. The 31
  Type-1 output groups are fragments/groups, not 31 independent history events.
- `c9003fa603292f9ba6f463ac103e69a6de3dcfdc` (parent
  `7b7e6213a71757bfaba6a0f460b166b0b865a438`): identifier changes in `focusClient`
  and `toggleTb`/`toggleWidget` remain in place. Two repeated Type-1 groups contain
  return/type-name tokens with mixed or unresolved context. They do not justify
  an invented group-level false-positive count.

Both comparisons preserve ordinary baseline output. Crucially, neither exposes
any unique Type-2 correspondence: handler bodies are exact, case labels are
outside Type-2 eligibility, and srcDiff exposes finer changes for the renamed
methods. **These initial samples did not establish historical Type-2 classification
coverage.** The follow-up below adds exposed positives and limited negative
evidence; upstream exposure failures remain limitations rather than changed
oracle labels.

Ignored `benchmark-results/correspondence-phase4-history/` retains
`source-review.json`, source snapshots/diffs, `evaluate.py`, `manifest.json`,
`summary.json`, srcDiff XML, and both detector outputs. The manifest records
revision/file hashes, commands, and executable hashes. These exploratory runs
use fragment granularity; product-default historical validation remains needed.
Snapshots use matching relative filenames beneath separate revision roots.

With the retained baseline and local repository available, repeat the audits
from the parent workspace using:

```bash
./bin/srcml-dev-shell python3 /workspace/srcMove/build/phase4-baseline/audit.py
./bin/srcml-dev-shell python3 /workspace/srcMove/benchmark-results/correspondence-phase4-history/evaluate.py
```

The scripts regenerate raw reports/outputs; source review and interpretation
remain independent human-readable evidence, not labels regenerated from output.

### Default-granularity historical follow-up

After committing the observation-only implementation as `8a24935`, a bounded
source-led search evaluated 14 repository/commit subsets: three SQLite, six
OpenCV, and five Notepad++ comparisons. Thirteen completed; one failed in
srcDiff. This convenience sample is exploratory, not held out or representative.
Selection used source history and diffs before detector output; the two exposed
Notepad++ declaration negatives were subsequently reviewed by a separate reviewer
who inspected source only. That retrospective targeting is a sampling limitation.
All runs use the product default statement granularity and real logical paths.

| Source-reviewed case | Observed evidence | What this establishes |
| --- | --- | --- |
| SQLite `3d006d0d00cc79bb8cfb9dc63f2db2acb080ac82`: `ext/misc/analyze.c` becomes `ext/misc/diskused.c` | 41 unique Type-2 correspondences, all `relocated/different_file`; 14 selected | The three pre-reviewed functions `analysisReset`, `analysisPrepare`, and `analysisPercent` become their `diskused` counterparts and are each selected as Type-2. No loss among these three. This is file-rename movement, not internal reordering. |
| Notepad++ `fd02b9df00a129b8e6c318c8d5f101c5a7f2a340`: `NppLocalization.cpp` becomes `localization.cpp`, `Notepad_plus` methods become `NativeLangSpeaker` methods | 12 unique Type-2 correspondences, all `relocated/different_file`; nine selected | All five pre-reviewed methods (`changeStyleCtrlsLang`, `changeShortcutLang`, `changeShortcutmapperLang`, `searchDlgNode`, `changeDlgLang`) are selected Type-2 moves. No loss among these five; nested unselected pairs are not additional missed moves. |
| Notepad++ `682a8edafa2048e0cf7d88060fda772e2ed0f30b`: `CFile` becomes `Win32_IO_File` | Three unique Type-2 declarations, all `ambiguous/insufficient_context`, none selected | Source-only independent review confirms `Read/read` and `Write/write` remain public declarations in the same order at lines 52–53. Their non-move output agrees with the review, but the classifier cannot establish stationarity. The copy-assignment declaration changes access section and order; movement versus restructuring remains unresolved. |
| SQLite `c799c15dbef70dd8ee63be2c4b77ebeacce1df00` (`ext/qrf/qrf.c`) and `3b440ce573e6567691dac106a961e4d658b09c03` (`src/select.c`) | Zero candidates and zero moves for the reviewed in-place renames | Fine-grained srcDiff edits do not exercise Type-2 classification. They are not evidence of improved classifier precision. |
| Six OpenCV subsets, including five edits-in-place and the exact `calibrationMatrixValues` transfer at `99fc5739130dbbbe4010545457ad11666cfcc0cb` | No Type-2 observations; the transfer is selected as one whole Type-1 function, negative subsets report no moves | Confirms the exposure limitation on another repository; does not add Type-2 acceptance coverage. Full commit/file inventory is retained in the source review. |
| Notepad++ `c9003fa60` and `e59774add`, rerun at default granularity | No Type-2 observations or selected moves; the latter retains 17 ambiguous Type-1 observations | These remain exposure controls, not Type-2 positives/negatives. |
| Notepad++ `f127ba02d`, `NppDarkMode.cpp` | srcDiff exits with SIGSEGV after an encoding/BOM parser error | Upstream failure retained with stderr; no detector conclusion and no encoding rewrite to manufacture an input. |

All thirteen successful comparisons preserve baseline ordinary results; XML
byte equality was additionally checked for the seven SQLite/Notepad++ pairs.
The baseline and observation-only executable hashes are unchanged from the
fixture audit above. No production classifier gate was enabled in these runs.
The eight reviewed selected functions across two file transfers have positive
relocation evidence; this establishes correspondence/location support, not the
output of an unimplemented selection policy or population recall. Two reviewed
stationary declarations already remain unselected under the baseline, so these
results do not demonstrate a new precision gain.

**At this follow-up stage, acceptance remained limited:** no reviewed same-file
edited move exercised the proposed gate, no reviewed historical false move was
demonstrated to be removed, and the changed-access declaration was unresolved.
The gate trial below supplies same-file evidence and finds a real recall loss. Do not interpret the
absence of observed regressions in these easy cross-file positives as proof of
improved historical analysis. Keep production behavior unchanged until a bounded
comparison addresses those tradeoffs; retain the reviewed cases for that trial.

Evidence is retained under ignored
`benchmark-results/correspondence-phase4-history-next/{sqlite,notepadpp,opencv}/`.
Each contains source review, exact revisions/files, snapshots/diffs, commands,
input/executable hashes, outputs, and conclusions or summary. Source labels are
not regenerated from classifications. The SQLite positive labels and the two
Notepad++ declaration negatives received independent source review.

From the parent workspace, the retained scripts reproduce the runs:

```bash
./bin/srcml-dev-shell python3 /workspace/srcMove/benchmark-results/correspondence-phase4-history-next/sqlite/evaluate.py
./bin/srcml-dev-shell python3 /workspace/srcMove/benchmark-results/correspondence-phase4-history-next/notepadpp/evaluate.py
./bin/srcml-dev-shell python3 /workspace/srcMove/benchmark-results/correspondence-phase4-history-next/notepadpp/compare_baseline.py
./bin/srcml-dev-shell python3 /workspace/srcMove/benchmark-results/correspondence-phase4-history-next/opencv/evaluate.py
```

### Type-2 gate trial: same-file recall regression

The next comparison enabled the proposed gate only in a detached, ignored
worktree at `build/type2-gate-trial/source`, based on `9efc4eb`. Production source
and its executable remain unchanged. The trial classifies unique Type-2 pairs
before selection, uses the shared eligibility gate, and removes the adjacent
replacement heuristic. It also reserves both IDs of every unique Type-2 pair
from alternate Type-3 matches. This identity reservation is independent of
location, applies to IDs rather than spans, and intentionally strengthens
correspondence precedence; it is an experimental policy change, not an adopted
feature. Repeated normalized groups retain their existing policy.

**Do not adopt this trial: it loses a source-reviewed real Type-2 move.** SQLite
`c799c15dbef70dd8ee63be2c4b77ebeacce1df00` moves the floating-point formatting
block in `src/shell.c.in` from after unchanged line-limit/quote handling to
before it. The block's field and string literals change from `zRealFmt` /
`--realfmt` to `zFpFmt` / `--fpfmt`. A separate source-only review confirms the
reorder; line displacement alone is not the evidence. The comparison registers
`.in=C` through srcDiff's existing `--register-ext` option, preserving the actual
source bytes and shared logical filename. srcMove uses default granularity.

Production selects the block as one Type-2 move. The shared classifier calls
both it and its nested declaration `stationary/same_anchor_interval`; the trial
therefore emits zero moves. `region_filter.cpp` currently collects common
`decl_stmt` anchors only. The crossed common conditionals do not divide the
interval, and equal ancestry plus this coarse interval is mistaken for proof
of stationarity. This is a context/classification error, not poor normalized
matching or a threshold problem.

The new accepted output contract
[`type2_reorder_across_common_conditionals`](cases/type2_reorder_across_common_conditionals.xml)
is a small source-generated reduction of that scenario, with a common function,
two common conditional siblings, and one reordered/renamed conditional. It
requires the whole Type-2 move and normal/results-only equivalence. Its oracle
comes from source order; it deliberately does not canonize the current incorrect
stationary diagnostic. Production passes it; the trial fails it.

A comparison of the pre-existing 157 fixtures plus 14 historical inputs changed
12 cases: nine XML cases lose ten contextless Type-2 pairs, two selection
mechanics cases lose their Type-2 parent (one exposes a repeated Type-1 group
instead), and the SQLite historical reorder is lost. The previously reviewed
cross-file positives are preserved. This demonstrates why counting fewer moves
is not an acceptance criterion. The subsequent 21-contract benchmark reports
production 21 passes and trial 18 passes / three semantic misses (the two
mechanics cases and the new real-reorder reduction). No golden was weakened to
accept those misses.

A separate source-selected same-file probe adds useful positive evidence:
OpenCV `9ba4bb7355` moves/refactors calibration code, and all five currently
selected Type-2 pairs remain selected in the trial, including a normalized
declaration crossing a stable sibling. Of three prespecified edited declaration
targets, `_dpdk` is detected while `_dpdr` and `_dpdt` remain unresolved normalized
groups. Those two are pre-existing matching limitations, not gate regressions.
Three additional OpenCV/SQLite probes preserve their outputs, including an
existing zero-result SQLite helper extraction. Two Notepad++ probes expose only
Type-1 evidence; one preference-dialog extraction remains an existing miss.
These convenience probes are not a population recall estimate.

The identity-reservation change also has a concrete benefit in a synthetic
counterexample: a stationary unique Type-2 pair can currently lose to a spurious
Type-3 alternate partner after the adjacency filter rejects it. Four isolated
trial checks cover both endpoint directions and controls without the Type-2
counterpart. Reservation prevents the false alternate while each control still
selects its legitimate Type-3 match. This does not justify accepting the separate
SQLite recall regression or establish a historical precision gain.

The next focused work is to capture positive order evidence from substantial
common non-declaration siblings before making Type-2 output depend on the
classifier. Reuse the streaming context representation and classifier; test
unique/repeated/mixed conditionals and preserve existing declaration anchors.
Do not turn all context-free pairs back into moves, introduce line-distance
rules, or treat the known reorder as an acceptable non-move.

Retained evidence:

- `build/type2-gate-trial/`: detached worktree, `trial.patch`, build receipt,
  executable/patch hashes, `compare.py`, per-case outputs and `comparison.json`.
- `benchmark-results/correspondence-type2-gate-trial/`: SQLite source-reviewed
  reorder, reduced source pair, bounded same-file probes, source reviews,
  manifests, commands, and baseline/trial outputs. The SQLite source-only
  independent review is retained under `opencv-sqlite/`.
- `benchmark-results/move-selection/type2-gate-recall-review/`: comparison of
  production and trial on the 21 output contracts.

`make test-move-selection` passes for production (15 unit tests, 21 contracts).
The four reservation/control checks pass only in the isolated trial; its checker
is at `build/type2-gate-trial/source/moveSelectionBench/type2_reservation_trial/`.
No production algorithm, VERSION, or expected output was changed in this slice.

## Retained Notepad++ evaluation

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

The adopted srcMove 0.5.0 build at commit
`1cb7b81b75c8192ac6caacbb14be4acb124235fe` was then rerun against that exact
retained `shadow-srcdiff.xml`; the snapshot and srcDiff hashes above remained
unchanged. The release executable has SHA-256
`c0f92dc3d31be954f98418d5914970af1190d44fa691661319bdf47c0c78e491`
and build receipt
`build-receipt-sha256-98c15680e3d54bb0b6b4f7233ec55e6027601ea26cecb0cfa05c7ee58e80513a`
(Clang 18.1.3, C++17, srcReader
`b4b2a88fca88e5dae40fd181f2666961e3ce01dc`). The receipt records a clean
srcMove checkout at that commit.

The same 17 unique Type-1 correspondence keys remain
`ambiguous/insufficient_context`. All 12 former Type-1 moves transition from
`move` to `not_move`; the other five remain `not_move`. Adopted normal output
contains zero move groups (`type1: 0`, `type2: 0`, `type3: 0`), with no
remaining move outside the unique Type-1 diagnostic decisions. Normal and
`--results-only` ordinary JSON are byte-identical. This is evidence for the
conservative fallback under missing context, not evidence that the 17
correspondences are stationary.

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
