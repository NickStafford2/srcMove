# Handoff: correspondence context and shadow classifier

## How to use this handoff

Give this entire document to the primary implementation agent. That agent is
the orchestrator and integration owner. It may delegate the bounded audit and
review tasks below, but it must make the final design decisions, own all merged
edits, and verify the integrated result.

Delete this handoff after the milestone is complete. Move verified behavior to
[`doc/architecture.md`](../architecture.md), preserve unresolved future work in
[`doc/plans/correspondence.md`](../plans/correspondence.md), and keep test
methodology in the owning suite documentation.

## Objective

Implement the first major milestone of
[`Correspondence before change classification`](../plans/correspondence.md):

1. create reviewed semantic contracts for stationary, relocated,
   restructured, and ambiguous Type-1 correspondences;
2. capture the minimum lightweight structural context needed by those
   contracts; and
3. emit an observation-only Type-1 shadow classification with stable,
   machine-readable reasons.

Normal annotated XML and the existing `moves` JSON array must remain
authoritative and behaviorally unchanged. The milestone exists to measure the
new classifier before it controls production output.

## Implementation progress (2026-09-27)

Phase 0 is implemented in `moveSelectionBench/shadow_contracts.json`. Its 12
reviewed contracts separately declare srcDiff membership/cardinality,
structural preconditions, context observations, expected shadow labels, and
stable reasons. `moveSelectionBench/shadow_contracts.py` validates file and
mapped-container relationships, common declaration anchors, crossed siblings,
wrapper ancestry (including required absence), and carried-parent structure.
The source-generated `[[nodiscard]]`/unwrap miniature preserves its srcDiff
delete/insert precondition. Production `moves` remain unchanged.

Phase 1 has started. `src/location_context.hpp` defines an owned endpoint
context, and every candidate now receives the correct revision-side file from
`old|new`, `old|`, `|new`, or a shared archive filename. The streaming parser
also maintains a bounded source-element stack and records the nearest named
semantic container only when it is one physical construct with common revision
membership. Exclusive functions can inherit a physical common enclosing type;
file-root candidates remain unmapped. Mapped candidates now also reference a
deterministically interned, side-filtered meaningful ancestor chain. The
candidate registry rebases each document-local table into registry-owned
storage, preserving ID validity after parsing and preventing collisions across
incremental inputs. Common ancestors and wrappers belonging to the endpoint
side are retained while opposite-side wrappers are excluded. Anchor fields
remain deliberately empty/unreliable. `location_context_test` covers filename
parsing, candidate initialization, common cross-function containers, exclusive
container fallback, conservative file-root defaults, wrapper differences, and
registry ownership and rebasing of interned summaries.

The next implementation session should continue Phase 1 in this order:

1. collect complete substantial common declarations within mapped containers,
   reject mixed or repeated anchors, and resolve nearest anchors after EOF; and
2. expose focused anchor-interval tests before adding the shadow classifier.

Do not derive containers or anchors from raw XPath, names alone, the candidate
being classified, or a second tree-matching pass. Shadow correspondences must
later be harvested from unique exact groups before local-replacement and
hierarchy filtering, because final selected groups omit stationary evidence.

## Why this is urgent

Current srcMove can correctly identify exact correspondence while incorrectly
calling it relocation. In Notepad++ commit
`e59774add26b0130d38aaf722aceb0259ccc0078` (parent
`bf9f8b4c9549dadd23f483190dd1e1e4707da3ea`), adding `[[nodiscard]]` to methods
in `scintilla/src/Document.h` caused unchanged return statements to be exposed
through delete/insert regions. Current srcMove commit
`f5ccfe7d30261cc468a1c7e51d2049203b9f8625` reported twelve Type-1 move groups
on that file comparison, including visibly stationary method bodies.

The existing local-replacement guard is deliberately narrow: it recognizes
only unique Type-1 or Type-2 endpoints in exactly adjacent nested diff regions.
Do not extend that raw-event adjacency heuristic. The new work must collect
positive structural context and classify insufficient evidence as ambiguous.

## Required reading

Before editing, read completely:

1. repository `AGENTS.md` and the parent workspace `AGENTS.md`;
2. [`doc/plans/correspondence.md`](../plans/correspondence.md), especially
   "Decisions for the first implementation milestone";
3. [`doc/architecture.md`](../architecture.md);
4. [`doc/srcDiff_notes.md`](../srcDiff_notes.md);
5. [`moveSelectionBench/README.md`](../../moveSelectionBench/README.md); and
6. [`tests/README.md`](../../tests/README.md).

Inspect, but do not assume correctness from, the current implementations in:

- `src/region_filter.cpp` and `src/move_candidate.hpp`;
- `src/move_registry/content_group_builder.cpp`;
- `src/move_registry/group_selection.cpp`;
- `src/pipeline.cpp` and `src/summary.hpp`; and
- the results JSON writer and diagnostics tests.

## Non-negotiable scope

### In scope

- Unique one-to-one Type-1 correspondences only.
- Conservative anchors derived from srcDiff revision membership and complete
  common structural context.
- File, mapped semantic-container, nearest reliable common-anchor,
  ancestor/wrapper, and relative-order observations when available.
- Shadow classifications: `stationary`, `relocated`, `restructured`, and
  `ambiguous`.
- Stable machine-readable classification reasons.
- Opt-in diagnostics and tests.
- Preservation of the streaming memory model.

### Out of scope

- Changing normal move annotations or the meaning of the existing `moves`
  array.
- Type-2 or Type-3 adoption.
- Deckard vectors, LSH, or another similarity implementation.
- Copy detection, source-survival inventories, or NxM decomposition.
- A second general-purpose differencer or complete-tree rematcher.
- srcDiffVisual changes.
- Broad candidate-filter, threshold, hierarchy, or performance redesigns.
- Thesis-result claims or publication benchmark runs.

If the required context cannot be established conservatively, emit
`ambiguous` with a reason. Do not add a fallback that equates correspondence,
line distance, path difference, or lack of stationary evidence with movement.

## Reviewed policy

Apply the policy recorded in the canonical correspondence plan. In compact
form:

```text
if the correspondence is not uniquely resolvable:
    ambiguous
else if the endpoints are in different files:
    relocated
else if a relocated parent explains the absolute displacement and the child
        remains stable relative to that parent:
    stationary locally; record carried_by_parent diagnostically
else if two reliably mapped semantic containers are genuinely distinct:
    relocated
else if the same stable anchor interval contains a meaningful wrapper change:
    restructured
else if both endpoints occupy the same mapped container and anchor interval:
    stationary
else if an endpoint crosses a reliably mapped stable sibling:
    relocated
else:
    ambiguous
```

Different raw XPaths, changed line numbers, names, or immediate parents are not
independently sufficient. A source file change is strong positive relocation
evidence. Pure wrapping or unwrapping within one mapped interval is
diagnostic-only restructuring.

## Orchestration protocol

The orchestrator must keep one integration owner. Do not allow agents to make
overlapping edits concurrently in the shared checkout. Parallel work is
appropriate only for read-only audits or isolated worktrees with explicit
integration.

### Step 1: establish the baseline

- Confirm all repository statuses before editing and preserve unrelated user
  changes.
- Record the current srcMove commit and build receipt.
- Run the focused move-selection contracts and the full test suite through the
  documented Docker/Make entry points.
- Reproduce the Notepad++ comparison when the local reference checkout is
  available. Generated evidence belongs under an ignored build or benchmark
  directory, not beside checked-in fixtures.

### Step 2: delegate two read-only investigations

Run these investigations in parallel if agents are available. They must not
edit files.

#### Agent A: contract and oracle audit

Prompt:

> Read the correspondence plan, current move-selection catalog, policy tests,
> and the Notepad++ `[[nodiscard]]` reproducer described in the handoff. Propose
> the smallest reviewer-owned contract matrix needed for unique Type-1 shadow
> classification. Include stationary line shifts, same-slot attribute or
> signature edits, cross-file relocation, cross-function relocation,
> same-parent reorder past a stable sibling, wrapping/unwrapping, moved parent
> with carried children, repeated ambiguity, incompatible srcDiff paths, and
> missing-anchor ambiguity. For every case, specify the required srcDiff
> precondition, correspondence expectation, context observations, expected
> shadow classification, and reason. Do not edit files. Flag any expected label
> that requires human judgment.

#### Agent B: context and data-flow audit

Prompt:

> Read the correspondence plan and trace candidate construction, revision
> membership, exact grouping, hierarchy selection, diagnostics, and JSON
> output. Design the smallest streaming-compatible location-context model for
> unique Type-1 shadow classification. Explain exactly how complete common
> anchors and semantic containers can be identified without retaining the full
> XML tree or independently rediffing the program. Identify required source
> changes, lifetime/ownership concerns, complexity risks, output-schema impact,
> and focused unit seams. Do not edit files. Prefer `ambiguous` wherever the
> current stream lacks reliable evidence.

The orchestrator must reconcile both reports into a short implementation note
before assigning edits. If the reports show that a proposed label cannot be
supported without general tree rematching, keep that case ambiguous and
continue with the smaller milestone.

### Step 3: implement Phase 0 contracts

The integration owner or one designated writer should add the reviewed
contracts before classifier behavior. Use small synthetic fixtures that isolate
one interpretation each. Do not check in the full Notepad++ file as a unit
test; retain that real commit pair as evaluation evidence and create a minimal
source-generated regression that reproduces its mechanism.

Each contextual contract must assert its srcDiff precondition so an upstream
alignment change cannot make the test pass without exercising the classifier.
Tests must distinguish:

- correspondence evidence;
- observed context dimensions;
- expected shadow classification; and
- expected machine-readable reason.

The production-result expectation remains unchanged during this milestone.

### Step 4: implement context capture

Add the minimum model justified by the contracts. Prefer small value types and
stable identifiers over retaining nodes or raw pointers. At minimum, evaluate:

- file identity;
- nearest enclosing named semantic container and whether it is reliably mapped;
- nearest reliable common construct before and after the endpoint;
- a compact ancestor/wrapper summary; and
- relative sibling order only when grounded in mapped anchors.

An anchor must be a complete, substantial construct belonging to both
revisions and uniquely resolvable in the relevant mapped container. Begin with
named semantic containers and unique common declarations. Admit other
structural siblings only when a contract demonstrates reliable behavior.

Unit-test context extraction independently before using it in classification.
Keep parsing and context collection within the existing streaming pass unless
measurements and explicit review justify otherwise.

### Step 5: implement the shadow classifier

Create a dedicated classifier module rather than adding more special cases to
canonicalization or the content-group builder. It should consume one unique
Type-1 correspondence plus immutable endpoint context and return:

- `change_kind`;
- a stable `classification_reason`;
- the observed dimensions used by the rule; and
- any `carried_by_parent` diagnostic relationship that is actually supported.

Use ordered, explicit rules. Do not introduce an opaque score. Every nontrivial
branch must have a focused unit test and a counterexample.

The existing adjacent-local-replacement result should become observable in the
shadow model, but current production behavior remains intact until a later
milestone intentionally replaces it.

### Step 6: expose diagnostics without changing output

Under the existing opt-in diagnostics mode, add a `correspondences` collection
or an equivalently clear nested structure. Reconcile the exact location with
the existing results schema and tests before implementation. Do not rename,
remove, or reinterpret existing fields in this milestone.

Each record should include enough evidence to audit disagreements, for example:

```json
{
  "correspondence_kind": "type1",
  "cardinality": "one_to_one",
  "current_result": "move",
  "shadow_change": "stationary",
  "classification_reason": "same_anchor_interval",
  "before_context": {
    "file": "Document.h",
    "semantic_container": "HighlightDelimiter::NeedsDrawing",
    "previous_anchor": "...",
    "next_anchor": "..."
  },
  "after_context": {
    "file": "Document.h",
    "semantic_container": "HighlightDelimiter::NeedsDrawing",
    "previous_anchor": "...",
    "next_anchor": "..."
  }
}
```

Use repository conventions for XPaths, identifiers, and JSON escaping. Avoid
duplicating large raw subtrees or source files in every diagnostic record.

### Step 7: independent review

After implementation, delegate one read-only review agent:

> Review the integrated correspondence-context and Type-1 shadow-classifier
> change against the handoff, correspondence plan, current architecture, and
> tests. Look specifically for circular anchors derived from the correspondence
> being classified, accidental production-output changes, raw XPath or line
> distance treated as relocation proof, non-unique anchors, parent/child double
> reporting, unbounded memory growth, nondeterminism, undocumented schema
> changes, and fixtures that do not assert their srcDiff preconditions. Report
> findings by severity with exact files and lines. Do not edit files.

Resolve substantive findings before final verification.

## Acceptance criteria

The milestone is complete only when all of the following hold:

- The reviewed challenge contracts exist and their expected interpretations
  are documented in the owning test catalog.
- Context extraction has focused unit coverage and remains deterministic.
- Unique Type-1 shadow classifications and stable reasons appear only when
  diagnostics are requested.
- The minimal `[[nodiscard]]` regression is shadow-classified as stationary or
  restructured, not relocated.
- A unique cross-file Type-1 correspondence is shadow-classified as relocated
  without requiring local anchors.
- A true same-container reorder crosses a mapped stable sibling and is
  shadow-classified as relocated.
- Missing, repeated, or contradictory context yields ambiguous rather than a
  manufactured move.
- A relocated parent does not cause every stable descendant to become an
  independent shadow relocation.
- Existing annotated XML and ordinary results JSON are unchanged for the
  complete regression corpus.
- Normal and `--results-only` decisions remain equivalent.
- The full `make test` suite passes in the intended Docker environment.
- `git diff --check` passes and no generated build or evaluation artifacts are
  tracked.

## Stop conditions

Stop and request human review rather than broadening scope when:

- an expected classification depends on an unresolved policy choice;
- reliable anchors require independently rematching the complete old and new
  trees;
- the proposed context representation requires retaining the complete XML tree;
- existing production results would change before shadow evaluation;
- a schema change would break existing consumers;
- Type-2, Type-3, NxM, copy, Deckard, or srcDiffVisual work becomes necessary
  to make the first milestone pass; or
- the test oracle begins treating the current implementation's output as ground
  truth instead of independently specifying the intended interpretation.

## Verification commands

Use repository entry points rather than host-native CMake or Ninja:

```bash
make test
git diff --check
```

Use `tests/run.py` or the move-selection benchmark only for focused iteration
after the documented Docker wrapper has provided the correct environment.
Report every command, result, retained ignored artifact, and any test not run.

## Final handoff requirements

The orchestrator's final report must state:

- the exact implemented scope and intentionally deferred work;
- the context dimensions and classification rules actually supported;
- the contract cases added and their outcomes;
- the number and kinds of current-versus-shadow disagreements on the retained
  Notepad++ evidence;
- whether ordinary XML and JSON output remained byte-for-byte or semantically
  unchanged, and how that was verified;
- complete test results and build/source provenance;
- remaining ambiguous cases and policy questions; and
- which durable facts moved into canonical architecture or test documentation.

After that report is accepted, delete this handoff and begin any production
adoption as a separately reviewed milestone.
