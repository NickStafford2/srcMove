# Results schema 3 contract

Status: proposed implementation contract, October 16, 2026. Step 1 defines the
format; the executable still emits results schema 2 and diagnostics schema 4.
The examples are synthetic format illustrations, not detector observations or
experimental evidence. Implementation and migration remain later steps.

This contract organizes srcMove output around atomic move groups and output
items. The migration must preserve selected evidence, matching and selection behavior, XML
annotations, benchmark scoring units, and sequence eligibility. Current runtime
consumers will require schema 3; no schema-2 compatibility adapter is planned.
Frozen research evidence and its version-specific readers remain unchanged.

The vocabulary follows thesis Chapter 4, Section 4.8. This document owns the
proposed software contract; the thesis will describe the implemented contract
after migration. See [current architecture](../../architecture.md) for verified
schema-2 behavior. [schema.json](schema.json) defines structural constraints;
the invariants below also require semantic validation.

## Document structure

All fields below are required except `diagnostics`. Unknown properties are
rejected in versioned contract objects. JSON object order is insignificant.

| Field | Meaning |
| --- | --- |
| `results_schema_version` | Integer `3`. |
| `configuration` | `min_granularity: statement\|fragment` and `sequence_policy: ordered_adjacent_v1`. Records effective settings, without claiming a source-to-binary binding. |
| `xpath_context` | `document: input_srcdiff` and `namespaces`, a nonempty prefix-to-URI mapping. Every published XPath uses these bindings and addresses the input srcDiff XML. |
| `summary` | Result counts and explicitly named content-relationship histograms. |
| `output_items` | User-facing atomic or sequence move groups, referencing canonical atomic evidence. |
| `atomic_move_groups` | Selected proposal evidence, including uncertainty and endpoints. |
| `pipeline_statistics` | Collection and processing-group counts, distinct from result counts. |
| `diagnostics` | Optional diagnostics schema `5`; absence means not recorded. |

Do not embed generated timestamps, Git revisions, executable checksums, absolute
artifact paths, or historical judgments here. Execution receipts own those facts.
Program release versions and results/diagnostics versions are separate decisions.

## IDs and endpoints

An atomic group has a nonempty string `id`, equal to its existing XML `mv:id`.
Preserve current IDs during migration. An atomic output item's ID is
`item:<group-id>`; a sequence output item's ID is `sequence:<first-member-id>`.
Output-item and group IDs are different logical namespaces. APIs must name the
requested entity explicitly rather than searching both collections for the first
match. IDs identify evidence only within this result document, not continuing
constructs across commits. They need not be identical across executions.

Each group contains nonempty `original` and `modified` endpoint arrays. An
endpoint has:

| Field | Meaning |
| --- | --- |
| `candidate_id` | Nonnegative integer from the collector registry; result-local and independent of array position. |
| `revision_file` | Revision-specific source path, or null when unavailable. Never substitute a combined `old\|new` srcDiff filename. |
| `xpath` | Nonempty absolute XPath into the input srcDiff XML. |
| `construct` | Collector's qualified construct name, or null when unavailable. |
| `role` | `diff_wrapper`, `single_child_wrapper`, `multi_child_wrapper`, or `structural_child`. |
| `raw_text` | Exact retained candidate text; no normalization for presentation. |

Revision side is determined by the containing array. For diagnostic candidates,
it is an explicit `revision: original\|modified` field. Candidate IDs must be
unique across selected endpoint occurrences and keep the same meaning with or
without diagnostics. Missing context uses null, not empty strings or zero IDs.
Candidate ID zero is valid.

The native writer patches attributes while retaining XML structure. Selected
input XPaths must also resolve to their annotated endpoint in native XML output;
verify this property rather than assuming it for a transformed viewer document.
Viewer normalization owns its separate node IDs and remapping. Unselected
diagnostic XPaths must be resolved against input XML before viewer transformation.
Results-only mode still supplies input XPaths and all ordinary evidence.

Do not infer partner pairs by zipping arbitrary endpoint arrays. Only a
`selected_pair` group establishes the detector's particular one-to-one association.

## Ordinary atomic evidence

Every atomic move group requires `id`, `content_relationship`, `original`,
`modified`, `correspondence`, `copy_provenance`, `identity_evidence`,
`location_evidence`, and `selection`.

### Content and correspondence

`content_relationship` is `type1`, `type2c`, or `type3`, with current matching
semantics. It does not establish relocation or historical identity.

`correspondence` contains `status` and `basis`:

| Status | Basis | Interpretation |
| --- | --- | --- |
| `selected_pair` | `pair_proposal` or `exact_neighbor_correspondence` | One selected original/modified partner association. Requires one endpoint per side and neither copy nor unresolved-residual policy. This is a detector decision, not an independent historical judgment. |
| `unresolved_partners` | `repeated_exact_group` or `unresolved_exact_residual` | Retained alternative endpoint sets. A residual can be one-to-one and still unresolved. |
| `copy_source_set` | `continuing_source_copy` | Retained possible continuing sources and added destinations. Even a singleton source set uses this status; it does not claim source relocation. |

Copy provenance is orthogonal to content and cardinality:
`copy_provenance.status` is `continuing_source_copy` or `not_established`.
The former requires `copy_source_set`; the latter does not prove copying absent.
Original endpoints of a copy group are supported continuing origins; modified
endpoints are added destinations. Continuations in place are excluded from the
destination array. A group does not assign a contributing source to each copy.

Preserve the existing typed copy/residual flags through the selected-group and
writer structures. Never recover these statuses by parsing `selection.reason`
or treating `copy_or_repeat` as a correspondence classification.

### Identity evidence

`identity_evidence` contains `status` and nullable `reason`. Status is
`exact_content`, `corroborated`, `tentative`, or `unassessed`; diagnostics also
allow `contradicted`. `exact_content` is the public rename of current `exact`:
Type-1 content equality, including unresolved groups. It does not mean that
partners are resolved or that independent continuing-name evidence was checked.

Recorded reasons are `continuing_name_corroborated`,
`uncorroborated_declaration`, and, in diagnostics only,
`continuing_name_conflict`. Use null when no reason is recorded. Selected
contradicted pairs remain prohibited by the existing output policy.
The status/reason mapping is exact: `corroborated` uses
`continuing_name_corroborated`, `tentative` uses `uncorroborated_declaration`,
and `contradicted` uses `continuing_name_conflict`. `exact_content` and
`unassessed` use null. Type-1 groups use `exact_content`; other relationships
do not.

### Location evidence

Concise location evidence belongs in ordinary results because content equality
and displacement are different questions. Full endpoint context stays optional.
The object is a tagged union:

| `scope` | Additional fields | Meaning |
| --- | --- | --- |
| `pair` | `classification`, `reason`, `observations`, `carried_by_parent`, `parent_pair` | Existing classifier assessment for the selected pair, preserved from its decision. |
| `group` | `status: group_relocation_evidence` | Existing existential relocation gate passed for an unresolved exact group. It does not establish displacement for every possible pairing. |
| `not_assessed` | `reason: continuing_source_copy` | Copy policy did not require a group displacement assessment. Do not invent one. |

A pair classification is `stationary`, `relocated`, `restructured`, or
`ambiguous`. Current selected ordinary pairs must be move-eligible under the
existing policy; diagnostics can contain all four classifications. Reasons are
the current `movement_classification_reason` values in
[movement_classifier.hpp](../../../src/movement_classifier.hpp).

Current pair eligibility requires `classification: relocated` and
`carried_by_parent: false`. In particular, `restructured` is not a selected
ordinary pair under the current policy.

Pair `observations` contains `file`, `semantic_container`, `anchor_interval`,
`relative_order`, and `ancestor`, preserving existing observations. Values are:

- file: `same`, `different`, `unknown`;
- semantic container: `same_mapped`, `different_mapped`, `unknown`;
- anchor interval: `same`, `different`, `crossed`, `unknown`, `same_within_parent`;
- relative order: `unchanged`, `crossed_stable_sibling`, `unknown`;
- ancestor: `same`, `wrapped`, `unwrapped`, `incompatible`, `unknown`.

`carried_by_parent` is boolean. `parent_pair` is null unless parent carrying is
established; otherwise it contains `original_candidate_id` and
`modified_candidate_id`. This describes the classifier's parent relation, not
a synthetic selected parent move. Do not claim those parent candidates are
selected. Production selected pairs cannot be parent-carried under current
eligibility policy; diagnostic pairs can be.

### Selection evidence

`selection` contains `matching_weight_milli`, `utility`, `matched_units`, and
`reason`. The first three directly preserve current `confidence_milli`,
`selection_utility`, and `matched_units`; they are nonnegative integers, with
matching weight bounded by 1000. None is a correctness probability.

Reasons retain `greedy_utility`, `exact_neighbor_correspondence`,
`continuing_source_copy`, `unresolved_exact_residual`, and `descendant_bundle`.
This field describes selection, not a substitute for correspondence or copy
evidence. `descendant_bundle` remains allowed although current weights make
that preference unreachable; the format does not assert that it occurred.
Copy, residual, and exact-neighbor reasons must agree with the corresponding
typed correspondence basis in both directions. The exact-neighbor basis is
Type-1 only. These consistency checks must not replace carrying the typed
evidence through the producer.

`matched_units` is the existing heuristic coverage value, not universally a
token count or LCS length. Candidate units prefer normalized tokens, then
normalized lines, then non-whitespace characters; repeated groups and Type-3
proposals apply their existing aggregation/scaling. Utility can also include
identity penalties. Do not assert `utility = weight * matched_units` generally.

## Output items and sequences

An atomic output item has exactly `id`, `kind: atomic_move_group`, and a
singleton `member_group_ids` array. A sequence output item has `id`,
`kind: sequence_move_group`, ordered `member_group_ids` with at least two
members, and `sequence`:

```
sequence.policy = ordered_adjacent_v1
sequence.original = { revision_file, parent_id,
                      first_child_ordinal, last_child_ordinal }
sequence.modified = { revision_file, parent_id,
                      first_child_ordinal, last_child_ordinal }
```

Sequence context fields are nonempty strings and positive ordinals. Each side's
span length equals member count. Members are Type-1 `selected_pair` groups
with structural-child endpoints, common per-side file and parent, consecutive
sibling ordinals, reliable context, and disjoint spans in both revisions.
These eligibility facts require collector/XML checks in addition to JSON
validation. An unresolved one-to-one residual cannot enter a sequence.

Each atomic group belongs to exactly one output item. Member order preserves
the actual paired order in both revisions. Output items do not duplicate endpoint
texts, XPaths, content classifications, identity assessments, or selection
scores. Resolve them through members. A sequence's content relationship is
Type-1; an atomic item's relationship is its member's. Do not invent aggregate
confidence or promote the first member's identity assessment to the whole run.
One sequence does not establish one developer action or an enclosing AST move.

## Counts and processing statistics

All count fields are nonnegative integers. Empty results retain mandatory
arrays and complete zero-valued histograms.

| `summary` field | Definition |
| --- | --- |
| `output_item_count` | Length of `output_items`. |
| `atomic_move_group_count` | Length of `atomic_move_groups`. |
| `sequence_move_group_count` | Number of sequence output items. |
| `pair_capacity` | Sum of `min(len(original), len(modified))` over atomic groups, including copies and unresolved groups. It chooses no pairing. |
| `endpoint_count` | Sum of both endpoint-array lengths over atomic groups. |
| `atomic_content_relationships` | Histogram counting atomic groups by `type1`, `type2c`, `type3`. |
| `output_content_relationships` | Histogram counting output items by their derived relationship. |

The output-item count also equals atomic-group count minus the sum of
`member_count - 1` over sequences. This is a validation identity, not a second
stored count. None of these counts independently measures confirmed historical
moves. No field counts the Cartesian product of unresolved alternatives.

`pipeline_statistics` contains:

- `srcdiff_region_count`: current collection `regions_total`;
- `registered_candidate_count`: registry `total_record_count()`, including
  inactive records;
- `active_candidate_count`: registry `active_candidate_count()`;
- `grouped_candidate_entry_count`: current `candidates_total`, the sum of
  endpoint entries in final processing groups, not all collected candidates;
- `processing_group_count`: current `groups_total`;
- `processing_group_kinds`: complete histogram of `move_1_to_1`, `moves_many`,
  `delete_only`, `insert_only`, `copy_or_repeat`, `ambiguous`.

These processing groups include one-sided groups and are not the output-item
collection. Preserve their categories; `copy_or_repeat` also covers copy and
residual policy cases and is not a pure cardinality label. Histogram totals
equal `processing_group_count`. The registry counts deliberately distinguish
candidate inventory from the old grouped-entry statistic.
Registered count is at least active count, which is at least selected endpoint
count. Registry candidate IDs are below registered count; they are not indices
into the selected endpoint or diagnostic arrays.

## Diagnostics schema 5

When requested, `diagnostics` requires `schema_version: 5`, `candidates`,
`correspondences`, `type3_comparisons`, and `type2b_groups`. Empty arrays mean
recorded with no entries. Omission of the entire object means not recorded.
No diagnostic observation contributes a new atomic group or production count.
Diagnostics remain a trace of the implemented retrieval/classification paths,
not an exhaustive delete-by-insert comparison or a truth oracle.

### Candidate inventory

Inventory covers active registry candidates, not inactive aliases. Each record
requires `candidate_id`, `revision`, `selected_group_id`, `endpoint`,
`type3_eligible`, `line_units`, and `token_units`.

For a selected candidate, `selected_group_id` points to its owning atomic
group and `endpoint` is null: resolve the endpoint there. For an unselected
candidate, `selected_group_id` is null and `endpoint` contains the ordinary
endpoint object. Its `candidate_id` must equal the inventory ID. This avoids
duplicating selected source bodies while retaining the full active inventory.
`type3_eligible` records the existing collector predicate; it does not mean a
pair was retrieved or compared. Unit counts are the actual normalized sequence
lengths, separate from selection `matched_units`.

### Classified correspondences

Each record has `id`, `original_candidate_id`, `modified_candidate_id`,
`content_relationship`, `identity_evidence`, `location`, `original_context`,
`modified_context`, `verified_partner_counts`, and `selection`.

`id` is a nonempty result-local string, explicitly serialized rather than
invented from viewer array position. Endpoint references resolve to the active
candidate inventory with matching revision sides. `location` is the pair-scope
location object defined above, including parent-pair linkage when applicable.

Contexts preserve current endpoint diagnostic fields: `revision_file`,
`semantic_container_id`, `semantic_container_label`,
`previous_common_anchor_id`, `next_common_anchor_id`, `meaningful_ancestors`,
`ancestor_summary_interpretable`, `structural_region_id`,
`structural_region_mapped`, `common_sibling_prefix_count`,
`common_sibling_suffix_begin`, and `anchor_region_id`. Unavailable strings are
null; arrays, booleans, and recorded counts retain their actual values.

`verified_partner_counts` is null outside Type-3. For Type-3 it contains
`original` and `modified`, positive incident verified-edge counts before
selection. Competing edges are not unresolved selected-group semantics.
Every verified Type-3 comparison has exactly one corresponding Type-3 classified
correspondence with the same candidate pair. The partner counts are recomputable
as degrees over those verified comparisons; duplicate pair records are invalid.

`selection` has `status: selected_pair|not_selected_pair` and nullable
`selected_group_id`. The former requires the exact selected atomic
`selected_pair` of the same content relationship and candidate IDs. The latter
has null group ID, but either candidate can still belong to a different selected
group, or both can occur in an unresolved group. Candidate ownership remains
available through the inventory. Unlike the old `not_move` label, this status
makes no claim of stationarity. Do not mark an unresolved one-to-one group as
a selected partner pair merely because cardinalities match.

The current implementation does not retain a complete per-proposal rejection
reason. Do not fabricate reasons from a false selection status. Detailed
rejection traces are a separate instrumentation decision, not a requirement of
this migration. Parent candidate references must resolve in the active
inventory: the existing parent policy chooses parents from classified exact
decisions over active candidates. Do not publish dangling references or assume
that the referenced parent pair was selected.

### Type-3 verification and selection

Each comparison has `id`, original/modified candidate IDs, `verification`, and
`selection`. Its verification object has `status`, nullable `reason`, and
`lines`/`tokens`, each with `common` and `maximum`. Maximum is a nonnegative
length. Common is null when not evaluated; otherwise it is a nonnegative
observed LCS length no greater than maximum.

| Current outcome | Verification status | Verification reason | Selection status |
| --- | --- | --- | --- |
| `ambiguous_type2c` | `not_evaluated` | `ambiguous_type2c` | `not_applicable` |
| `below_threshold` | `below_threshold` | null | `not_applicable` |
| `selected` | `verified` | null | `selected` |
| `selection_rejected` | `verified` | null | `not_selected` |

Selection also has nullable `selected_group_id` and `reason`; reason is null
unless later instrumentation actually records one. A selected comparison joins
the exact selected Type-3 pair. `not_selected` does not imply overlap rejection:
the current category also includes output-policy rejection. Diagnostic LCS
observations do not replace the existing verifier's decision or threshold logic.

### Type-2b observations

Each record has `id`, `content_relationship: type2b`, `observation_only: true`,
nonempty `original_candidate_ids` and `modified_candidate_ids`,
`blind_only_pair_count`, and nullable `location`.

The lists are a blind equivalence group, and can also contain stronger
consistent pairs. `blind_only_pair_count` excludes those stronger pairs; do not
present the Cartesian product as exclusively blind-only correspondences.
Cardinality is derived from list lengths, never called `ambiguous` merely
because a side has multiple entries. A nonnull location contains only
`classification` and `reason` and requires a unique one-to-one blind-only pair.
No Type-2b observation enters production content histograms.

## Validation and migration gates

Structural validation must reject schema 2 at live boundaries, malformed
endpoints, invalid enums, missing mandatory objects, and unknown properties.
Semantic validation must additionally enforce:

1. Unique group, output-item, candidate, and diagnostic record IDs in their
   respective namespaces; valid sides and complete reference resolution.
2. Output items partition atomic groups exactly once; sequence membership,
   ordering, Type-1 relationship, selected-pair status, file context, and span
   lengths are consistent.
3. Summary values and both histograms are recomputable from canonical data.
4. Copy, residual, correspondence, identity, and location tagged states agree.
   Type-1 groups have `exact_content`; other production relationships do not.
5. Diagnostic candidate ownership and pair-selection links match the actual
   production endpoints, including unresolved singleton residuals.
6. Type-3 measurement/selection states agree and Type-2b remains observation-only.
7. XML-level checks independently establish XPath resolution, endpoint text,
   atomic annotations, disjoint spans, and actual sequence eligibility. JSON
   alone cannot prove structural adjacency or detector correctness.

Before implementation, capture representative schema-2 outputs. Afterward,
compare normalized evidence rather than JSON bytes: atomic endpoints/text,
content relationships, selection values, identity evidence, sequence membership,
and XML semantics. Added production evidence must come from existing decisions
and typed state, with no new matching search. Instrumentation must not affect
selection, IDs, or candidate allocation. Standard evidence must agree between
normal, results-only, and diagnostics-enabled modes.

Fresh history states and viewer artifacts must invalidate incompatible storage
and fingerprints. Benchmark oracles continue scoring atomic groups. Frozen
schema-2 studies, hashes, adjudications, and version-specific appendix readers
are not rewritten. New schema-3 examples get separate build identities and
receipts when executed; the synthetic examples here are not those captures.

## Implementation source map

| Contract fact | Existing implementation / change needed |
| --- | --- |
| Public schema and output writer | `src/summary.hpp`, `src/util/json_writer.hpp`; replace public shape after this design step. |
| Counts and active candidate inventory | `src/pipeline.cpp`; preserve count meanings and add registry inventory counts. |
| Copy/residual status | `src/move_registry/pending_group.hpp`; preserve typed flags through `content_groups.hpp` and writer tags rather than discarding them. |
| Pair location and identity | `src/move_registry/content_group_builder.cpp`, `src/movement_classifier.hpp`; retain existing decision evidence on selected groups. |
| Endpoint metadata | `src/move_candidate.hpp`, `src/writer/annotation_plan.cpp`, `src/writer/annotation_writer.cpp`; retain candidate identity and revision file. |
| Ordered aggregation | `src/move_sequences.cpp`; retain eligibility, replace reporting endpoint copies with references. |
| Diagnostic outcome meanings | `src/move_registry/selection_diagnostics.hpp`, `content_group_builder.cpp`; split existing observed states without inventing rejection reasons. |
| Runtime readers | History admission/retention, benchmark validation/oracles, and srcDiffVisual adapters migrate together after producer implementation. |

## Step 1 completion and later work

Step 1 delivers this contract, the structural schema, illustrative examples,
and example validation. Step 2 implements the producer; later steps migrate
consumers, run semantic equivalence and integration checks, and update the
authoritative thesis. No production schema constants or thesis claims change
merely because this proposal exists.

### Worked format examples

All numbers, paths, and IDs in these files are illustrative. Selection values
are not measured results; the examples have no execution receipts and must not
be substituted for retained thesis evidence.

| Example | Boundary illustrated |
| --- | --- |
| [Empty](examples/empty.json) | Complete zero counts and mandatory empty arrays. |
| [Selected pair](examples/selected-pair.json) | One atomic group, one output item, ordinary pair evidence. |
| [Unresolved group](examples/unresolved-group.json) | Multiple alternative endpoints without chosen pairings. |
| [Unresolved residual](examples/unresolved-residual.json) | Singleton endpoints do not establish resolved partners. |
| [Continuing copy](examples/continuing-copy.json) | Two possible continuing sources and one added destination. |
| [Ordered sequence](examples/ordered-sequence.json) | Five atomic groups represented by one sequence item. |
| [Mixed output](examples/mixed-output.json) | A sequence and an atomic item partition the selected groups. |
| [Tentative pair](examples/tentative-pair.json) | Type-2c pair selection preserves tentative identity evidence. |
| [Diagnostics](examples/diagnostics.json) | Candidate ownership, selected and unselected pairs, parent carrying, Type-3 verification states, and observation-only Type-2b. |

From the workspace root, check cross-record invariants and malformed
counterexamples in Docker:

```bash
./bin/srcml-dev-shell python3 srcMove/doc/plans/results_schema_v3/check_examples.py --self-test
```

This checker uses only the Python standard library. It expects structurally
valid input and does not replace a JSON Schema validator. A Draft 2020-12
validator should apply [schema.json](schema.json) before production admission.
Neither structural nor cross-record checking establishes XML adjacency,
source correctness, or empirical detector behavior.
