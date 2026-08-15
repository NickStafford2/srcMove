# srcMove Handoff: Investigate Annotation Performance

> Historical note: commit `3afbc86` implemented this handoff's primary
> recommendation by retaining candidate XPaths and removing the extra
> `collect_start_node_xpaths(...)` pass. The profiles below describe the older
> three-pass pipeline. Current performance work is planned in the
> [parallel programming upgrade plan](../parallel_programming_upgrade_plan.md).

## Situation

Recent profiling shows `srcMove` spends most runtime in XML parsing and
annotation, not content grouping.

Two useful profiles were collected with the release binary:

### BigCloneBench Type-1

Command:

```bash
scripts/build_release.sh
python3 benchmarks/profile.py --prepare-bigclonebench
```

Profile file:

```text
profile-results/runs/srcmove-profile_20260728T003733Z_bigclonebench_bigclonebench-type1-request1000-cases915-r3.txt
```

Median phase summary:

```text
pipeline.total_ms             17.056
pipeline.annotation_ms         7.770  (~45.6%)
pipeline.parse_regions_ms      6.743  (~39.5%)
pipeline.filter_candidates_ms  2.330  (~13.7%)
content_groups.total_ms        0.012  (~0.1%)

annotation.collect_xpaths_ms   3.197  (~18.7%)
annotation.write_stream_ms     4.529  (~26.6%)
```

### Large OpenCV srcDiff

Command:

```bash
scripts/build_release.sh
python3 benchmarks/profile.py --suite opencv --repeats 1 --no-latest
```

Profile file:

```text
profile-results/runs/srcmove-profile_20260728T004031Z_opencv_opencv-large-r1.txt
```

Timing summary:

```text
pipeline.total_ms              29276.276
pipeline.annotation_ms         20965.074  (~71.6%)
pipeline.parse_regions_ms       8311.091  (~28.4%)
content_groups.total_ms            0.004

annotation.collect_xpaths_ms    8906.706  (~30.4%)
annotation.write_stream_ms     11736.469  (~40.1%)
```

## Main Finding

The current annotation path does multiple full XML passes over the input:

1. `collect_all_regions(...)` during pipeline parsing.
2. `collect_start_node_xpaths(...)` inside `build_move_tags(...)`.
3. `write_with_move_annotations(...)` to copy and patch the output XML.

On the 76 MB OpenCV srcDiff, this repeated streaming dominates total runtime.

Content grouping is not currently a performance priority for these workloads.

## Relevant Files

- `src/pipeline.cpp`
- `src/writer/annotation_plan.cpp`
- `src/writer/annotation_plan.hpp`
- `src/writer/annotation_writer.cpp`
- `src/writer/annotation_writer.hpp`
- `src/srcml_reader.hpp`
- `src/xpath_builder.*` if present in the checkout
- `src/parse/diff_region.cpp`
- `benchmarks/profile.py`
- `src/profile.hpp`

## Investigation Goal

Find a way to reduce annotation overhead, especially the extra
`annotation.collect_xpaths_ms` pass, without changing output XML or move summary
behavior.

Start by answering:

- Can `diff_region` or `move_candidate` carry enough XPath information from the
  initial parse to avoid `collect_start_node_xpaths(...)`?
- Can annotation build partner XPath attributes lazily during the write pass
  instead of precollecting all start-node XPaths?
- Can `write_with_move_annotations(...)` avoid any expensive string work for
  nodes that are not tagged?
- Is `srcml_reader::get_current_xpath()` the main cost, or is XML tokenization
  itself dominant?

## Likely Optimization Direction

The most promising change is to remove the full XPath-collection pass.

Possible approaches:

1. Store candidate XPath at candidate creation time.
   - Pros: annotation tags can use candidate-owned XPath strings directly.
   - Cons: candidate extraction currently happens from parsed diff regions, so
     verify XPath availability and stability there.

2. Extend `diff_region` to record the start XPath during `collect_all_regions`.
   - Pros: reuses the initial XML pass.
   - Cons: structural-child candidates may need child-specific XPaths, not just
     wrapper region XPaths.

3. Build tags with candidate start indexes, then resolve partner XPaths during
   the annotation write pass.
   - Pros: avoids precollecting every start-node XPath.
   - Cons: partner attributes need both sides' XPath strings before writing a
     tagged node. If the partner appears later in the stream, this may require
     delayed writes or a smaller targeted prepass.

Be careful with option 3: current output writes `mv:from` / `mv:to` partner
XPath attributes immediately on each tagged start node.

## Behavior To Preserve

- XML output must remain byte-for-byte compatible with expected fixtures except
  for intentional changes.
- Move IDs and partner XPath attributes must remain stable enough for existing
  tests.
- Existing pre-marked move behavior must not regress.
- BigCloneBench known failures are not part of this optimization; do not mix
  oracle or detection changes into annotation performance work.

## Validation

Correctness:

```bash
scripts/build_release.sh
python3 tests/regression/xml/run.py build-release/srcMove
python3 tests/regression/source/run.py
python3 benchmarks/bigclonebench/run.py --clone-type type1 --limit 10 --srcmove build-release/srcMove
```

Performance:

```bash
python3 benchmarks/profile.py --prepare-bigclonebench --label annotation-before
python3 benchmarks/profile.py --suite opencv --repeats 1 --label opencv-before
```

After a change, rerun the same commands with `annotation-after` /
`opencv-after` labels and compare:

- `annotation.collect_xpaths_ms`
- `annotation.write_stream_ms`
- `annotation.total_ms`
- `pipeline.parse_regions_ms`
- `pipeline.total_ms`

## Notes

`benchmarks/profile.py --prepare-bigclonebench` now continues profiling if
BigCloneBench validation reports known failures, as long as the active manifest
was generated.

The OpenCV profile is a large XML I/O/annotation stress test. It currently has
nearly no candidate/grouping cost, so it is not a content-group stress test.
