# Handoff: adopt correspondence classification for unique Type-1 output

## Objective

Implement Phase 3 of
[`Correspondence before change classification`](../plans/correspondence.md):
let the reviewed classifier control normal output for unique one-to-one exact
(Type-1) correspondences.

Only positively supported `relocated` Type-1 correspondences may become normal
moves. `stationary`, `restructured`, `ambiguous`, and parent-carried children
remain visible in opt-in diagnostics but must not be annotated or emitted in
the authoritative `moves` array. Type-2, Type-3, and non-1x1 exact groups stay
on their existing production paths.

This is an intentional output-policy change. Do not preserve an old golden
merely because it reports every exact delete/insert pair as a move.

## Starting point

Start from commit `3db5da8` (`Correspondence phase 2.6 independent review`) or
a descendant containing it. That release is srcMove `0.4.0`, passes all 13
`make test` steps in Docker, and has a clean `git diff --check`.

The completed milestone already provides:

- compact streaming context in `src/location_context.hpp` and
  `src/region_filter.cpp`;
- a pure ordered classifier in `src/shadow_classifier.*`;
- unique Type-1 correspondence harvesting before selection in
  `src/move_registry/content_group_builder.cpp`;
- deterministic schema-v2 correspondence diagnostics;
- parent-carried child inference based on exact containment on both sides;
- 12 independently specified contracts in
  `moveSelectionBench/shadow_contracts.json`; and
- retained Notepad++ evaluation documented in
  `moveSelectionBench/README.md`.

All twelve reviewed contracts currently match their expected context,
classification, and reason. Production output deliberately has not adopted
those classifications yet.

## Required reading

Read completely before editing:

1. repository and parent-workspace `AGENTS.md` files;
2. [`doc/plans/correspondence.md`](../plans/correspondence.md), especially
   Phase 3 and the invariants;
3. [`doc/architecture.md`](../architecture.md);
4. [`moveSelectionBench/README.md`](../../moveSelectionBench/README.md);
5. [`tests/README.md`](../../tests/README.md); and
6. the Type-1 grouping, proposal, local-replacement, hierarchy, diagnostics,
   and unmatched-emission paths in
   `src/move_registry/content_group_builder.cpp`.

## Adopted policy

For an exact group with exactly one active deletion and one active insertion:

| Classification | Normal Type-1 output |
| --- | --- |
| `relocated` | eligible for existing hierarchy/overlap selection |
| `stationary` | no move |
| `restructured` | no move; diagnostics only |
| `ambiguous` | no move |
| `carried_by_parent` | no independent child move |

This gate controls eligibility, not selection priority. A relocated proposal
may still lose to an enclosing or otherwise stronger accepted explanation.

Non-1x1 exact groups remain governed by current group policy during this phase.
Do not decompose them, pair by document order, or infer copying. Type-2 and
Type-3 behavior must remain unchanged.

The existing adjacent-local-replacement heuristic must no longer make the
production decision for unique Type-1 pairs once this gate is active. Keep it
for Type-2 until Phase 4. A positively classified Type-1 relocation must not be
silently rejected by that older heuristic.

## Implementation sequence

### Phase 3.0: production oracle and baseline

Status: complete. The contract catalog now declares the adopted production
disposition independently of current selection. The sealed srcMove 0.4.0
baseline has seven unique disagreements, all current `move` versus expected
`not_move`; their IDs are documented in `moveSelectionBench/README.md` and
asserted by the focused test. The checked-in inventory found 14 supported
unique relocations, 14 unique XML correspondences with insufficient context,
nine source-fixture filename artifacts, and seven non-1x1 groups. The source
fixture artifact and complete case lists are documented canonically in the
benchmark README. Phase 3.1 may now build the shared decision path, but Phase
3.2 must normalize those source inputs and manually audit every changed golden.

Extend the reviewed contract catalog with an explicit expected production
disposition for every unique one-to-one case: `move` only for `relocated`, and
`not_move` for every other classification. Record that the repeated 2x2 case
remains outside the adoption gate rather than manufacturing pair results.

Update the adapter so contract evaluation returns `current_result` from the
resolved diagnostic record. Add a focused test that reports the pre-adoption
disagreements explicitly. Do not derive expected output from current results.

Before changing selection, capture an inventory of all checked-in Type-1
goldens and their shadow classifications. The inventory may be generated in an
ignored test-results directory, but its reviewed conclusions belong in the
owning test documentation or catalog. Separate:

- clear relocations whose move goldens should remain;
- stationary/restructured/ambiguous cases whose old moves should disappear;
- fixtures lacking enough context to prove their intended move; and
- non-1x1 groups, which are unchanged in this phase.

If a fixture is intended to prove relocation but supplies no positive context,
improve the fixture to express that intended structural change rather than
weakening the classifier.

### Phase 3.1: one shared classification decision

Build unique Type-1 classification records unconditionally, not only when
`--diagnostics` is requested. Keep the compact decision data local to grouping;
diagnostics should materialize it only on request.

Do not run two subtly different classifiers. Parent-carried post-processing
must operate on the same decision records later used by the production gate.
Diagnostics and production eligibility must therefore agree by construction.

Recommended shape:

1. harvest unique exact pairs immediately after `build_exact_groups()`;
2. classify each pair and resolve supported parent carrying;
3. build normal proposals;
4. disable or omit unique Type-1 proposals whose final classification is not
   `relocated`;
5. apply the legacy local-replacement filter only to Type-2 proposals;
6. run the existing hierarchy, overlap, and utility selection for remaining
   proposals; and
7. populate diagnostics from the shared decisions, then record whether each
   eligible relocation was ultimately selected.

Use candidate-ID pairs as deterministic keys. Do not retain references into
vectors or `content_groups::id_view` across mutation.

Rejected one-to-one exact correspondences must not fall through as Type-2 or
Type-3 matches. The current builders already exclude exact groups with both
sides from those fallback pools; preserve and test that property.

### Phase 3.2: end-to-end adoption contracts

For every unique reviewed contract, assert both the classification and normal
output:

- stationary line shift: no move;
- minimal `[[nodiscard]]` signature-only case: no move;
- `[[nodiscard]]` plus unwrap: no move;
- cross-file relocation: one Type-1 move;
- cross-function relocation: one Type-1 move;
- same-parent reorder past a stable sibling: one Type-1 move;
- wrapper added/removed: no move;
- relocated parent: report the coherent parent, not the carried child;
- incompatible wrapper evidence: no move;
- missing context: no move; and
- repeated 2x2 exact content: unchanged group policy, with no manufactured
  one-to-one decisions.

Assert normal annotated XML and `--results-only` equivalence for changed
fixtures. With `--diagnostics`, `current_result` must match actual production
output and all ordinary JSON fields must remain identical after stripping the
diagnostics object.

Audit every changed checked-in golden manually. Explain why it changed in the
owning catalog or test documentation; do not bulk-accept regenerated files.

### Phase 3.3: retained real-history evaluation

Re-run the retained normalized Notepad++ input from
`benchmark-results/correspondence-baseline-notepadpp/shadow-srcdiff.xml` using
the adopted build. Preserve the existing snapshot and srcDiff hashes.

The Phase 2.5 observation was 17 unique Type-1 correspondences, all
`ambiguous/insufficient_context`; 12 were then emitted as moves and five were
unselected. Under the adopted policy, none of those ambiguous correspondences
should become normal Type-1 moves. Verify this rather than assuming it, and
record:

- srcMove commit and build receipt;
- executable artifact hash;
- current move count by match kind;
- correspondence counts by classification/reason;
- old-to-new output transitions; and
- any remaining move not explained by a unique Type-1 decision.

Do not claim those 12 records are stationary. The supported conclusion remains
that available srcDiff context is insufficient for positive relocation.

## Focused tests

At minimum, add coverage for:

- a pure eligibility table mapping classification to output eligibility;
- production and diagnostics consuming the same final parent-carried decision;
- an ambiguous exact pair not falling through to Type-2 or Type-3;
- a positive same-file relocation surviving removal of the Type-1
  local-replacement guard;
- unchanged Type-2 local-replacement behavior;
- deterministic correspondence and move ordering;
- normal versus `--results-only` equivalence; and
- unchanged non-1x1 exact behavior.

Prefer a named helper or small value type for the eligibility policy rather
than scattering string comparisons through proposal selection.

## Scope boundaries

In scope:

- unique one-to-one Type-1 production adoption;
- replacing the Type-1 use of the local-replacement heuristic;
- reviewed regression-golden changes caused by that adoption;
- diagnostics/production consistency; and
- retained Notepad++ reevaluation.

Out of scope:

- Type-2 or Type-3 classification adoption;
- copy detection or source-survival inventories;
- NxM decomposition or document-order pairing;
- new anchor kinds or full-tree rematching;
- changing the taxonomy;
- srcDiffVisual changes; and
- exposing ambiguous or restructured records by default outside existing
  opt-in diagnostics.

## Stop conditions

Stop and request human review if:

- a checked-in positive Type-1 move has no positive relocation evidence and
  cannot be repaired with a small faithful fixture;
- adopting a decision requires Type-2, Type-3, copy, or NxM policy;
- a proposed fix derives relocation from raw XPath, line distance, names alone,
  or document order;
- ordinary output would need a schema change rather than only changed move
  membership;
- the same pair receives different classifications in diagnostics and
  production; or
- retained evaluation counts disagree with the sealed Phase 2.5 input before
  the production gate is applied.

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

Confirm no generated build, benchmark, or evaluation artifacts are tracked.
Because this phase intentionally changes detector behavior and reported
results, advance the `0.x` minor version when the production gate is complete.

## Completion report

Report:

1. exact production eligibility policy;
2. number and identity of reviewed golden changes;
3. proof that Type-2, Type-3, and non-1x1 policy stayed unchanged;
4. all 12 contract classifications and production dispositions;
5. retained Notepad++ before/after counts with provenance;
6. full test result and `git diff --check`; and
7. the new version.

After the phase is accepted, move verified production behavior into
`doc/architecture.md`, keep unresolved later-phase policy in
`doc/plans/correspondence.md`, and delete this handoff.
