# Results schema 3 contract

Status: Phase 3 consumer migration implemented and checked, October 16, 2026. The executable and
live consumers use results schema 3 and diagnostics schema 5. Verification
receipts distinguish current consumer checks from the historical Phase-2 run.
Examples are synthetic format illustrations, not detector observations.

The migration must preserve matching, selection, sequence eligibility, atomic
XML annotations, and benchmark scoring. Its purpose is to make those results
clearer through the thesis's atomic move groups and output items. Live consumers
will require schema 3; frozen studies and their version-specific readers remain
unchanged. See the [architecture](../../architecture.md) for the detector pipeline.

[schema.json](schema.json) links to the packaged runtime contract and defines structural constraints. Cross-record and XML
checks below supplement it; no JSON schema proves detector correctness.

## Start with the results

The writer should present fields in this order. Object order has no semantic
meaning, but results should be easy to find before technical context.

| Field | Purpose |
| --- | --- |
| `results_schema_version` | Integer `3`. |
| `summary` | Counts with explicit units and separate atomic/output content histograms. |
| `output_items` | Atomic or sequence move groups, referencing canonical evidence. |
| `atomic_move_groups` | Selected endpoints, correspondence, name assessment, location, and selection evidence. |
| `configuration` | Effective `min_granularity: statement\|fragment` and `sequence_policy: ordered_adjacent_v1`. |
| `pipeline_statistics` | Region and processing-group counts used for stage diagnosis. |
| `xpath_context` | Input document, explicit locator convention, and namespace bindings. |
| `diagnostics` | Optional schema `5`, containing candidate inventory and comparison details. |

Everything except `diagnostics` is required. Unknown properties are rejected in
versioned contract objects. Execution receipts own timestamps, binary/source
identities, artifact hashes, and historical judgments. Results schema versions,
diagnostics versions, and program releases are separate decisions.

## Atomic groups and output items

Each atomic group has `id`, `content_relationship`, `correspondence`,
`name_evidence`, nonempty `original` and `modified` endpoint arrays,
`location_evidence`, and `selection`.

An atomic group's ID preserves its existing XML `mv:id`. An atomic output item
has exactly `id: item:<group-id>`, `kind: atomic_move_group`, and a singleton
`member_group_ids`. A sequence item has `id: sequence:<first-member-id>`,
`kind: sequence_move_group`, ordered `member_group_ids`, and `sequence` context.
APIs distinguish item IDs from group IDs. All IDs are result-local; they do not
identify continuing constructs across commits or promise cross-run stability.

Output items partition atomic groups exactly once. They do not duplicate
endpoint bodies, content classifications, name assessments, or selection
scores. Resolve those through their members. An atomic item's content
relationship is its member's; a sequence's is Type-1. Do not infer an aggregate
confidence or promote the first member's evidence to the entire sequence.

### Endpoints

Each endpoint has `candidate_id`, `revision_file`, `xpath`, `construct`, and
`raw_text`. Candidate ID is a nonnegative registry ID, unique across selected
endpoint occurrences. It has the same meaning with or without diagnostics and
is never an index into a result array. ID zero is valid.

`revision_file` is the revision-specific path, or null when unavailable; do not
substitute a combined `old|new` archive filename. `construct` is the collector's
construct name (often a local name such as `expr_stmt`) or null. `raw_text` preserves the retained candidate
text. Revision side follows the containing array. Collector roles and registry
accounting belong in diagnostics, not mandatory ordinary endpoint objects.

### Content and correspondence

`content_relationship` is `type1`, `type2c`, or `type3` under the existing
matcher. It does not establish displacement or historical identity.

`correspondence` contains only `status`:

| Status | Interpretation |
| --- | --- |
| `selected_pair` | One detector-selected original/modified association, with exactly one endpoint on each side. |
| `unresolved_partners` | Alternative endpoint sets without selected individual pairings. A singleton residual can remain unresolved. |
| `copy_source_set` | Supported continuing origins and additional copy destinations, without assigning a contributing source to each destination. |

Copy origins' continuations in place are excluded from modified endpoints.
Even a singleton source set retains copy semantics; it does not claim source
relocation. Copy and unresolved-residual flags must survive the producer's
selected-group/writer transfer. Never determine correspondence by parsing
selection reasons or interpreting `copy_or_repeat` as partner certainty.

There is no separate `copy_provenance` object containing the same status. The
copy state and its endpoint semantics supply the interpretation; a selection
reason remains the actual algorithm trace, not another provenance claim.

### Name evidence

`name_evidence` is one value: `not_assessed`, `corroborated`, or `tentative`.
Diagnostics additionally allow `contradicted`. This records the existing
continuing-name assessment for the pair, not a judgment of historical identity.

| Current internal state/reason | Public value |
| --- | --- |
| `exact` / no independent pair name assessment | `not_assessed`; Type-1 equality is already stated by content relationship. |
| `unassessed` | `not_assessed`. |
| `corroborated` / `continuing_name_corroborated` | `corroborated`. |
| `tentative` / `uncorroborated_declaration` | `tentative`. |
| `contradicted` / `continuing_name_conflict` | `contradicted`, diagnostics only; the existing conflict veto still applies. |

Type-1 records use `not_assessed`. Do not claim their equality independently
corroborated names. This mapping changes presentation, not the existing name
policy, utility penalty, or selection decision. No redundant reason accompanies
the scalar value.

### Concise ordinary location evidence

Displacement evidence belongs in ordinary results, separately from content and
partner interpretation. Full pair observations and parent context stay in
diagnostics. Ordinary location is one of:

| Scope | Fields and meaning |
| --- | --- |
| `pair` | `classification: relocated` and the existing classifier `reason` for the selected pair. |
| `group` | `status: group_relocation_evidence`; the existing existential gate passed for an unresolved exact group, without choosing or relocating every possible pair. |
| `not_assessed` | `reason: continuing_source_copy` for copy policy, or `no_classified_pair` for a selected singleton with no retained pair assessment. |

Classified selected pairs are relocated and not parent-carried. Existing exact
fragment proposals can become singletons when repeated endpoints are reduced
after unique-pair classification. These proposals can be selected without a
classified pair; `no_classified_pair` exposes that limitation without inferring
relocation or changing selection. Removing the old invalid Debug assertion
makes this path behave like the existing Release build.

Do not
serialize constant `carried_by_parent: false` / `parent_pair: null` on every
ordinary pair. Diagnostics can report stationary, relocated, restructured, and
ambiguous pair classifications, with parent carrying preserved.

### Selection evidence

`selection` contains `matching_weight_milli`, `utility`, `matched_units`, and
`reason`, directly preserving current confidence, utility, coverage, and reason
values. Numerical values are nonnegative integers; weight is bounded by 1000.
They are heuristic ranking evidence, not probabilities.

Existing reasons are `greedy_utility`, `exact_neighbor_correspondence`,
`continuing_source_copy`, `unresolved_exact_residual`, and `descendant_bundle`.
Copy reasons must agree with copy interpretation. Residual reasons require
unresolved partners; unresolved singleton groups require the residual reason.
Exact-neighbor reasons require Type-1 selected pairs. These checks supplement
preserved typed state; they must not replace it.

`matched_units` is not universally a token count or LCS length. Candidate units
prefer normalized tokens, then normalized lines, then non-whitespace characters;
group aggregation and Type-3 scaling retain their current behavior. Utility can
include penalties, so do not assume `utility = weight * matched_units`.

### Sequence context

Sequence items require at least two Type-1 selected-pair members and:

```
sequence.policy = ordered_adjacent_v1
sequence.original = { revision_file, parent_id,
                      first_child_ordinal, last_child_ordinal }
sequence.modified = { revision_file, parent_id,
                      first_child_ordinal, last_child_ordinal }
```

Strings are nonempty and ordinals positive. Each span length equals member
count. Actual members must be reliable structural children with consecutive
sibling positions, common per-side file/parent, and disjoint spans in both
revisions, preserving paired order. XML/collector validation establishes these
facts; JSON references alone do not prove adjacency. An unresolved singleton
cannot enter a sequence. One sequence is not proof of one developer action or
an enclosing AST move.

## Counts and processing statistics

All counts are nonnegative integers. Empty output retains mandatory arrays and
complete zero-valued histograms.

| `summary` field | Definition |
| --- | --- |
| `output_item_count` | Number of output items. |
| `atomic_move_group_count` | Number of selected atomic groups. |
| `sequence_move_group_count` | Number of sequence output items. |
| `pair_capacity` | Sum of `min(original count, modified count)` over atomic groups, including copies and unresolved groups. |
| `endpoint_count` | Sum of both endpoint-array lengths over atomic groups. |
| `atomic_content_relationships` | Atomic-group histogram over `type1`, `type2c`, `type3`. |
| `output_content_relationships` | Output-item histogram over those relationships, counting a sequence once. |

Output count equals atomic count minus the sum of `member_count - 1` over
sequences. This is a validation identity, not another stored count. Pair
capacity chooses no partners. None of these counts independently measures
confirmed historical moves.

`pipeline_statistics` retains `srcdiff_region_count`,
`grouped_candidate_entry_count`, `processing_group_count`, and
`processing_group_kinds`. They map to current `regions_total`, `candidates_total`,
`groups_total`, and `group_kinds`. Grouped entries count candidate occurrences
in final processing groups, not every collected candidate.

Processing groups include one-sided groups. The complete histogram retains
`move_1_to_1`, `moves_many`, `delete_only`, `insert_only`, `copy_or_repeat`, and
`ambiguous`; its sum equals processing-group count. `copy_or_repeat` includes
policy-specific copy/residual cases and is not a pure cardinality label.
Registered/active inventory counts move to diagnostics.

## The existing locator convention

`xpath_context` requires `document: input_srcdiff`,
`convention: srcreader_file_units_v1`, and `namespaces`.

These strings are srcReader locators with XPath syntax, not universally absolute
XPaths into the XML document. Preserve their strings and XML partner links.
srcReader intentionally appends positional qualifiers after name and filename
predicates, including `[1]`; these distinguish repeated semantic predicates.
This does not change archive-root omission. Frozen captures predate these
qualifiers and must not be rewritten.
The resolver must reproduce [srcReader's root test](../../../../srcReader/src/srcml_reader.cpp):

1. A root whose local name is `unit`, with an attribute whose local name is
   `url`, and without an attribute whose local name is `filename`, is archive
   mode. Attribute presence, not value, determines this test.
2. In archive mode, descendant locators omit the outer root. Prepend
   `/src:unit[1]` before ordinary document-level XPath evaluation.
3. Otherwise evaluate the locator directly, including its root segment.
   A standalone file normally begins `/src:unit[1]`. A root with both `url`
   and `filename`, or child units but no `url`, is not archive mode.
4. Require exactly one endpoint. Do not silently choose the first match or try
   alternate roots until an expression succeeds. Filename-less archive children
   use positional segments; filenames containing both quote types can use
   XPath `concat()`.

The emitted canonical bindings are mandatory:
`src = http://www.srcML.org/srcML/src` and
`diff = http://www.srcML.org/srcDiff`. If `mv` is supplied, its binding is
`http://www.srcML.org/srcMove`. Every used QName prefix must be bound. Input
prefix spelling can differ because canonicalization uses namespace URIs.

Other prefixes preserve srcReader's lexical names. A single document-wide map
can represent them only when their bindings are consistent for all emitted
locators. If a retained prefix would denote different URIs in different locator
steps, fail schema-3 serialization explicitly as an unsupported namespace
context; never guess a URI or publish misleading evidence. This is an explicit
output-admission limitation. Endpoint-specific overrides and changes to
srcReader's naming convention are outside this migration.

Selected locators must resolve to the same endpoint/text in native input and
attribute-annotated output. Viewer transformation owns its separate node IDs
and remapping. Resolve diagnostic paths against input before transformation.
Namespace and uniqueness checks need the XML; a declaration in JSON alone does
not establish successful resolution.

Producer namespace admission indexes extension-element spans in opening-tag
order, retaining one enclosing-span index per record. Building that index takes
O(E) time and storage for E extension elements. A candidate lookup takes
O(log E + D) time, where D is extension nesting depth, and reuses one temporary
list of ancestor indices. Namespace strings are not copied into each candidate.
Binding order remains outer-to-inner, with published candidates admitted before
benign bindings from other active candidates. XML-only runs skip extension
namespace collection and admission entirely. The optional profile report records
JSON admission under `pipeline.locator_namespaces_ms`.

## Diagnostics schema 5

When requested, diagnostics requires `schema_version: 5`, `candidate_counts`,
`candidates`, `correspondences`, `type3_comparisons`, and `type2b_groups`.
Absence means not recorded; empty collections mean recorded with no entries.
It is a trace of actual retrieval/classification paths, not an exhaustive
Cartesian comparison or historical truth oracle. It creates no production
matches or content counts.

### Candidate inventory

`candidate_counts` holds `registered` (registry total records, including
inactive ones) and `active`. Candidate inventory covers exactly the active
records. Registered is at least active, which is at least selected endpoint
count; every candidate ID is below registered count.

Each candidate has `candidate_id`, `revision: original|modified`, `role`,
`selected_group_id`, `endpoint`, `type3_eligible`, `line_units`, and `token_units`.
Role is `diff_wrapper`, `single_child_wrapper`, `multi_child_wrapper`, or
`structural_child`. For selected candidates, group ID points to their owner and
endpoint is null: resolve the ordinary endpoint there. Unselected candidates
have null group ID and an inline ordinary endpoint, whose ID agrees.

This avoids duplicating selected bodies while preserving full active inventory.
Eligibility is the existing collector predicate, not proof of retrieval or
comparison. Unit lengths are actual normalized sequence lengths, not selection
coverage. When diagnostics is present, sequence members' roles must agree with
structural-child eligibility; without it, that remains an XML/collector check.

### Classified correspondences

Records require `id`, original/modified candidate IDs, `content_relationship`,
`name_evidence`, `location`, original/modified contexts,
`verified_partner_counts`, and `selection`. IDs are explicit result-local
strings, not viewer array positions. Candidate references resolve with the
correct side.

Diagnostic pair `location` preserves `scope: pair`, `classification`, `reason`,
`observations`, `carried_by_parent`, and nullable `parent_pair`.
Classifications/reasons retain [movement_classifier.hpp](../../../src/movement_classifier.hpp)
values. Observations retain file, semantic-container, anchor-interval,
relative-order, and ancestor values. Parent carrying requires a parent pair
with original/modified candidate IDs, not a selected parent move. Parent
references resolve in active inventory; the current parent policy chooses
parents from those exact decisions. Carried pairs retain `same_within_parent`
anchor and `unchanged` relative-order observations.

Contexts preserve revision file, semantic-container ID/label, previous/next
common anchor IDs, meaningful ancestors and interpretability, structural-region
ID/mapping, common-sibling prefix/suffix counts, and anchor-region ID. Missing
strings use null; arrays, booleans, and actual counts retain their values.

Verified partner counts are null outside Type-3. For Type-3 they are positive
`original`/`modified` degrees in the verified graph before selection. Every
verified Type-3 comparison has exactly one corresponding classified pair;
degrees must recompute from those comparisons. Competing edges are not an
unresolved selected-group interpretation.

Selection contains `status: selected_pair|not_selected_pair` and nullable
`selected_group_id`. A selected link identifies the exact ordinary selected
pair of the same content relationship. Unselected pairs can still share
endpoints with other selected groups or occur within an unresolved group.
Unresolved singleton cardinality does not establish pair selection. Missing
rejection reasons must not be reconstructed from a false selection status.

### Type-3 verification

Each comparison has explicit ID, original/modified candidate IDs,
`verification`, and `selection`. Candidates must be eligible with the same
known construct. Verification contains status, nullable reason, and line/token
objects with `common` and `maximum`.

Maxima equal the larger of the respective inventory lengths. Common lengths are
null when not evaluated; otherwise they are nonnegative and no larger than the
shorter candidate. Evaluated verification must agree with the current 9/10
threshold: at least one positive-length line or token comparison meets it for
`verified`, and neither does for `below_threshold`. Do not require both to pass.
This check validates the current detector policy, not a universal definition of
Type-3 similarity; a later policy change must update its versioned description
and validation together.

| Current outcome | Verification | Verification reason | Selection |
| --- | --- | --- | --- |
| `ambiguous_type2c` | `not_evaluated` | `ambiguous_type2c` | `not_applicable` |
| `below_threshold` | `below_threshold` | null | `not_applicable` |
| `selected` | `verified` | null | `selected` |
| `selection_rejected` | `verified` | null | `not_selected` |

Selection has nullable selected-group ID and reason. Reason is null under the
current instrumentation; rejected verified edges can lose to policy or
conflicts. Do not invent `overlap_conflict`. Selected links resolve to exact
Type-3 groups. Diagnostics preserve observed LCS values without changing the
verifier's decision or production retrieval behavior.

### Type-2b observations

Each group has ID, `content_relationship: type2b`, `observation_only: true`,
nonempty original/modified candidate-ID arrays, `blind_only_pair_count`, and
nullable location. Lists describe a blind equivalence group that can also
contain stronger consistent pairs. Blind-only count excludes those stronger
pairs; do not label the whole Cartesian product blind-only.

A nonnull location has classification and reason and requires singleton
original and modified lists with one blind-only pair, matching current producer
instrumentation. Cardinality follows list lengths, not an `ambiguous` confidence
label. Type-2b never enters production histograms.

## Worked examples and validation

The [examples](examples/) cover empty, selected, unresolved-many,
unresolved-singleton, copy, sequence, mixed, tentative, and diagnostic results.
All paths, counts, and measurements are illustrative. Normalized sequence/LCS
numbers are not measurements computed from these snippets. Their declared
relationships must remain coherent, but passing these checks does not establish
that the complete illustrative trace can be generated by the current detector.
Executed examples with separate build receipts belong to later implementation
verification, not these format fixtures.

The [locator companions](examples/locators/locator-checks.json) are hand-authored
input/attribute-annotated XML. They demonstrate resolution in native archive
and standalone-file documents; they are not detector captures.

Validation uses pinned development-only dependencies in
[requirements-validation.txt](requirements-validation.txt). On a Docker Python
with pip, install them into an isolated target and run both checks:

```bash
./bin/srcml-dev-shell python3 -m pip install --target srcMove/build/schema3-validation -r srcMove/doc/plans/results_schema_v3/requirements-validation.txt
./bin/srcml-dev-shell env PYTHONPATH=srcMove/build/schema3-validation python3 -B srcMove/doc/plans/results_schema_v3/check_examples.py --self-test
./bin/srcml-dev-shell env PYTHONPATH=srcMove/build/schema3-validation python3 -B srcMove/doc/plans/results_schema_v3/check_locators.py
```

The current workspace image lacks pip. Bootstrap a temporary pip zipapp without
changing system packages, then install the same pinned target:

```bash
./bin/srcml-dev-shell bash -lc 'curl --fail --silent --show-error --location https://bootstrap.pypa.io/pip/pip.pyz -o /tmp/srcmove-schema3-pip.pyz && python3 /tmp/srcmove-schema3-pip.pyz install --disable-pip-version-check --target srcMove/build/schema3-validation -r srcMove/doc/plans/results_schema_v3/requirements-validation.txt'
```

The example checker first calls `Draft202012Validator.check_schema`, then applies
that schema before cross-record validation. Its malformed cases exercise shape,
namespace, references, evidence states, degree/measurement consistency, and
counts. Selected-pair joins are indexed rather than scanned for every trace
record. The focused migration target also compares runtime structural admission
with the pinned JSON Schema engine across independently generated nested
mutations; ordinary runtime admission has no JSON Schema library dependency.
Runtime integer fields require integer encodings and reject integral floats
such as `3.0`, a deliberately narrower admission rule than JSON Schema's
mathematical integer interpretation. The locator checker independently uses a full XPath engine for native
root handling, text/annotation links, quote handling, and ambiguous resolution.
Neither checker proves detector correctness or actual structural adjacency.

## Phase 3 consumer inventory

The pre-edit inventory identified these live schema-2 consumers:

| Boundary | Consumers and responsibility |
| --- | --- |
| Shared admission | `tests/support/validation.py`, `benchmarking/results.py`, history `results.py`, viewer `srcmove_results.py`; now delegate wire admission to the runtime contract. |
| History | `process.py`, `compact.py`, `database.py`, `contracts.py`, `inputs.py`; atomic metrics, retained evidence, read-only historical access and strict resume fingerprints. |
| Benchmarks | `bigMoveBench/evaluate.py`, `oracle.py`, `normalized_execution.py`, `review.py`, `browser/reader.py`; atomic scoring, native locator ranges, diagnostics and retained-run display. |
| Viewer | Producer merge/enrichment, output-item projection, artifact admission/projections, correspondence APIs, native pre-transform resolver and frontend payload types. |
| Test readers | Behavioral oracle helpers, shadow diagnostics and tooling fixture constructors; schema-3 admission before test-only legacy-vocabulary projection. |

Other uses of schema number 2 (history CLI, benchmark dataset/review manifests,
configuration and projection APIs) are separate contracts and are not results
schema versions. Frozen schema-2 replay captures and version-specific study
readers remain historical evidence. Test comparison permits only srcReader's
new positional suffix after a semantic predicate; current native resolution
must still succeed with the unmodified locator.

## Implementation gates

Phase 2 threads existing typed flags, location decisions, and candidate metadata
through the producer. `make test-results-schema` replays a captured schema-2
baseline in ordinary, diagnostic, results-only, and diagnostic results-only
modes. It checks structural and cross-record constraints, atomic evidence,
sequence membership, selection values, and byte-identical native XML.

The shared native XML validator in `srcmove_runtime/results_xml.py` checks
sequence context independently of the detector against the input document. It reconstructs parent stream identifiers from XML events and
projects original/modified source children through diff wrappers to check
revision files, actual parents, consecutive child ordinals, member order, and
disjoint XML spans. Comments and whitespace do not consume sibling positions;
common and unselected source elements do. Hand-authored positive and negative
checks in
[test_results_schema_v3_sequences.py](../../../tests/behavior/test_results_schema_v3_sequences.py)
exercise this validator without using detector-produced expectations. Ambiguous
sequence-member locators fail this check even when an atomic baseline locator
ambiguity is recorded.

The October 16 verification uses 326 distinct input/granularity cases and nine
namespace regressions: all 335 producer checks and all 25 unit/component checks
passed in Docker. The synthetic checker also passed nine examples, an
unclassified-pair positive variant, and 108 malformed counterexamples; locator
companions passed both document forms and ten edge cases.
A fresh Release build of tracked commit
`86c3b44e6aac1c1525bf03de65a3459c10b6aef8` reproduced the frozen baseline binary
(SHA-256 `12c21cf13b6ac99a87982a70e6cac748aacadfc85e9d9ab244e86aacaedb0365`),
and all 326 schema-2 JSON/XML captures agreed with that build. This verifies
format migration against existing behavior, not detector accuracy. Dependencies
used the existing workspace builds; their source-to-binary identity is not
asserted. The explicit archived-source receipt records a caveat about the
automatic receipt discovering the enclosing repository.

Generated evidence stays ignored under `build/schema3-phase2/`: `baseline/`
contains snapshots and the locator audit, `source-baseline/receipt.json` and
`comparison.json` bind the old executable to archived source.

The initial Phase-3 invocation of the existing target reused `replay/` before
its output destination was corrected. That generated directory is no longer
an intact Phase-2 execution receipt; `replay/PHASE3_REGENERATION_NOTICE.json`
records this limitation. Frozen baseline inputs, results, annotation XML,
manifest hashes and archived-source receipts remain unchanged. Current
producer/consumer checks write to `build/schema3-phase3/`; ordinary suite reports
use `build/test-results/report.json`. See [test entry points](../../../tests/README.md)
for the focused target and baseline prerequisites.

Historical Phase-2 limits are retained explicitly below. Current srcReader
positions address repeated semantic predicates; Phase-3 replay validates the
current locators independently while preserving the old audit and hashes.

- Three baseline cases have ambiguous native locators from repeated file units
  or named functions. Phase-2 tests recorded their exact paths and match counts;
  323 cases resolved uniquely. Current srcReader adds positional qualifiers;
  Phase-3 checks require all current endpoint locators to resolve uniquely.
- Three legacy behavioral oracle failures existed before migration (padded
  loop reorder, unchanged try/catch crossing, and edited control-header/body
  reorder). They remain recorded separately from differential equivalence.
- Three selected fragment pairs lack classification and use
  `no_classified_pair`, as explained above.
- A separate native XML writer defect can hoist conflicting extension-prefix
  declarations within one file unit. JSON admission and valid cross-unit
  rebinding are tested; this migration does not repair that writer.

Phase 3 shares strict JSON admission through `srcmove_runtime.results_schema`,
including diagnostics schema 5 and cross-record consistency. History compact
schema 5 retains ordinary evidence with source text digests and keeps output
items separate from atomic SQLite projections; validator fingerprint 4 prevents
resuming old admissions as current evidence. Read-only historical access keeps
its original fingerprints. Viewer artifact schema 5 uses explicit correspondence
IDs and resolves diagnostic paths against native input before transformation.
Viewer native admission also checks actual sequence parents, adjacency, member
order, files and disjoint spans. Parent stream IDs are checked against original
input bytes when available; annotated-only supplied documents cannot prove
those original event indices after writer framing changes.
Benchmark scoring stays atomic. Frozen study outputs, hashes, adjudications,
and version-specific thesis appendix readers remain unchanged. Current thesis claims change only after the
new format is implemented and verified. No production constants or program
release version changed in Phases 1–2. Phase-2 verification does not establish
full consumer-suite success. Current verification is recorded separately under `build/schema3-phase3/`.


## Phase 3 verification

Docker verification on October 16, 2026:

- `make test-results-schema`: 358 checks passed, including all 326 frozen-case
  replays, native namespace/sequence checks, independent structural-validator
  parity, and oracle-boundary regressions. Current locators resolve uniquely;
  frozen capture hashes remain unchanged.
- `make test`: 739 passed, three failures exactly matching the frozen baseline,
  and two development-only dependency checks skipped. Those two checks passed
  in the focused migration target. There were no errors. The known detector
  failures remain assertions; no full-suite green result is claimed.
- Final benchmark browser query checks: all ten passed, covering schema-3
  atomic counts/classifications and legacy read-only fallbacks.
- Synthetic contract checker: nine examples, the unclassified exact-pair
  variant, and 108 malformed counterexamples passed. Locator companions and
  ten edge cases passed.
- `make -C srcDiffVisual image` and the authoritative
  `make -C srcDiffVisual test` passed with the rebuilt packaged image: 277
  backend tests, 76 frontend tests, production frontend build, and lint.
  Final frontend layers reused the successful source-matched Docker cache.
- The workspace Docker image was rebuilt with `python3-lxml`. Initial viewer
  checks used an isolated development dependency target; the final check needed
  no temporary dependency override.

Local receipts are `build/schema3-phase3/replay/report.json`,
`build/schema3-phase3/browser-consumers/report.json`,
`build/schema3-phase3/verification.json`, and `build/test-results/report.json`.
Ignored build/test output and `../srcDiffVisual/temp/schema3-python` are generated
files, not frozen research results. See the regeneration notice above for the
initial reuse of the old generated Phase-2 replay directory.

No staging, commits, pushes, release-version changes, detector matching-policy
changes, or frozen study rewrites were performed.
