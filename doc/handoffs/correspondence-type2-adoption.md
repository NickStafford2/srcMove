# Handoff: adopt correspondence classification for unique Type-2 output

## Objective

Implement Phases 4.0 and 4.1 of
[`Correspondence before change classification`](../plans/correspondence.md):
extend the reviewed structural change classifier to strong unique one-to-one
Type-2 correspondences without changing the definition of relocation.

Do not change production output first. Begin with a reviewer-owned oracle and
observation-only Type-2 diagnostics, characterize every checked-in Type-2
expectation, and only then adopt the shared decision path. Type-1, Type-3, and
non-1x1 policy must remain unchanged.

This handoff covers the immediate Type-2 migration. Phase 4.2 migrates verified
Type-3 correspondences; Phase 5 addresses repeated groups; Phase 6 evaluates and
consolidates the system. Their scope and historical-analysis acceptance criteria
live in the [roadmap](../plans/correspondence.md#historical-analysis-objective).
Apply those criteria during this migration: fewer moves or more ambiguity alone
does not demonstrate improvement. Audit missed real moves alongside false moves.

## Starting point

The Phase 4.0 working tree is based on `6538ed7`. It generalizes the location
classifier into `src/movement_classifier.*`, adds observation-only Type-2
diagnostics (schema 3), and adds an independent Type-2 contract catalog. Normal
production behavior remains unchanged. The fixture baseline is audited; the
historical sample does not yet establish unique Type-2 positive/negative
classification coverage. Finish that evidence before Phase 4.1 adoption.

Current evidence and reproduction details belong in
[`moveSelectionBench/README.md`](../../moveSelectionBench/README.md#type-2-observation-baseline).
Do not repeat the completed refactor or regenerate expected labels from output.

srcMove remains version `0.5.0`. Phase 3 is complete:

- unique Type-1 output requires positive `relocated` classification;
- normalized source regressions no longer manufacture rename evidence;
- all twelve Type-1 contracts agree with production;
- the retained Notepad++ evaluation transitions 12 ambiguous Type-1 moves to
  non-moves while preserving all 17 correspondence observations; and
- the full 13-step Docker suite passes with a clean `git diff --check`.

The canonical current behavior is in [`doc/architecture.md`](../architecture.md),
the Phase 3 evidence is in
[`moveSelectionBench/README.md`](../../moveSelectionBench/README.md), and future
policy remains in [`doc/plans/correspondence.md`](../plans/correspondence.md).

## Current Type-2 behavior

[`src/move_registry/content_group_builder.cpp`](../../src/move_registry/content_group_builder.cpp)
groups candidates by exact Type-2 canonical identity. It creates a proposal
only when the normalized group is uniquely one-to-one, assigns the fixed
ranking confidence `950`, and removes a proposal when the legacy adjacent
nested local-replacement heuristic fires. Other unique Type-2 proposals enter
the common hierarchy and overlap selector without structural change
classification.

The fixed `confidence_milli` value is an ordering weight, not a calibrated
probability or a reviewed correspondence threshold. Do not treat `950` as
evidence that a location changed.

Type-2 groups that are not one-to-one are already unresolved. Preserve that
behavior: do not pair by document order, decompose normalized groups, or allow
a rejected unique Type-2 correspondence to fall through as a manufactured
Type-3 result.

## Checked-in baseline inventory

The clean Phase 3.3 build currently selects the following Type-2 expectations.
Counts below use only currently discovered fixtures; stale ignored test-result
directories are excluded.

| Suite | Selected Type-2 moves | Cases |
| --- | ---: | --- |
| XML regression | 10 | `type2_boolean_literal_statement`, `type2_consistent_type_name`, `type2_function_name_and_literal`, `type2_nested_if_statement`, `type2_renamed_function`, `type2_renamed_local`, `type2_renamed_parameter`, `type2_statement_child_preferred`, and two in `type2_two_independent_statements` |
| Source regression | 1 | `reorder_function_specifiers` |
| Policy regression | 4 | `direct_type2_c_function`, `classification_type2_java_method_identifiers`, `classification_type2_java_method_literal`, `classification_type2_java_method_identifiers_and_literal` |
| Move-selection contracts | 3 | one required Type-2 result each in `unique_parent_over_repeated_children`, `coherent_type2_parent_over_partition`, and `coherent_type3_parent_over_partition` |

The XML suite also has six explicit zero-move Type-2 guards:
`type2_ambiguous_many_guard`, `type2_ambiguous_many_to_one_guard`,
`type2_function_ambiguous_many_guard`, `type2_call_expression_guard`,
`type2_member_access_guard`, and `type2_operator_guard`. The move-selection
catalog separately requires `adjacent_type2_replacement_is_not_move`.

Do not interpret the 18 positive expectations as 18 reviewed relocations:

- the four policy cases are generated cross-file transfers and have positive
  file evidence;
- `reorder_function_specifiers` moves a declaration past a stable sibling in
  one struct and should be evaluated for crossed-anchor evidence;
- `coherent_type3_parent_over_partition` explicitly uses
  `source.java|destination.java`;
- several XML positives are intentionally small Type-2 canonicalization or
  hierarchy mechanics fixtures at the file root, with no mapped container or
  stable anchors; and
- `type2_renamed_local`, `type2_renamed_parameter`, literal replacement, and
  similar cases may represent modification in place rather than relocation.

The two hierarchy contracts `unique_parent_over_repeated_children` and
`coherent_type2_parent_over_partition` also lack positive location context in
their current filenames. If they are intended to remain move-selection
mechanics contracts, add explicit faithful relocation context as Phase 3 did;
do not weaken the classifier to preserve them.

## Required Phase 4.0: shared decisions, oracle, and observation-only diagnostics

Implementation and fixture-contract work below is present in the working tree;
the historical acceptance requirement (item 6) remains open. The baseline audit
does not establish that suppressing all ambiguous Type-2 pairs improves accuracy.

Before changing normal output:

Generalize the existing Type-1/shadow classifier names and compact decision
record only as needed for shared use. Keep matching evidence, location outcome,
and selection disposition separate, with one decision feeding production and
diagnostics. Preserve current Type-1 behavior; do not add a generic framework,
new matcher, or parallel eligibility implementation.

1. Add a separate reviewer-owned Type-2 contract catalog, or extend the
   existing catalog without weakening its Type-1 independence. Each unique
   contract must specify correspondence preconditions, observed location
   context, expected classification and reason, and expected future production
   disposition.
2. Add observation-only diagnostics for unique one-to-one Type-2 groups. Use
   the same pure structural classifier as Type-1; correspondence kind changes,
   but the definition of movement does not.
3. Bump the diagnostics schema version if ordinary diagnostic records gain
   Type-2 entries or fields. Normal results schema and annotations must remain
   unchanged during Phase 4.0.
4. Derive `current_result` from actual selected output after hierarchy and
   overlap selection. Do not use current output as the expected oracle.
5. Run every current XML, source, policy, and move-selection Type-2 fixture
   with diagnostics and record a reviewed baseline in
   `moveSelectionBench/README.md`.
6. Review a bounded historical sample independently of detector output,
   including genuine edited moves and edits in place. Record baseline false
   moves, missed moves, and unresolved cases using the
   [Phase 6 evaluation criteria](../plans/correspondence.md#phase-6-evaluate-and-consolidate).

Minimum independent contracts:

| Scenario | Expected change | Future Type-2 output |
| --- | --- | --- |
| Cross-file consistent rename | `relocated/different_file` | move |
| Cross-container consistent rename | `relocated/different_semantic_container` | move |
| Same-parent reorder past stable sibling | `relocated/crossed_stable_sibling` | move |
| Identifier or literal change in same mapped slot | `stationary/same_anchor_interval` | no move |
| Adjacent nested replacement | stationary or restructured according to observed ancestry | no move |
| Missing mapped context | `ambiguous/insufficient_context` | no move |
| Repeated normalized group | `ambiguous/non_unique_correspondence` | unchanged unresolved group policy |

For the initial strong Type-2 correspondence boundary, prefer a structural
definition over an invented probability: exact equality of the existing
Type-2 canonical representation, eligible complete constructs, and unique
one-to-one cardinality. If another confidence threshold is proposed, it must
measure correspondence quality independently of location and have explicit
counterexamples. Do not repurpose `confidence_milli == 950` as that threshold.

## Phase 4.1: one shared Type-2 decision path

After the oracle and baseline are reviewed:

1. harvest unique Type-2 decisions after exact groups have removed Type-1
   correspondences;
2. classify each pair exactly once with the shared structural classifier;
3. materialize diagnostics and production eligibility from that same decision;
4. admit only `relocated` Type-2 proposals to normal selection;
5. retire the legacy Type-2 local-replacement rejection only when its negative
   contracts are covered by the shared classifier; and
6. preserve existing hierarchy, overlap, Type-3 retrieval, and unmatched
   emission behavior.

A relocated Type-2 proposal may still lose to a stronger accepted parent or
child explanation. Classification controls eligibility, not final selection.
Do not extend exact-parent carrying to normalized parents on containment alone.
Require evidence of stable relative position and a selected explanation that
accounts for the child before suppressing a genuine child move.

Before adoption, explain each gained or lost reviewed historical move. Missing
context is a reason to investigate the evidence, not to redefine a known move
as a negative test. Preserve genuine same-file positives; explicit cross-file
context is appropriate for mechanics fixtures only when faithful to their
intended scenario. Review unresolved precision/recall tradeoffs before adoption.

## Focused tests

At minimum, require:

- Type-2 classification and production disposition are independent oracle
  fields;
- diagnostics-only Phase 4.0 leaves ordinary output byte-for-byte unchanged;
- normal and `--results-only` ordinary JSON remain equivalent;
- cross-file and crossed-sibling Type-2 relocations remain eligible;
- stationary and missing-context Type-2 pairs do not fall through to Type-3;
- the existing adjacent local-replacement negative remains a non-move;
- non-1x1 normalized groups remain unresolved without manufactured pairs;
- independently reordered children inside normalized parents are not incorrectly
  suppressed as parent-carried;
- Type-1 contract outputs and diagnostic order remain unchanged; and
- Type-3 contracts remain unchanged.

## Stop conditions

Stop for review if:

- a positive Type-2 golden lacks relocation evidence and cannot be repaired
  with a small faithful fixture;
- correspondence acceptance would require a new similarity score rather than
  exact Type-2 normalized identity;
- a rejected Type-2 pair reappears as Type-3;
- parent carrying would require pairing a non-1x1 normalized group;
- location classification feeds back into Type-2 canonical identity; or
- a reviewed real move is lost and the evaluation has not established an
  acceptable historical-analysis tradeoff; or
- ordinary output must change during the observation-only slice.

## Verification

Use the parent workspace Docker environment:

```bash
./bin/srcml-dev-shell make --no-print-directory -C srcMove test
```

Also require:

```bash
git diff --check
git status --short
```

Phase 4.0 diagnostics, tests, and documentation do not require a version bump.
Production adoption also does not automatically authorize a release. Leave
`VERSION` unchanged unless the user explicitly requests a release or approves
that exact release step, following [the versioning policy](../../README.md#versioning).
The user handles staging and commits.
