# srcMove Handoff: Fix Structural-Child Candidate Selection

## Situation

`srcMove` currently has a move-unit design problem around
`region_filter_options.expand_structural_children`.

The old behavior (`expand_structural_children = true`) replaces a matching
leaf `diff:insert` / `diff:delete` wrapper with preferred child candidates such
as functions, classes, and statements before matching. This can be too
aggressive: if a whole BigCloneBench Type-1 fragment matches, smaller internal
statement/function matches should not steal the result.

The attempted quick fix was to set the default to:

```cpp
opt.expand_structural_children = false;
```

in [src/region_filter.cpp](/home/nick/Projects/srcMLBuildTemplate/srcMove/src/region_filter.cpp:257).

That avoids child matches stealing whole-region matches, but it is too blunt.
It causes srcMove to annotate broad `diff:*` wrappers and loses legitimate child
matches when the wrapper text does not match.

## User Intent

The user explicitly wants:

- no move tags on broad `diff:delete` / `diff:insert` wrappers when the actual
  moved unit is a srcML construct inside the wrapper
- whole matching regions to win over smaller internal matches
- child construct matches to remain available as a fallback when the whole
  wrapper does not match

In short:

> Prefer the largest meaningful exact moved construct, but do not annotate
> generic diff wrappers as the moved code block.

## New Policy Test

A named e2e fixture now records this policy:

- [tests/regression/xml/cases/do_not_annotate_diff_wrapper_when_child_construct_moves/input.xml](/home/nick/Projects/srcMLBuildTemplate/srcMove/tests/regression/xml/cases/do_not_annotate_diff_wrapper_when_child_construct_moves/input.xml:1)
- [tests/regression/xml/cases/do_not_annotate_diff_wrapper_when_child_construct_moves/expected.json](/home/nick/Projects/srcMLBuildTemplate/srcMove/tests/regression/xml/cases/do_not_annotate_diff_wrapper_when_child_construct_moves/expected.json:1)
- [tests/regression/xml/cases/do_not_annotate_diff_wrapper_when_child_construct_moves/expected.xml](/home/nick/Projects/srcMLBuildTemplate/srcMove/tests/regression/xml/cases/do_not_annotate_diff_wrapper_when_child_construct_moves/expected.xml:1)

It expects a moved function to be annotated at:

```text
/src:unit[1]/diff:delete[1]/src:function[src:name='moved_function']
/src:unit[1]/diff:insert[1]/src:function[src:name='moved_function']
```

It must fail if srcMove annotates only:

```text
/src:unit[1]/diff:delete[1]
/src:unit[1]/diff:insert[1]
```

With `expand_structural_children = false`, this test fails in exactly that way.
That failure is intentional until the candidate-selection design is fixed.

## Failure Categories Observed

After setting `expand_structural_children = false`, `python3
tests/regression/xml/run.py build/srcMove` produced failures in two categories.

### 1. Annotation moved to the diff wrapper

These are policy failures, not necessarily detection failures:

- `do_not_annotate_diff_wrapper_when_child_construct_moves`
- `position`
- `type2_nested_if_statement`
- `type2_renamed_function`
- `type2_renamed_local`
- `type2_renamed_parameter`
- `type2_statement_child_preferred`
- `type2_two_independent_statements`

The move may still be found, but the reported xpath becomes `diff:delete[1]`
instead of the child construct. That is not acceptable for srcVisual or for
explaining what source construct moved.

### 2. Legitimate child moves disappear

These are real regressions:

- `single_structural_child_in_wrapper`
- `archive_whole_file_split_structural`

Examples:

- `single_structural_child_in_wrapper`: wrapper-only comments differ, but the
  inner function is the same moved code.
- `archive_whole_file_split_structural`: one delete wrapper contains two
  functions, and they reappear as two separate insert wrappers. Whole-wrapper
  matching cannot express this split; child candidates can.

## Recommended Design

Do not treat `expand_structural_children` as a mutually exclusive mode.

Instead, generate competing candidates:

1. whole leaf diff-region candidates
2. preferred child construct candidates inside those leaf regions

Then choose winners after matching.

Desired rule:

- if a larger meaningful candidate has a match, prefer it
- suppress matched child candidates contained inside that winning larger match
- if the larger candidate does not match, allow child candidates to match
- do not annotate generic `diff:*` wrappers when a single child construct is the
  meaningful moved unit

This is essentially:

> largest useful exact match wins; children are fallback alternatives.

## Important Design Details

### Do not regress BigCloneBench

The original reason for turning off structural-child expansion was BigCloneBench
Type-1 failures where smaller internal matches were reported instead of the
whole intended fragment. The fix must preserve the ability for whole Type-1
fragments to win.

### Do not remove child fallback

The existing child expansion is still useful for:

- wrapper-only comment/context differences
- one large delete wrapper splitting into multiple insert wrappers
- Type-2 function/statement cases where annotating the srcML construct matters

### Type-2 should stay construct-level

Type-2 matching should not become broad wrapper matching. Keep Type-2 eligibility
restricted to the existing construct/statement roots in
[src/region_filter.cpp](/home/nick/Projects/srcMLBuildTemplate/srcMove/src/region_filter.cpp:67).

## Implementation Direction

The current code path in
[filter_regions_for_registry](/home/nick/Projects/srcMLBuildTemplate/srcMove/src/region_filter.cpp:209)
does this:

```cpp
child_candidates = extract_preferred_child_candidates(...)
if (!child_candidates.empty()) {
  add children;
  continue;
}
add whole region;
```

That replacement behavior is the root problem.

A better implementation likely needs:

1. always create the whole leaf-region candidate
2. also create preferred child candidates
3. store enough metadata to know containment / parent candidate relationship
4. match all candidates
5. suppress lower-priority contained matches when a higher-priority match exists

Possible metadata to add to `move_candidate`:

- `candidate_unit` or `candidate_source`:
  - `diff_wrapper`
  - `structural_child`
- `parent_region_id` or source `diff_region` index
- `start_idx` / `end_idx` are already present and can support containment checks
- maybe `is_diff_wrapper_candidate`

Suppression can probably happen after `build_content_groups(...)` and before
`build_move_tags(...)`, because by then the code knows which candidates actually
matched.

## Selection Sketch

For each matched group:

1. Ignore unmatched groups for annotation.
2. Consider exact matches before Type-2 matches.
3. Sort matched candidate groups by priority:
   - exact before Type-2
   - larger source span before smaller source span
   - structural child before bare diff wrapper when spans are equivalent or when
     the wrapper only encloses one meaningful child
4. When accepting a group, mark its delete and insert spans as covered.
5. Reject later groups whose delete and insert candidates are contained in
   already accepted spans.

This sketch may need adjustment for many-to-many groups. Keep the first version
small and driven by the current failing fixtures.

## Validation Commands

Run the focused suite first:

```bash
python3 tests/regression/xml/run.py build/srcMove
```

Then run generated e2e:

```bash
python3 tests/regression/source/run.py
```

Before calling the fix done, also rerun a BigCloneBench Type-1 slice that
previously suffered from child matches stealing whole-fragment matches. If the
large generated cases are already present, use the BigCloneBench runner with a
small enough limit for iteration, then scale back up.

## Expected Outcome

After the fix:

- `do_not_annotate_diff_wrapper_when_child_construct_moves` passes
- `single_structural_child_in_wrapper` passes
- `archive_whole_file_split_structural` passes
- existing Type-2 construct-level tests pass
- BigCloneBench Type-1 cases prefer the larger intended fragment when it matches
- srcMove does not annotate `diff:*` wrappers when the meaningful moved block is
  an inner `function`, `decl_stmt`, `if_stmt`, etc.

## Note About Older Handoff

[AI_HANDOFF_move_unit_flag.md](AI_HANDOFF_move_unit_flag.md) describes a simpler
CLI toggle for structural-child behavior. Treat that as older context, not the
preferred fix. The current recommendation is an internal candidate-selection
fix first. A CLI flag can still be added later for experiments, but it should
not be the main correctness mechanism.
