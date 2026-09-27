# Move-selection semantic benchmark

This suite measures the parent/child, nesting, `diff:common`, ambiguity, and
cross-Type decisions that the redesign is intended to improve. It complements
rather than replaces BigMoveBench and the performance runner:

- this suite asks whether a build chose the intended *explanation* of a move;
- BigMoveBench measures detection and Type-1/2/3 classification over a larger
  clone-derived population;
- `performance/` measures time, memory, and internal work over fixed inputs.

Every catalog case declares a `status`: an accepted `contract` or an
exploratory `hypothesis`. Normal benchmark runs record every semantic miss as
an observation so variants can be compared. The deterministic test suite runs
contracts with `--contracts-only --enforce-contracts`, making a contract miss a
test failure. Tool crashes, timeouts, malformed output, and invalid XML are
always hard failures.

The current catalog contains accepted contracts; the `hypothesis` status is
available for future questions that have not yet earned regression status.
This benchmark's status is independent of BigMoveBench's observational Type-3
population recall.

The separate `shadow_contracts.json` catalog is the reviewer-owned oracle for
the correspondence-classifier milestone. It does not describe current
production output and is not evaluated against the current `moves` array.
Instead, each entry records four independent parts:

- the required srcDiff delete/insert precondition and Type-1 cardinality;
- the structural context observations the future extractor must produce;
- the expected observation-only classification; and
- its stable machine-readable reason.

The move-selection unit suite validates the catalog schema and verifies the
declared srcDiff endpoint counts. Most inputs are small checked-in srcDiff XML
fixtures. The `nodiscard_signature_and_unwrap` case is regenerated from its
checked-in source pair so an upstream srcDiff alignment change cannot let the
contract pass without exposing the exact return as both deleted and inserted.
Raw path incompatibility without a reliable wrapper interpretation remains
`ambiguous`; paths alone never establish relocation or restructuring.

## Retained Notepad++ shadow evaluation

The retained evaluation uses Notepad++ commit
`e59774add26b0130d38aaf722aceb0259ccc0078` and parent
`bf9f8b4c9549dadd23f483190dd1e1e4707da3ea`, limited to
`scintilla/src/Document.h`. The ignored evidence directory is
`benchmark-results/correspondence-baseline-notepadpp/`. Its `before.tar` and
`after.tar` snapshots have SHA-256 values
`8e1523139afd8c16f981abe130920853dd43a5e77a7d38e0809d4387742a47d0`
and `27e5eb5de83440dc10e74e743c646e1f0f538627f8ab3cdc02b51e3bb1b16049`.
The contained files exactly match the corresponding Git objects, with hashes
`6f7661ebeb0b85588961b6c3518f65560ab67725d37b9b3e36b4c71ac7389e01`
and `517d37ed54f5bca008afe2e0c9eb78d0d7aecc6b30f4305e7f0cb24ab8eba22c`.

Regenerate srcDiff from the two extracted directory roots rather than using a
direct file comparison. The directory comparison records the shared logical
child filename `scintilla/src/Document.h`; a direct comparison embeds distinct
temporary `before` and `after` prefixes in `unit@filename`, which would
incorrectly appear to the classifier as positive cross-file evidence. The
retained normalized srcDiff is `shadow-srcdiff.xml`, SHA-256
`2c1221226aef346a7a4511d3725f836a6ea8ebfbe8da0ca1ca1f2a2c2129632e`.

At srcMove commit `5c634c88691ecb9d6c846d02c83f189a0ba9a4d9`, the normalized comparison
produces 12 current move groups, all Type-1, matching the retained baseline
count. The evaluated release build has artifact SHA-256
`de59e645da199d3ff912677cb073f0bcb23c053f8be13f1f1a8a05cb228b0be5`
and build receipt
`build-receipt-sha256-0f2da449b93686ca0a3f52f89aeec81b706143672d6e07f277a6cbf7c1ed257e`
(Clang 18.1.3, C++17, srcReader
`b4b2a88fca88e5dae40fd181f2666961e3ce01dc`). The srcDiff regeneration used
srcdiff 0.1.0 at commit `f48b8180e0c2e9d07e098553d96ed3895676bfdc`.
Diagnostics contain 17 unique Type-1 correspondences: 12 selected by
current move detection and five rejected by current selection. All 17 shadow
classifications are `ambiguous/insufficient_context` because srcDiff serializes
their enclosing constructs exclusively and exposes no reliable mapped semantic
container. Therefore the measured current-versus-shadow disagreement is 12
`move` versus `ambiguous` records; the five unselected records remain
non-relocation observations. This evaluation does **not** establish that those
12 are stationary or restructured. The small reviewed contracts provide that
interpretive evidence; the real comparison demonstrates the conservative
fallback when srcDiff lacks sufficient common structure.

Run the current build:

```bash
python3 moveSelectionBench/benchmark.py \
  --variant current=build/srcMove \
  --run-id current-characterization
```

Compare a redesign with a baseline:

```bash
python3 moveSelectionBench/benchmark.py \
  --variant baseline=/path/to/baseline/srcMove \
  --variant candidate=/path/to/candidate/srcMove \
  --baseline baseline \
  --run-id parent-aware-selection
```

The append-only run directory contains a provenance manifest, sealed attempt
records and logs, per-case semantic outcomes, profiler metrics, a summary, and
baseline-to-candidate transition counts. Do not report only a pass total: review
the individual rationale and forbidden interpretations for changed cases.

## Adding cases

Add one isolated srcDiff XML input under `cases/` and one catalog entry. A
required expectation says that a move pair should exist. A forbidden
expectation says that an interpretation should not be selected. Raw text is
compared after whitespace normalization; match kinds remain explicit.

Archive fixtures declare `"input_shape": "archive"`; single-file fixtures may
omit the field. Set `"verify_results_only_equivalence": true` when a case must
also confirm that normal and `--results-only` executions select identical move
endpoints and match kinds.

Cases with no required moves are useful negative controls. Keep uncertain
examples as `hypothesis` cases. Change the status to `contract` only after the
expected behavior has been reviewed and accepted; contracts run under
`make test`.

Shadow-classifier contracts belong in `shadow_contracts.json` rather than the
production move catalog until observation-only diagnostics exist. Add a
single-purpose input under `shadow_cases/`, declare the exact srcDiff
precondition, fill every context dimension, and select a classification reason
from the stable vocabulary enforced by `shadow_contracts.py`. A source-level
alignment regression should use an `original`/`modified` pair and be generated
by the test instead of checking in a large real-world srcDiff artifact.
