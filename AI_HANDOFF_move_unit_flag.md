# srcMove Handoff: Configurable Structural-Child Move Detection

## Situation

`srcMove` was recently changed so that large leaf diff wrappers can be split into structural child move candidates instead of being matched only as one giant hunk.

That fix was added to solve missed move detection in large srcDiff files such as:

- `examples/wowy_advanced_analytics/wowy_advanced_analytics.214_215.v000214-to-v000215.546108276d6d-to-b12c1d312b5c.position.diff.xml`

The key internal option already exists:

- `region_filter_options.expand_structural_children`

It currently defaults to `true` in:

- [src/region_filter.hpp](/home/nick/Projects/srcMLBuildTemplate/srcMove/src/region_filter.hpp:1)
- [src/region_filter.cpp](/home/nick/Projects/srcMLBuildTemplate/srcMove/src/region_filter.cpp:1)

The user wants this behavior to be configurable from the CLI, but the task was interrupted for a more urgent issue.

## User Intent

The user asked:

- should the fix be a configurable variable?
- can it be done simply?
- they want it presented soon

So the follow-up implementation should be as small and easy to explain as possible.

## Recommended Minimal Approach

Do **not** introduce a large mode system unless needed.

Use a single boolean CLI flag:

- `--no-structural-children`

Behavior:

- default: current behavior stays the same (`expand_structural_children = true`)
- flag present: disable subtree expansion and fall back to wrapper-only leaf matching

This is the lightest change and easiest to demo:

- “new behavior is on by default”
- “old behavior can still be reproduced with one flag”

## Files To Edit

Most likely only these:

- [src/cli.hpp](/home/nick/Projects/srcMLBuildTemplate/srcMove/src/cli.hpp:1)
- [src/cli.cpp](/home/nick/Projects/srcMLBuildTemplate/srcMove/src/cli.cpp:1)
- [src/pipeline.hpp](/home/nick/Projects/srcMLBuildTemplate/srcMove/src/pipeline.hpp:1)
- [src/pipeline.cpp](/home/nick/Projects/srcMLBuildTemplate/srcMove/src/pipeline.cpp:1)
- [src/main.cpp](/home/nick/Projects/srcMLBuildTemplate/srcMove/src/main.cpp:1)

No `region_filter` behavior change should be needed beyond wiring the option through.

## Suggested Implementation

### 1. Add a CLI option field

In `cli_options`, add:

```cpp
bool expand_structural_children = true;
```

### 2. Parse a simple flag

In `parse_cli(...)`, support:

```text
--no-structural-children
```

When present:

```cpp
opts.expand_structural_children = false;
```

Also add it to `--help`.

Suggested help text:

```text
--no-structural-children
    Disable subtree expansion inside large leaf diff wrappers.
    Use only wrapper-level leaf candidates for move detection.
```

### 3. Thread the option into the pipeline

Change the pipeline signature from:

```cpp
summary run_pipeline(const std::string &srcdiff_in_filename,
                     const std::string &srcdiff_out_filename);
```

to something like:

```cpp
summary run_pipeline(const std::string &srcdiff_in_filename,
                     const std::string &srcdiff_out_filename,
                     bool               expand_structural_children);
```

Then in `pipeline.cpp`:

- get default filter options
- override:

```cpp
filter_options.expand_structural_children = expand_structural_children;
```

### 4. Pass it from `main.cpp`

After parsing CLI options:

```cpp
srcmove::run_pipeline(
    opts.input_path,
    opts.output_path,
    opts.expand_structural_children);
```

## Validation

The user explicitly said:

- **do not build**

That instruction came after asking to proceed, so it should be respected unless they later change their mind.

If later validation is allowed, good checks would be:

- existing custom suite:
  - `python3 test/e2e_custom/run_tests.py build/srcMove`
- compare behavior with and without the flag on the Wowy example

Expected demo story:

- without flag: current improved move detection
- with `--no-structural-children`: old coarse wrapper behavior

## Git / Branch Notes

I attempted to create a new branch for this work, but from this environment git ref updates were blocked by sandbox permissions on `.git`.

Observed failures included:

- inability to create branch refs under `.git/refs/heads/...`
- later an escalated branch-creation attempt was interrupted before approval

So if the next AI is asked to actually do the work on a branch:

- ask the user to create/switch branch manually, or
- request approval for:

```bash
git checkout -b feat-srcmove-move-unit-mode
```

## Important Context From Previous Fix

The structural-child behavior exists because whole-file delete/insert wrappers were hiding moved functions/classes/imports inside them.

Relevant regression fixture already added:

- [test/e2e_custom/cases/archive_whole_file_split_structural/input.xml](/home/nick/Projects/srcMLBuildTemplate/srcMove/test/e2e_custom/cases/archive_whole_file_split_structural/input.xml:1)

That fixture is useful when explaining why the toggle matters.

## Summary For Next AI

Implement the smallest possible CLI toggle:

- add `--no-structural-children`
- keep current behavior as default
- wire `opts.expand_structural_children` through `main -> pipeline -> filter_options`
- do not build unless the user explicitly allows it

