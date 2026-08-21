# BigCloneBench / IJaDataset Notes

## Supported IJaDataset Layouts

The generator supports both IJaDataset layouts distributed for BigCloneBench.
The full corpus uses flat source-kind directories:

```text
ijadataset/{default,sample,selected}/*.java
```

The smaller `IJaDataset_BCEvalVersion.tar.gz` archive uses functionality-specific
directories:

```text
ijadataset/bcb_reduced/<functionality_id>/<source_kind>/<filename>
```

The reduced layout contains the Java files referenced by BigCloneBench without
the millions of unrelated files in the full IJaDataset. The generator uses each
clone row's `functionality_id` to resolve reduced-corpus paths; case selection,
source ranges, and extracted text otherwise remain unchanged. If both layouts
are installed, the flat full-corpus file takes precedence.

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

## BigCloneEval Mental Model

BigCloneEval is an evaluator for clone detection tools, not a source-change
history benchmark. A tool reports clone pairs, BigCloneEval imports those pairs,
then measures recall against BigCloneBench reference clone pairs.

The pieces are:

- IJaDataset source files: the Java corpus. These files contain the code text.
- `functions`: a table of benchmark code fragments inside that corpus. In this
  database, a fragment is a concrete line range inside one Java file, usually a
  method-sized region. It is not a separate file; it is identified by
  `functions.name`, `functions.type`, `functions.startline`, and
  `functions.endline`.
- `clones`: BigCloneBench reference clone-pair rows between two `functions`
  rows.
- `false_positives`: known false-positive clone pairs used when evaluating clone
  detector precision-related output.
- imported tool output: clone pairs reported by the tool being evaluated.
- clone matcher: the matching algorithm that decides whether a reported tool
  clone sufficiently covers a reference clone.

BigCloneEval recall is row-based: a reference row in `clones` is counted as
detected if the tool output contains a clone pair that the configured matcher
accepts. The built-in evaluator checks both pair orders, so `(A, B)` and `(B, A)`
are equivalent for detection.

## Database Shape

The local H2 database uses these relevant columns:

```text
FUNCTIONS(NAME, TYPE, STARTLINE, ENDLINE, ID, NORMALIZED_SIZE, PROJECT, TOKENS,
          INTERNAL)
CLONES(FUNCTION_ID_ONE, FUNCTION_ID_TWO, FUNCTIONALITY_ID, TYPE, SYNTACTIC_TYPE,
       SIMILARITY_LINE, SIMILARITY_TOKEN, MIN_SIZE, MAX_SIZE, MIN_PRETTY_SIZE,
       MAX_PRETTY_SIZE, MIN_JUDGES, MIN_CONFIDENCE, MIN_TOKENS, MAX_TOKENS,
       INTERNAL)
FALSE_POSITIVES(FUNCTION_ID_ONE, FUNCTION_ID_TWO, FUNCTIONALITY_ID, TYPE,
                SIMILARITY_LINE, SIMILARITY_TOKEN, SYNTACTIC_TYPE, MIN_JUDGES,
                MIN_CONFIDENCE)
```

For mapping a reference clone back to source text:

1. Read `clones.function_id_one` and `clones.function_id_two`.
2. Join each ID to `functions.id`.
3. Resolve each fragment as:

```text
benchmarks/bigclonebench/data/BigCloneEval/ijadataset/<functions.type>/<functions.name>
```

4. Extract inclusive `functions.startline` through `functions.endline`.

`functions.type` is the IJaDataset subdirectory (`selected`, `default`, or
`sample`). `functions.project` is the project label used by BigCloneEval's
intra-project/inter-project reporting.

## BigCloneBench Fields That Matter

### `functionality_id`

BigCloneBench's way of grouping clone pairs by the kind of task the code
performs.

Conceptually:

```text
functionality_id = 42: sort an array
functionality_id = 99: read a file
functionality_id = 123: compute edit distance
```

Every row in `clones` is still a pair of concrete code fragments:

```text
function A clone-of function B
function A clone-of function C
function D clone-of function E
```

If several rows share the same `functionality_id`, BigCloneBench is saying they
all implement the same general functionality.

For srcMove reporting:

- row count: how many BigCloneBench pair rows ran. This matches BigCloneEval's
  native recall unit.
- distinct raw text-pair count: how many unique extracted source-text pairs ran.
  This matters because many BigCloneBench rows can contain identical raw source
  text, especially in Type-1.
- functionality coverage: how many different code-task groups were represented.
  This guards against a large run mostly testing one repeated task shape.

### `syntactic_type`

The BigCloneBench clone category. Local srcMove tests currently use Type-1 and
Type-2 only.

### `similarity_line` / `similarity_token`

How much syntax the two fragments share, measured by lines or tokens after
BigCloneBench rewrites source into a normalized comparison form.

The comparison form exists so BigCloneBench can classify clone strength without
being dominated by superficial source differences. BigCloneEval's README
describes this as strict pretty-printing plus Type-1 and Type-2 normalizations.
In practical terms:

- strict pretty-printing gives code a consistent layout before line comparison
- comment and whitespace differences should not decide semantic clone strength
- Type-2 comparison can abstract identifier and literal differences
- shared lines or tokens are then compared with a diff-style ordered match

The local H2 database stores line and token similarity as fractional values such
as `1.0`, `.90`, or `.70`. BigCloneEval's command-line documentation often talks
about the same thresholds as percentages such as 100%, 90%, or 70%.

BigCloneEval can evaluate by:

- line score
- token score
- average of the line and token scores
- `BOTH`, meaning the lower of the line and token scores

These are benchmark clone-strength scores: they describe how strongly the two
BigCloneBench fragments resemble each other after BigCloneBench's normalization.
They are useful for srcMove sampling and future similarity experiments, but they
are not byte-for-byte raw source comparisons. Do not use them directly as the
srcMove `exact` vs `type2` oracle.

### Size Metadata And Judgment Filters

- `min_tokens`: the smaller token count of the two fragments. BigCloneEval's
  recommended settings include `min_tokens >= 50`, but srcMove deliberately
  includes every available fragment size. The value remains useful for size
  strata and diagnostics; it is not an eligibility filter.
- `min_size` / `min_pretty_size`: smaller fragment size in original lines and
  pretty-printed lines. `min_size` counts the original source line span.
  `min_pretty_size` counts the same fragment after BigCloneBench's
  pretty-printing normalization.
- `min_judges` / `min_confidence`: optional human-judgment filters.
  A judge is a human reviewer who inspected whether a fragment implements the
  functionality BigCloneBench assigns to it. Confidence is an agreement score
  used when multiple judges reviewed the same fragment. These fields are mainly
  useful when you want a stricter benchmark slice.

### `internal`

An exclusion flag used by BigCloneEval's default evaluator. Unless
`include_internal` is enabled, BigCloneEval adds `AND internal = FALSE` when it
selects reference clones.

The name is easy to misread. It does not mean "in the same project" and it does
not mean "inside one file." It is a BigCloneBench/BigCloneEval filtering flag
for whether a reference row belongs to the default public evaluation set.

Do not equate `internal = FALSE` with inter-project clones. BigCloneEval handles
project granularity separately by comparing `functions.project`:

```text
inter-project: f1.project != f2.project
intra-project: f1.project == f2.project
```

Thus, `internal = FALSE` is best understood as "use BigCloneEval's default
reference clone set" rather than "use only inter-project examples."

## Similarity And Clone Types

In this document, similarity means BigCloneBench's estimate of how much syntax
two benchmark fragments share after its normalization steps. The fragments are
the inclusive source line ranges extracted from IJaDataset using the
`functions` table.

This is different from raw text equality:

- Two fragments can be raw-text identical and therefore have similarity `1.0`.
- Two fragments can differ only by layout or comments and still be Type-1.
- Two fragments can differ by names or literals and still be Type-2.
- Type-3 and Type-4 rows allow larger syntactic or semantic differences.

This distinction matters for srcMove because the local generator writes the
extracted raw source text into synthetic `original.java` and `modified.java`
files. srcMove then sees the raw source, not BigCloneBench's normalized
comparison form. A BigCloneBench similarity score can tell us which benchmark
bucket a pair belongs to, but srcMove still needs its own exact, Type-2, or
future similarity matching logic to detect the synthetic move.

Type-1 deserves special care for srcMove. BigCloneEval describes Type-1
similarity as allowing formatting/comment differences, so a srcMove test
framework should not dedupe Type-1 cases by a whitespace-insensitive key by
default. Raw extracted text is the safer default dedupe unit; trimmed keys are
useful only as secondary audit metadata.

## Practical Implication For srcMove

BigCloneBench says two independently existing Java fragments are clones. It does
not say one fragment historically moved to the other location. The local srcMove
framework therefore synthesizes a before/after edit: delete one benchmark
fragment from `original.java`, insert the paired fragment in `modified.java`,
then check whether srcMove reports the expected move.

This transformation is useful, but its metrics must be described honestly:

- BigCloneBench row count is not the same as distinct move-test variety.
  BigCloneBench counts clone-pair rows. A single fragment can appear in many
  rows, and several rows can have identical extracted raw text. Running 1,000
  rows therefore does not automatically mean running 1,000 meaningfully
  different srcMove cases.
- Repeated rows from the same functionality or identical source text can inflate
  apparent coverage.
  For example, a high pass rate over many copies of the same sorting method
  mostly proves that one exact pattern works repeatedly. It is still useful, but
  it should be reported separately from coverage over different functionality
  groups and different raw text pairs.
- Type-1 whitespace/comment behavior should be covered by raw-text-aware
  BigCloneBench cases plus focused hand-authored fixtures.
  Most currently selected Type-1 BigCloneBench cases have identical extracted
  raw text on both sides. To test whether srcMove handles Type-1
  formatting/comment changes, use `--text-change raw-different` for the rare
  BigCloneBench rows that actually differ in raw text, and keep small
  checked-in fixtures that deliberately exercise whitespace and comment changes.

See [Converting BigCloneEval Into srcMove Tests](bigclonebench_srcmove_conversion.md)
for the current local generator and runner design.

## Local Installation

Install BigCloneEval manually under:

```text
benchmarks/bigclonebench/data/BigCloneEval/
```

This is the path used by `benchmarks/bigclonebench/generate.py`. The local
checkout should contain BigCloneEval's `ReadMe.md`, `libs/`, the BigCloneBench
H2 database under `bigclonebenchdb/`, and either supported IJaDataset layout
described above.

Follow BigCloneEval's own setup instructions in
`benchmarks/bigclonebench/data/BigCloneEval/ReadMe.md`, or the upstream README at
<https://github.com/jeffsvajlenko/BigCloneEval>. In this repository, the
expected local artifacts are:

```text
benchmarks/bigclonebench/data/BigCloneEval/bigclonebenchdb/bcb.h2.db
benchmarks/bigclonebench/data/BigCloneEval/libs/h2-1.3.176.jar
```

and one of:

```text
benchmarks/bigclonebench/data/BigCloneEval/ijadataset/{default,sample,selected}/*.java
benchmarks/bigclonebench/data/BigCloneEval/ijadataset/bcb_reduced/*/{default,sample,selected}/*.java
```
