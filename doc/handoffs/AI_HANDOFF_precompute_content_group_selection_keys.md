# srcMove Handoff: Precompute Content-Group Selection Sort Keys

## Context

`add_selected_exact_groups(...)` in
`src/move_registry/content_group_builder.cpp` sorts exact groups before
selection. The comparator currently recomputes each group's selection tier, span
size, and minimum candidate id on every comparison.

The current sort is effectively:

```text
O(G log G * K)
```

where:

- `G` is the number of exact groups
- `K` is the average number of candidate ids scanned per compared group

With cached keys, this can become:

```text
O(total_group_ids + G log G)
```

## Suggested Refactor

Add a private cached key type near the existing selection-order helpers:

```cpp
struct selection_sort_key {
  selection_tier tier = selection_tier::primary;
  std::size_t    span_size = 0;
  candidate_id   min_id = static_cast<candidate_id>(-1);
};
```

Build one key per `pending_group`, then sort an index vector instead of sorting
the `pending_group` vector directly. Sorting indices avoids moving group objects
that own `std::vector<candidate_id>` members.

## Important Behavior To Preserve

The current selected-exact order is also the order later used by
`add_unmatched_exact_groups(...)`, because `exact_groups` is sorted in place.

If this is changed to an index/order vector, either:

- use the same order vector for unmatched leftover emission, or
- intentionally document and test any output-order change.

Do not change selection semantics while doing this optimization:

- exact groups are selected before Type-2 recovery
- primary groups precede single-child wrapper fallback groups
- larger span groups precede smaller span groups within the same tier
- minimum candidate id remains the final deterministic tie-breaker

## Validation

Run at least:

```bash
cmake --build build
python3 test/e2e_custom/run_tests.py build/srcMove
python3 test/e2e_generated/run_tests.py
python3 test/e2e_bigclonebench/run_tests.py --clone-type type1 --limit 10
```

For performance validation, compare `--profile` output before and after on a
large BigCloneBench run or a stress input, focusing on:

- `profile.content_groups.exact_select_ms`
- `profile.content_groups.total_ms`
- `profile.pipeline.total_ms`
