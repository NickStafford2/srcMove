# srcMove — Move Annotation for srcDiff XML

srcMove is a C++ tool that post-processes `srcDiff` XML output and annotates detected “move” operations by adding a stable `move` id (and an `xpath` location) onto matching `diff:delete` / `diff:insert` regions.

This repository is being developed as part of a master’s thesis project focused on improving the interpretability of fine-grained source-to-source diffs produced in the srcML/srcDiff ecosystem.

## What it does

Given a `srcdiff.xml` file (the XML produced by `srcDiff`), `srcMove`:

1. streams the XML and collects all `diff:insert` and `diff:delete` regions
2. filters the regions to choose good “move units” (default: leaf-only diff regions, skip whitespace-only, skip regions already marked with `move`)
3. hashes each region by its inner text content
4. groups deletes/inserts by content (hash + exact text equality confirmation)
5. assigns a new move id to each group that has both deletes and inserts
6. writes a new XML file identical to the input, except:
   - adds `move="<id>"` to the START tag of matched `diff:insert` and `diff:delete`
   - adds `xpath="<path>"` to those tags (even if `move` already existed)

Output is a new XML file (default: `diff_new.xml`) you can feed into downstream tooling, renderers, or visualizers.

## Quick start

### Prerequisites

- CMake 3.20+
- A C++17 compiler (Clang or GCC recommended)
- `libxml2` development package
- A workspace that contains:
  - `srcReader` (sibling repository)
  - a built/installed `srcML` (expected at `srcML-install`)

The project assumes a workspace layout like:

```
WORKSPACE_ROOT/
srcMove/           # this repo
srcReader/         # dependency repo
srcML-install/     # srcML install prefix (include/ and lib/)

````

You can override these paths at configure time (see below).

### Build

From the repository root:

```bash
cmake -S . -B build
cmake --build build -j
````

If your workspace layout differs, configure with:

```bash
cmake -S . -B build \
  -DWORKSPACE_ROOT=/path/to/workspace \
  -DSRCREADER_ROOT=/path/to/srcReader \
  -DSRCML_INSTALL_PREFIX=/path/to/srcML-install
cmake --build build -j
```

### Run

```bash
./build/srcMove path/to/srcdiff.xml
```

Optionally specify an output filename:

```bash
./build/srcMove path/to/srcdiff.xml out.xml
```

If no output file is provided, `srcMove` writes `diff_new.xml` in the current working directory.

## Example: run against included tests

This repo includes small, focused test fixtures under `test/`.

For example:

```bash
./build/srcMove test/simple/diff.xml test/simple/diff_new.xml
```

Or:

```bash
./build/srcMove test/function_content/diff_pos.xml test/function_content/diff_new.xml
```

Each `test/*/` directory contains an `original.cpp` and `modified.cpp` plus `diff.xml` (and in many cases an example `diff_new.xml`) to make it easy to see what changed.

## How it works (high level)

The pipeline (see `src/pipeline.cpp`) is intentionally simple and streaming-friendly:

* `collect_all_regions` (`src/move_region.*`)

  * single pass over `srcml_reader`
  * records every diff region with nesting metadata and inner text
  * detects pre-existing `move` attributes and tracks the max id

* `filter_regions_for_registry` (`src/region_filter.*`)

  * selects which regions become candidates for move detection
  * defaults:

    * leaf-only diff regions
    * skip whitespace-only regions
    * skip regions that already have a `move` attribute

* `move_registry` + group builder (`src/move_registry.*`, `src/move_groups_builder.*`)

  * buckets candidates by a fast 64-bit FNV-1a hash of raw inner text
  * optionally confirms equality by exact `full_text` to avoid hash collisions
  * produces “content groups” that can be classified (1-to-1, many-to-many, etc.)

* `annotation_plan` + writer (`src/annotation_plan.*`, `src/annotation_writer.*`)

  * assigns a new `move` id per group that has both deletes and inserts
  * rewrites the XML in a second pass
  * patches only the START tags of `diff:insert` / `diff:delete`
  * writes `xpath` values using a streaming path builder (`src/xpath_builder.*`)

This design keeps memory usage predictable and avoids generating the full D×I pair explosion unless explicitly requested.

## Output format

`srcMove` edits only the START tags of `diff:insert` and `diff:delete` elements:

* `move="<id>"` is added only if the element was not already marked by srcDiff
* `xpath="<path>"` is written even if `move` already existed

The produced output remains valid srcDiff XML and should be usable anywhere the original was used.

## Included developer tools

This repository also builds a few small utilities under `src/tools/`:

* `srcdiff_render`
* `srcdiff_highlight`
* `srcdiff_highlight_pos`

These are intended for debugging and inspection during development (they link against the same srcReader/srcML stack).

## Project structure

* `src/`

  * core pipeline and move detection logic
* `src/tools/`

  * small inspection utilities (debug-focused)
* `doc/`

  * diagrams, notes, terms, and papers reviewed during thesis work
* `test/`

  * compact fixtures (original/modified + sample diffs)

## Limitations (current)

* Matching is currently content-based (raw inner text) and does not use AST-aware similarity scoring.
* Pairing is currently a fast baseline (greedy 1-to-1 consumption inside each content group).
* Many-to-many groups are identified but not fully disambiguated into specific move pairings.
* This tool expects srcDiff XML input and is not a general-purpose diff engine.

These are active areas for improvement as the thesis work progresses.

## Roadmap

Planned directions (subject to change as research evolves):

* richer move classification (copy vs move vs repeated insertion)
* better disambiguation strategies for many-to-many groups
* scoring models that incorporate structural context (xpath, node type, surrounding tokens)
* a dedicated visualization companion tool (side-by-side view with insert/delete/move highlighting)

## License

GPL-3.0-only. See `LICENSE`.

## Acknowledgements

This project builds on the srcML/srcDiff tooling ecosystem and depends on `srcReader` and `srcML` for streaming parsing and writing of srcML-derived XML formats.
