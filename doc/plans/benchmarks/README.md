# BigCloneBench Suite Plan

## Goal

Build one reproducible command that measures how well the current srcMove
implementation distinguishes whole-fragment moves/clones from non-moves using
BigCloneBench:

```bash
make bigclonebench-suite MODE=sample
make bigclonebench-suite MODE=census
```

The suite must report accuracy and srcMove performance by benchmark category.
It must not hide unsupported categories or combine unlike oracles into one
misleading percentage. BigCloneBench is clone ground truth rather than edit
history, so the suite continues to synthesize a declared before/after move from
each selected pair.

The current conversion methodology remains canonical in
[`doc/bigclonebench_srcmove_conversion.md`](../../bigclonebench_srcmove_conversion.md).
Operational commands remain in
[`benchmarks/bigclonebench/README.md`](../../../benchmarks/bigclonebench/README.md).
This document defines the desired suite and caching work, not current behavior.

## Required Evaluation Matrix

Report each row separately:

| Pair set | Selection | Required measurement |
| --- | --- | --- |
| Type 1 positives | BigCloneBench `syntactic_type = 1` | Whole-fragment detection and `exact` classification |
| Type 2 positives | BigCloneBench `syntactic_type = 2` | Whole-fragment detection and `type2` classification |
| Type 3 positives | `syntactic_type = 3`, stratified by line/token similarity | Whole-fragment detection by any match kind now; strict Type-3 classification after srcMove implements it |
| Weak/semantic positives | Explicit low-similarity BigCloneBench strength bucket | Exploratory whole-fragment detection until a defensible Type-4 mapping and srcMove oracle exist |
| Known false positives | BigCloneBench `false_positives`, stratified by stored syntactic type and similarity | Whole-fragment rejection and false-positive acceptance rate |

BigCloneBench does not provide four populated false-positive tables or a simple
`syntactic_type = 4` stratum. The local false-positive table is overwhelmingly
Type 3 and has only two Type-2 rows. The suite must report the strata the dataset
actually contains rather than invent Type-1 or Type-4 false-positive rates.

Type-3 support is a program requirement. Initial runs remain observational so
Deckard-, SourcererCC-, or other similarity-based srcMove implementations can be
developed without changing historical ground truth. Every Type-3 report must
preserve both:

- whole-fragment detection, independent of reported match kind
- strict classification under the oracle version active for that run

When srcMove gains a stable `type3` result category, a new versioned strict
oracle may require it. Old results retain their original oracle and remain
comparable.

Known-false-positive cases use the existing symmetric negative oracle: only a
reported move linking the complete generated source and target fragments counts
as acceptance of the false-positive pair. No move passes. Smaller incidental
child moves also pass but receive their own count.

No pair set has a minimum token-count eligibility requirement. Preserve
`min_tokens` as metadata and report size strata, but include fragments below 50
tokens in both sample frames and census denominators.

## Deduplication Policy

Deduplication is the default and is required for headline results. Repeated
database rows must not cause srcMove to execute the same test repeatedly.

Define test identity from the exact generated old/new source bytes, including
raw formatting and comments. Do not use whitespace-insensitive normalization:
those differences are meaningful Type-1 inputs. The default selector also keeps
one deterministic direction for an unordered fragment pair. An explicit
research option may evaluate both directions, but the normal suite does not.
Synthetic wrapper names and context must derive from the content identity, not
BigCloneBench row or function IDs; otherwise duplicate fragments would produce
artificially different generated files and evade deduplication.

For every retained test, preserve:

- the generated-input SHA-256 identity
- every contributing BigCloneBench row ID
- duplicate-row multiplicity
- functionality IDs and source fragment IDs
- the selected direction and any excluded reverse duplicate

Reports show both BigCloneBench row coverage and unique generated-test count.
This removes duplicate execution without discarding information about the
dataset population. `--dedupe none` remains an audit option, not the default
accuracy run.

## Compile BigCloneBench Once

Repeatedly opening H2, extracting source ranges, hashing the 5.5 GiB database,
and creating mutable case directories is too expensive. Add an explicit compile
stage that produces a local, immutable benchmark dataset:

```text
benchmark-data/bigclonebench/compiled/<dataset-id>/
  manifest.json
  catalog.sqlite
  fragments/
    <sha256>.java
  selections/
    <selection-id>.json
```

`catalog.sqlite` is a srcMove-owned read-optimized index, not a replacement for
BigCloneBench ground truth. It stores:

- function IDs, source locations, sizes, projects, and extracted-fragment hashes
- positive and known-false-positive pair rows
- syntactic type, similarity, functionality, judgment, and confidence fields
- exact generated-test dedupe groups and row multiplicities

The fragment store contains each exact extracted source fragment once, addressed
by SHA-256. Do not copy the complete IJaDataset. Copy only unique fragments
needed by indexed eligible rows. SQLite rows refer to those immutable fragment
objects.

The compile manifest records the BigCloneBench database checksum, H2 identity,
source-file checksums, LF-based extraction policy, compiler schema, and extractor
version. Development reuse may first compare a saved file identity tuple such as
path, size, and modification time to avoid rehashing the 5.5 GiB database.
Publication mode must rehash and verify the original database and selected
sources before accepting the cache.

H2 access remains serial. After compilation, selection, source materialization,
srcDiff generation, and srcMove execution no longer need H2 and may use bounded
parallel workers.

## Reuse Instead of Regenerate

Use the existing content-addressed benchmark stages and narrow each cache key to
the inputs that can actually change it:

1. **Compiled dataset:** BigCloneBench/H2/source identity plus extraction schema.
2. **Selection:** compiled dataset ID plus filters, strata, direction, seed, and
   dedupe policy.
3. **Input snapshot:** selection ID plus synthetic-wrapper version.
4. **srcDiff corpus:** input snapshot ID, srcDiff executable/configuration, and
   semantic-eligibility oracle.
5. **srcMove evaluation:** corpus ID, srcMove executable/configuration, and
   scoring-oracle version.

The BigCloneBench adapter should materialize generated old/new files directly
into the immutable input snapshot from the fragment store. Avoid a second tree
of long-lived generated case files. Hard-link immutable content when possible
and copy only as a portability fallback.

Changing srcMove must rerun only stage 5. Changing a Type-3 matching threshold
must not requery H2, re-extract Java, or rerun srcDiff unless it changes the
selected inputs. Changing the synthetic wrapper invalidates snapshots and
downstream corpora but not the compiled dataset.

## Suite Modes

### Sample

The default development mode is a deterministic, seeded, stratified sample. It
must include every supported pair set and enough size, functionality, project,
similarity, and raw-text strata to expose regressions quickly. The exact seed,
frame, selected IDs, and exclusions are saved.

### Census

Census mode evaluates every eligible unique generated test after default
deduplication. It reports pre-deduplication rows, unique tests, exclusions, and
all upstream/tool failures. Census means the complete declared eligible frame,
not every row in the database regardless of size, internal status, confidence,
or source availability.

Both modes keep tuning and held-out evaluation selections separate.

## Command and Output Requirements

The final command should compile or reuse missing stages automatically:

```bash
make bigclonebench-suite MODE=sample
```

Useful overrides may include:

```text
MODE=sample|census
ROLE=tuning|evaluation
JOBS=<bounded worker count>
SEED=<integer>
VERIFY_SOURCE=0|1
```

The CLI prints one compact section per pair set and never one blended accuracy
number:

```text
BigCloneBench suite
  dataset: <dataset-id> (compiled cache reused)

  Type 1                 detected/classified ...   srcMove time ...
  Type 2                 detected/classified ...   srcMove time ...
  Type 3 very strong     detected ... classified ...
  Type 3 strong          detected ... classified ...
  Type 3 moderate        detected ... classified ...
  Weak/semantic          detected ... classified ...
  Known false positives rejected ... accepted ... incidental ...

  unique tests ...   source rows ...   srcDiff eligible ...
  srcMove total ...  throughput ...    peak memory ...
```

Time these phases separately:

- one-time dataset compilation
- selection and snapshot materialization
- srcDiff corpus generation
- srcMove execution per pair set

Cache-hit time is reported as reuse/verification overhead, not as fresh
generation time. The primary speed comparison between srcMove builds replays the
same immutable corpus and excludes BigCloneBench and srcDiff preparation.

## Implementation Order

Phase 1 is implemented by `benchmarks/bigclonebench/compile.py` and
`compiled.py`: serial H2 bulk export, a versioned SQLite catalog, exact fragment
objects, atomic publication, catalog/full validation, and metadata-based reuse.
The compiler has fixture coverage and a real-data smoke check. The compiled
catalog is not yet consumed by case selection or snapshot materialization;
those remain the next phases.

1. Add a read-only compile command, SQLite catalog schema, fragment store, and
   manifest validation.
2. Move exact generated-input dedupe into compilation/selection and retain row
   multiplicity metadata.
3. Materialize BigCloneBench inputs directly into content-addressed snapshots;
   remove repeated extraction and mutable case-directory dependence.
4. Add `bigclonebench-suite` orchestration for Type 1, Type 2, and known false
   positives, with sample and census modes.
5. Add stratified Type-3 and weak/semantic observational reports without
   pretending current srcMove supports strict Type-3/Type-4 classification.
6. Version and enable the strict Type-3 oracle when srcMove exposes a stable
   Type-3 match category.
7. Add bounded parallel srcDiff/srcMove execution, corpus reuse diagnostics, and
   concise combined timing output.

## Completion Criteria

The upgrade is complete when:

- one command runs or reuses every declared suite section
- unchanged dataset inputs are not requeried, re-extracted, or rehashed during
  ordinary development runs
- no duplicate generated test executes by default
- Type-1, Type-2, Type-3-strength, weak/semantic, and false-positive results are
  reported separately with auditable denominators
- the same corpus can evaluate multiple srcMove builds without rerunning srcDiff
- sample and census selections are reproducible from their manifests
- timing distinguishes compilation, srcDiff, srcMove, and cache verification
- all failures and exclusions remain preserved as data
