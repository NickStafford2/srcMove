# srcMove — Move Annotation for srcDiff XML

srcMove is a C++ command-line tool that post-processes srcDiff XML and annotates
delete/insert regions that represent relocated source code. Matching regions
receive a shared `mv:id` plus directional `mv:from` and `mv:to` XPath
relationships.

The project is Nicholas Stafford's master's thesis work on making structured
source-code differences more interpretable, with particular emphasis on moves
across file boundaries.

## Project role

srcMove is the thesis's primary program and research deliverable. It is a
portable CLI rather than a component tied to one development workspace: it can
be built wherever srcML and srcReader are available, and it consumes XML
produced by srcDiff.

[SrcMLBuildTemplate](https://github.com/NickStafford2/SrcMLBuildTemplate)
provides the recommended reproducible workspace for building the complete
toolchain. The companion `srcVisual` project presents srcDiff and srcMove XML in
a synchronized code-editor-like interface so detected moves can be inspected
across files.

## What it does

Given a srcDiff XML document, srcMove:

1. streams all `diff:delete` and `diff:insert` regions from single-file or
   archive input
2. selects leaf diff regions and eligible structural children as move
   candidates while excluding whitespace-only and very small payloads
3. builds canonical representations from the embedded srcML structure
4. uses FNV-1a hashes as indexes, then confirms exact matches with the full
   canonical text
5. recovers Type-2 matches by consistently normalizing eligible names and
   literal categories
6. suppresses overlapping parent/child selections and annotates every group
   containing both deletes and inserts

The output remains srcDiff XML and can be consumed by downstream analysis or
visualization tools.

## Installation

### Recommended: reproducible workspace

For macOS users, evaluators, and new contributors, the easiest supported path
is [SrcMLBuildTemplate](https://github.com/NickStafford2/SrcMLBuildTemplate).
It builds the complete native dependency chain inside Ubuntu Docker, keeps the
toolchain isolated from the host system, and exposes the resulting files to
normal macOS editors.

Install Docker Desktop, then run:

```bash
git clone https://github.com/NickStafford2/SrcMLBuildTemplate.git
cd SrcMLBuildTemplate
make srcmove
./bin/srcml-dev-shell srcMove --version
```

The build scripts clone missing source repositories and build srcML, srcReader,
srcDiff, and srcMove in dependency order.

#### Repository and workspace model

srcMove is an independent Git repository. It is commonly checked out inside
the SrcMLBuildTemplate workspace scaffold, but the parent directory and sibling
repositories are not part of this repository. The scaffold provides a
reproducible Docker environment and coordinates dependency builds; srcMove owns
its source, build interface, tests, and documentation.

The usual workspace layout is:

```text
srcMLBuildTemplate/
  srcML/
  srcML-install/
  srcReader/
  srcDiff/
  srcMove/
  srcVisual/
```

The workspace is a convenience and the recommended installation experience,
not an architectural dependency of srcMove.

### Standalone build

To build srcMove outside SrcMLBuildTemplate, provide the same dependencies
yourself:

- CMake 3.20+
- Ninja
- a C++17 compiler, preferably Clang or GCC
- the `libxml2` development package
- a `srcReader` checkout and build
- a local srcML development installation
- the `srcdiff` executable for source-pair tests and generating input XML

From the srcMove repository root:

```bash
make build
make test
```

The Makefile is the canonical developer interface when the dependency paths use
the expected sibling layout. Run `make help` for focused unit and
regression-suite targets.

For any other layout, configure the paths explicitly:

```bash
cmake -S . -B build \
  -G Ninja \
  -DWORKSPACE_ROOT=/path/to/workspace \
  -DSRCREADER_ROOT=/path/to/srcReader \
  -DSRCML_INSTALL_PREFIX=/path/to/srcML-install

cmake --build build
```

### Run

```bash
./build/srcMove path/to/srcdiff.xml
```

The default output is `srcmove.xml` in the current directory. An explicit
output path and JSON results file can also be supplied:

```bash
./build/srcMove input.srcdiff.xml output.srcmove.xml \
  --results results.json
```

CLI synopsis:

```text
srcMove <srcdiff.xml> [out.xml] [--results results.json]
        [--results-only] [--min-granularity statement|fragment]
        [--profile] [-v]
srcMove --help
srcMove --version
```

- `--results <file>` writes versioned move groups, XPaths, raw texts, candidate
  counts, group classifications, and match kinds as JSON. The top-level
  `results_schema_version` is currently `1`.
- `--results-only` writes the JSON result without reparsing and writing annotated
  XML. It requires `--results <file>` and does not accept an output XML path.
- `--min-granularity statement|fragment` selects the minimum move unit.
  `statement` is the default; `fragment` enables low-level diff fragments for
  specialized analysis.
- `--profile` writes coarse `profile.<stage>_ms=<milliseconds>` timings to
  standard error.
- `-v` and `--verbose` print selected move-match diagnostics to standard output.

## Output format

srcMove adds `xmlns:mv="http://www.srcML.org/srcMove"` to the root unit and
patches the start tags of selected diff regions or structural children:

- `mv:id` identifies one move group.
- `mv:to` lists destination XPath values on deletions.
- `mv:from` lists source XPath values on insertions.

Multiple partners are represented as an XPath union separated by ` | `.

```xml
<unit xmlns="http://www.srcML.org/srcML/src"
      xmlns:diff="http://www.srcML.org/srcDiff"
      xmlns:mv="http://www.srcML.org/srcMove">
  <diff:delete mv:id="97b1dcdaf"
               mv:to="/src:unit[1]/diff:insert[1]">int a;</diff:delete>
  <diff:insert mv:id="97b1dcdaf"
               mv:from="/src:unit[1]/diff:delete[1]">int a;</diff:insert>
</unit>
```

Legacy unnamespaced `move` attributes are preserved. They do not currently
prevent a selected region from also receiving the `mv:*` annotations produced
by this pipeline.

## Matching scope

The deterministic classifier reports `type1`, `type2`, and `type3`;
pairs below the Type-3 threshold remain unmatched. Hash equality alone never
establishes a match. The normalization rules, 0.70 similarity formula,
ambiguity policy, and performance safeguards have one canonical description in
[Architecture](doc/architecture.md#matching-and-group-semantics).

## Documentation and evaluation

- [Documentation index](doc/README.md)
- [Architecture](doc/architecture.md)
- [srcMove History](srcmove_history/docs/README.md)
- [Correctness tests](tests/README.md)
- [Benchmarks](benchmarking/README.md)
- [BigMoveBench](bigMoveBench/README.md)

Small deterministic XML fixtures live under `tests/regression/xml/cases/`.
Generated source-pair tests and BigCloneBench evaluation are documented by the
test and benchmark entry points above.

## Versioning

The project version has one source of truth: [`VERSION`](VERSION). CMake reads
that file during configuration, and `srcMove --version` reports the configured
value. Update `VERSION` when preparing a release-worthy change:

- increment the patch version for backward-compatible fixes
- increment the minor version for backward-compatible features or substantial
  algorithm changes
- increment the major version for incompatible CLI, output-format, or behavior
  contracts after the project reaches 1.0

While srcMove remains in initial `0.x` development, an incompatible change may
advance the minor version instead of declaring the interface stable at 1.0.

## Developer utilities

The build also produces text-oriented inspection tools from `src/tools/`:

- `srcdiff_render`
- `srcdiff_highlight`
- `srcdiff_highlight_pos`

These utilities are for debugging srcDiff/srcMove XML and use the same
srcReader/srcML stack.

## Current limitations

- Type-4 moves are not supported.
- Type-2 normalization is lexical and consistency-sensitive; it is not semantic
  equivalence. Type-3 uses bounded syntactic similarity and likewise does not
  imply semantic equivalence.
- There is no probabilistic confidence score, locality model, or behavioral
  interpretation.
- Many-to-many and unequal-count groups are classified but not fully paired or
  disambiguated.
- srcMove depends on candidate regions exposed by srcDiff and is not a
  general-purpose diff engine.

Research directions include richer move classification, contextual scoring,
and better ambiguous-group disambiguation.

## License

GPL-3.0-only. See `LICENSE`.

## Acknowledgements

srcMove builds on the srcML/srcDiff ecosystem and uses srcReader and srcML for
streaming parsing and writing of srcML-derived XML formats.
