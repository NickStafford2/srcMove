# Normalized Census Execution Plan

Status: design only. This document does not describe current behavior.

## Goal

Make a full Type-3 census practical by representing a case as database rows that
reference reusable immutable objects. Do not materialize one permanent directory
and four generated Java files for every fragment pair.

The compiled BigCloneBench catalog already normalizes millions of pairs onto a
much smaller fragment store. The census path should preserve that normalization
instead of expanding it again during snapshot creation.

## Storage Model

Keep dataset evidence, an immutable execution plan, and mutable execution state
separate:

```text
compiled dataset (immutable)
  catalog.sqlite
  fragments/<fragment-sha256>.java

generated object store (immutable, content addressed)
  generated-objects/<object-sha256>.java

execution plan (immutable)
  plans/<plan-id>/manifest.json
  plans/<plan-id>/plan.sqlite

execution result (append-only journal)
  benchmark-results/bigMoveBench/runs/<run-id>/execution.sqlite
  output objects or compressed output shards
```

Do not add execution state to the compiled catalog. It represents external
evidence and must remain reusable and read-only.

### Generated objects

Use stable wrapper class names. Pair-specific class names prevent reuse but add
no isolation because each case already runs in its own temporary workspace.

Object identity includes the wrapper version, role, and fragment content. The
initial roles are:

- source wrapper containing a fragment
- destination wrapper containing a fragment
- empty source wrapper
- empty destination wrapper

A fragment used by many pairs therefore produces at most one object per
applicable role.

### Execution plan

`plan.sqlite` should contain normalized tables equivalent to:

```text
cases(case_id, ordinal, pair_set, original_source_object_id,
      original_destination_object_id, modified_source_object_id,
      modified_destination_object_id, expected_match_kind,
      expected ranges and payload identities)
case_rows(case_id, catalog_pair_id, source_row_id, direction_disposition)
generated_objects(object_id, role, fragment_sha256, path, size, sha256)
```

Additional selection and functionality metadata should be referenced or stored
once in normalized tables. Do not copy complete selection frames, contributing
rows, or raw fragment text into every case record.

### Serial execution

Start with one worker. For each case it should:

1. read the four required object references from the plan;
2. hard-link or symlink them into a reusable scratch archive with the required
   `source/input.java` and `destination/input.java` paths;
3. run srcDiff and the semantic gate;
4. run srcMove when eligible;
5. commit the attempt and oracle result as a small database transaction;
6. clear and reuse the scratch archive.

The journal, rather than a rewritten whole-run JSON document, is the recovery
source of truth. Summary JSON and CSV are derived artifacts produced by queries.

## Invariants

1. The compiled catalog and fragment store remain unchanged and read-only.
2. Plan identity covers the compiled dataset, selection, wrapper version, object
   inventory, case inventory, direction policy, and oracle configuration.
3. Every object is verified by content hash before publication; published plans
   never refer to mutable source paths.
4. A case preserves the current two-file archive shape and the exact expected
   payload texts and line ranges used by the semantic and scoring oracles.
5. Case identity remains deterministic. Multiple BigCloneBench rows may support
   one case, but one generated input executes only once per declared direction.
6. Attempt identity includes the plan, case, tool artifact, and tool
   configuration. Retrying records a new attempt without overwriting evidence.
7. A committed terminal attempt is idempotent: restart must neither lose it nor
   execute it again unless retry was explicitly requested.
8. Large case collections are streamed or queried in bounded batches; no stage
   loads every case or result into memory.
9. The serial normalized runner must reproduce current small and medium profile
   outcomes before the old expanded path is removed.
10. Parallel execution is not introduced until the serial design passes the
    verification gate below.

## Implementation Steps

1. **Design:** this document establishes ownership, identities, and the migration
   boundary.
2. **Object store:** add stable wrappers, content-addressed generated objects,
   and tests showing storage scales with unique fragments rather than pairs.
3. **Plan database:** publish normalized plans and implement a serial runner using
   a reusable scratch archive. Keep the current workflow available for result
   comparison.
4. **Journal and streaming evaluation:** replace per-case manifest rewrites with
   transactional attempts and query-derived summaries; verify interruption and
   resume behavior.
5. **Stop and verify before parallelism:** compare current and normalized results
   on both frozen profiles, run a larger synthetic scale test, inspect disk and
   memory growth, and exercise forced interruption/restart. Resolve discrepancies
   before proceeding.
6. **Bounded parallelism:** only after the gate passes, add deterministic shards
   and transactional case claiming. Prove that two workers cannot execute the
   same case accidentally.
7. **Output compaction:** preserve reusable srcDiff results in compressed,
   content-addressed objects or deterministic shards rather than millions of XML
   files.
8. **Cutover:** make `suite.py` use the normalized path, bump artifact schemas,
   and remove the expanded snapshot/corpus implementation after equivalence is
   established. Do not silently mix old and new caches.

## Verification Gate Before Parallelism

Parallelism is a deliberate stopping point, not part of the first vertical
slice. Before adding workers, require all of the following:

- identical selected case IDs and oracle outcomes for `PROFILE=small` and
  `PROFILE=medium` compared with the current workflow;
- generated-object count proportional to unique fragments, not selected pairs;
- bounded memory during a 10,000-case synthetic planning/execution test;
- approximately linear journal/checkpoint cost as case count grows;
- successful resume after forced termination during srcDiff, srcMove, and
  evaluation;
- reconciled selected, eligible, executed, failed, and scored counts;
- complete provenance from every result back to its plan, selection, compiled
  dataset, contributing rows, wrapper version, and tool artifacts.

## Next Task

Implement step 2 only: introduce stable wrappers and the content-addressed
generated-object store with focused unit tests. Do not add concurrency, change
the scoring oracle, or remove the current workflow in that task.
