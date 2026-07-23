# BigCloneBench / IJaDataset Notes

## Local IJaDataset Layout

The downloaded dataset under `test/IJaDataset/` is a Java source corpus:

```text
test/IJaDataset/
  dataset/
    sample/     44 Java files, about 184K
    default/    137,062 Java files, about 880M
    selected/   2,739,113 Java files, about 18G
```

Only `.java` files were found locally. No clone-pair metadata, manifests, CSV, XML,
JSON, or database files were present in this copy.

The `sample/` directory uses descriptive filenames such as `BubbleSort.java` and
`BinarySearch.java`. The `default/` and `selected/` directories use numeric
filenames such as `28322.java` and `1425080.java`.

## Where The Truth Data Lives

The source corpus alone is not the BigCloneBench oracle. The BigCloneBench truth
data is distributed separately with BigCloneEval as an H2 database.

Relevant BigCloneEval setup details:

- BigCloneEval repo: <https://github.com/jeffsvajlenko/BigCloneEval>
- The repo contains placeholder directories:
  - `bigclonebenchdb/`
  - `ijadataset/`
- BigCloneEval's README instructs users to download `BigCloneBench_BCEvalVersion.tar.gz`
  and extract it into `BigCloneEval/bigclonebenchdb/`.
- It also instructs users to download `IJaDataset_BCEvalVersion.tar.gz` and extract it
  into `BigCloneEval/ijadataset/`, producing `ijadataset/bcb_reduced/`.
- `bigclonebenchdb/readme` says that directory should contain the BigCloneBenchDB.

The BigCloneEval code opens the benchmark database at:

```text
bigclonebenchdb/bcb
```

using the H2 JDBC URL:

```text
jdbc:h2:<absolute path>/bigclonebenchdb/bcb;IFEXISTS=TRUE
```

So the expected local database artifact is likely one or more H2 files named like
`bcb.*` inside `bigclonebenchdb/`.

## Useful Database Shape

The BigCloneEval source indicates that BigCloneBench truth records are keyed by
functions.

`src/database/Functions.java` queries the `functions` table with:

```sql
SELECT id, name, type, startline, endline, normalized_size
FROM functions
WHERE id = ...
```

The `Function` object fields are:

- `id`
- `name`
- `type`
- `startline`
- `endline`
- `normalized_size`

For mapping back to local files, `type` appears to correspond to the IJaDataset
subdirectory (`selected`, `default`, or `sample`), and `name` is the Java filename.

`src/database/Clone.java` represents clone truth records with:

- `functionality_id`
- `function_id_one`
- `function_id_two`
- `type`
- `syntactic_type`
- `similarity_line`
- `similarity_token`
- `min_size`
- `max_size`
- `min_pretty_size`
- `max_pretty_size`
- `min_judges`
- `min_confidence`

The likely workflow for extracting ground truth is:

1. Open the H2 database from `bigclonebenchdb/bcb`.
2. Query the clone-pair truth table for pairs of function IDs and clone metadata.
3. Join `function_id_one` and `function_id_two` to the `functions` table.
4. Resolve each function to:

```text
dataset/<type>/<name>, startline, endline
```

This should produce the source fragment pairs needed to build a move-detection
benchmark or to synthesize controlled move cases.

## Practical Implication For srcMove

The current local `test/IJaDataset/` checkout is useful as source material, but it
does not contain the oracle. To use BigCloneBench labels directly, download and
inspect the BigCloneEval H2 database. Without that database, the reliable path is
to synthesize moves from the Java corpus and generate known ground-truth oracles.

## Setup Script

Use `scripts/setup_bigclonebench.sh` to create a reproducible local checkout under
`test/bigclonebench/`.

```bash
scripts/setup_bigclonebench.sh
```

The script clones BigCloneEval, downloads the BigCloneBench H2 database archive
and reduced IJaDataset archive, extracts them into the expected BigCloneEval
directories, and exports the H2 database metadata/tables into:

```text
test/bigclonebench/export/
```

If OneDrive requires login and returns an HTML page instead of a tarball, download
the archives manually and rerun with:

```bash
BCB_TARBALL=/path/to/BigCloneBench_BCEvalVersion.tar.gz \
IJA_TARBALL=/path/to/IJaDataset_BCEvalVersion.tar.gz \
scripts/setup_bigclonebench.sh --no-download
```
