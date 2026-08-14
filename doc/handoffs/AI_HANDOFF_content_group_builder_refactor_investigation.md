# srcMove Handoff: Investigate `build_content_groups` Refactor Options

## Situation

`build_content_groups(...)` in
[src/move_registry/content_group_builder.cpp](/home/nick/Projects/srcMLBuildTemplate/srcMove/src/move_registry/content_group_builder.cpp:512)
was recently split from one long function into a sequence of named internal
phases.

The current top-level flow is:

```cpp
std::vector<pending_group> exact_groups = build_exact_groups(registry);
selection_state            state(registry.active_candidate_count());

add_selected_exact_groups(out, registry, exact_groups, state);

type2_group_map type2_groups =
    build_type2_groups(registry, exact_groups, state);
add_selected_type2_groups(out, registry, type2_groups, state);

add_unmatched_exact_groups(out, registry, exact_groups, state);
```

This is clearer than the previous monolithic implementation, but the surrounding
private helpers are still a bit confusing and may benefit from a follow-up
organization pass.

## Task

Investigate the best next refactor for the content-group-building code.

Do not assume the current structure should be preserved, and do not assume it
should be split into more files. Read the code and evaluate the options on their
own merits.

Focus on:

- understandability of the grouping and selection flow
- clarity of ownership for suppression/coverage state
- whether helper names match the behavior they implement
- whether a small private abstraction, a file split, or no further split is the
  cleanest next step
- whether any refactor would risk performance or change candidate-selection
  behavior

## Relevant Files

- [src/move_registry/content_group_builder.cpp](/home/nick/Projects/srcMLBuildTemplate/srcMove/src/move_registry/content_group_builder.cpp:1)
- [src/move_registry/content_group_builder.hpp](/home/nick/Projects/srcMLBuildTemplate/srcMove/src/move_registry/content_group_builder.hpp:1)
- [src/move_registry/content_groups.hpp](/home/nick/Projects/srcMLBuildTemplate/srcMove/src/move_registry/content_groups.hpp:1)
- [src/move_registry/candidate_registry.hpp](/home/nick/Projects/srcMLBuildTemplate/srcMove/src/move_registry/candidate_registry.hpp:1)
- [src/move_candidate.hpp](/home/nick/Projects/srcMLBuildTemplate/srcMove/src/move_candidate.hpp:1)

## Current Behavior To Preserve

Recent work made structural-child candidates compete with diff-wrapper
candidates, then suppresses lower-priority or overlapping matches during content
group selection. That behavior is covered by the existing e2e suites and should
not change during an organization-only refactor.

In particular, preserve:

- exact matches before Type-2 recovery
- single-child wrapper priority behavior
- suppression of already-covered candidates
- unmatched leftover groups after selected exact and Type-2 groups
- structural child candidates remaining available when wrapper candidates do not
  match

## Suggested Validation

After any code change, run:

```bash
cmake --build build
python3 tests/regression/xml/run.py build/srcMove
python3 tests/regression/source/run.py
python3 benchmarks/bigclonebench/run.py --clone-type type1 --limit 10
```

For broader confidence after a behavior-touching change, also run:

```bash
python3 benchmarks/bigclonebench/run.py --clone-type type1 --limit 1000
```

## Notes For The Next AI

The user wants high-quality, easy-to-understand code and is especially
interested in organization and performance. Prefer a small, inspectable refactor
over a broad rewrite unless the code clearly supports a larger boundary.

If you recommend a refactor instead of implementing it, give a concrete reason
and identify the smallest useful next step.
