# Converting BigCloneEval Into srcMove Tests

BigCloneEval is not a move-detection benchmark by itself. Its oracle is a set of
clone pairs: two independently existing Java function fragments that implement
the same functionality. To use it for srcMove, synthesize a before/after edit
where one clone fragment is deleted from the old version and its paired clone
fragment is inserted at a different location in the new version.

## Local Assets

After the five BigCloneEval setup steps, this checkout has the two required
inputs:

```text
test/BigCloneEval/bigclonebenchdb/bcb.h2.db
test/BigCloneEval/ijadataset/{default,sample,selected}/*.java
```

The H2 database contains the truth tables:

```sql
FUNCTIONS(NAME, TYPE, STARTLINE, ENDLINE, ID, NORMALIZED_SIZE, PROJECT, TOKENS, INTERNAL)
CLONES(FUNCTION_ID_ONE, FUNCTION_ID_TWO, FUNCTIONALITY_ID, TYPE, SYNTACTIC_TYPE,
       SIMILARITY_LINE, SIMILARITY_TOKEN, MIN_SIZE, MAX_SIZE, MIN_PRETTY_SIZE,
       MAX_PRETTY_SIZE, MIN_JUDGES, MIN_CONFIDENCE, MIN_TOKENS, MAX_TOKENS, INTERNAL)
```

`FUNCTIONS.TYPE` is the IJaDataset subdirectory (`selected`, `default`, or
`sample`), and `FUNCTIONS.NAME` is the Java file name.

## Conversion Model

For each selected clone pair:

1. Join `CLONES` to `FUNCTIONS` twice.
2. Extract `function_id_one` lines from its source file.
3. Extract `function_id_two` lines from its source file.
4. Build a synthetic old file containing fragment one between stable anchor methods.
5. Build a synthetic new file containing the paired fragment in a later stable gap.
6. Run `srcDiff original.java modified.java`.
7. Run `srcMove` over the srcDiff XML.
8. Score whether srcMove reports one delete/insert move whose raw texts match the two
   benchmark fragments.

This converts clone similarity into move similarity. Exact and Type-2 clone pairs
are the best first target for srcMove because they align with the current exact and
Type-2 match categories. Type-3 and Type-4 pairs are useful later as expected misses
or as recall targets for future similarity scoring.

## Recommended Sampling Query

Start with a deterministic exact/Type-2 sample:

```sql
SELECT
  c.function_id_one,
  f1.type AS type1, f1.name AS name1, f1.startline AS startline1, f1.endline AS endline1,
  c.function_id_two,
  f2.type AS type2, f2.name AS name2, f2.startline AS startline2, f2.endline AS endline2,
  c.syntactic_type, c.similarity_line, c.similarity_token, c.min_tokens
FROM clones c
JOIN functions f1 ON f1.id = c.function_id_one
JOIN functions f2 ON f2.id = c.function_id_two
WHERE c.syntactic_type IN (1, 2)
  AND c.min_tokens >= 50
  AND c.internal = FALSE
ORDER BY c.syntactic_type, c.functionality_id, c.function_id_one, c.function_id_two
LIMIT 100;
```

Then broaden by buckets:

```text
syntactic_type = 1             exact / Type-1 move baseline
syntactic_type = 2             renamed / Type-2 move baseline
syntactic_type = 3, sim >= .90 near-miss or future Type-3 recall
syntactic_type = 3, sim < .70  expected miss / stress cases
internal = TRUE/FALSE          intra-project vs inter-project split
```

## Practical Test Layout

Generate into a separate directory so the large suite is not mixed with small
hand-authored e2e fixtures:

```text
test/e2e_bigclonebench/
  cases/
    bcb_t2_000001/
      original.java
      modified.java
      metadata.json
```

`metadata.json` should record BigCloneBench IDs, file locations, line ranges,
similarity fields, and the exact deleted/inserted fragment text. The large-suite
runner can validate by fragment text and counts instead of requiring stable
srcMove UUIDs or absolute xpaths.

## Important Caveats

- BigCloneBench labels clones, not historical edits. The generated suite measures
  whether srcMove can recognize a synthetic move whose payload is drawn from a
  known clone pair.
- Many BigCloneBench fragments depend on imports or surrounding class members.
  srcDiff/srcML parsing generally does not require compilation, but malformed
  extracted fragments should be filtered out.
- Type-3 and Type-4 pairs should not be marked as required positives unless
  srcMove grows a similarity matcher designed for them.
- Keep the generator deterministic. A stable SQL `ORDER BY` makes failures
  reproducible and lets you compare recall across srcMove versions.
