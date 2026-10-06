# srcMove correctness tests

`make test` builds srcMove and runs every correctness test. In the macOS
workspace, run it inside Docker through `./bin/srcml-dev-shell make -C srcMove test`
from the workspace root, or use the workspace's `make test`. The
[build guide](../README.md) owns dependency and build instructions.

`tests/run.py` expects an existing build. It inventories and selects individual
Python methods, accepted fixtures, and C++ component contracts:

```bash
python3 tests/run.py --list
python3 tests/run.py --suite behavior
python3 tests/run.py --test 'fixtures.xml.*' --test 'fixtures.source.blocks_swapped'
python3 tests/run.py --test '*CorrespondenceInteractionTests*' --list
python3 tests/run.py --test 'components.canonical_forms'
python3 tests/run.py --suite tooling --report build/tooling-report.json \
  --artifacts build/tooling-artifacts
```

Run these commands in Docker when using the workspace. Repeat `--suite` to
combine suites and `--test` to select a union of full IDs or shell globs. Quote
globs so the shell does not expand them. Each selector must match at least one
ID in the selected suites. `--list` needs no executable and can write a JSON
inventory with `--report`.

## Boundaries

| Location | Responsibility |
| --- | --- |
| `unit/` | Isolated Python helpers and C++ component contracts. |
| `behavior/` | Detector correspondence, location, classification, representation, annotations, sequences, and CLI contracts. |
| `tooling/` | History analysis, benchmark infrastructure, and test infrastructure. |
| `fixtures/` | Accepted XML/source inputs, reviewer-owned catalogs, expectations, and source-review rationale. |
| `support/` | Execution, input construction, fixture discovery, structural validation, and explicit oracle functions. |

The behavior suite includes dynamically generated fixture and selection-catalog
tests, each with its own ID. It covers normal, diagnostic, and results-only
output where the owning test requests those modes. Pure helper, component, and
tooling tests remain separate. Discovery rejects duplicate IDs and import
errors. The active `canonical_forms_test` remains a unit component; the obsolete
canonical-subtree workflow and inactive legacy tests are retired.

Large BigCloneBench populations, repository studies, and performance measurements
are separate [experiments](../benchmarking/README.md). Their small offline
infrastructure tests belong to `tooling`; running correctness never starts a
population experiment.

## Accepted fixtures and oracles

[Fixture discovery](support/cases.py) rejects malformed layouts instead of
silently dropping cases. [Fixture tests](support/fixture_tests.py) execute these
representations:

- `fixtures/xml/cases/<case>/`: `input.xml`, `expected.json`, and exact annotated
  `expected.xml`. Tests apply the JSON oracle and preserve the XML serialization
  snapshot.
- `fixtures/source/<case>/`: `oracle.json` and either one
  `original.*`/`modified.*` pair or `original/`/`modified/` archive directories.
  srcDiff regenerates inputs. Single-file sides use the same logical relative
  filename `source.<ext>` beneath separate revision roots, preventing fixture
  labels from becoming rename evidence. Normal and results-only ordinary JSON
  must agree.
- `fixtures/policy/`: isolated reviewer-owned transfer and archive catalogs.
  Negative cases require zero moves; positive cases require exactly one move
  with the declared endpoint text and content relationship. Entries retain
  language, scenario, and rationale. Unrelated catalog examples never share one
  comparison archive.
- `fixtures/selection/`: accepted selection and classifier catalogs plus their
  XML/source inputs. [Selection-catalog assertions](support/selection_catalog.py)
  retain required and forbidden interpretations; classifier tests retain
  independent srcDiff admission, context, classification, and production-policy
  expectations.

XML, policy, and selection-catalog executions explicitly use `statement`
granularity. Source fixtures use `fragment`. Python behavior tests declare their
own granularity and requested modes; low-level normalization and historical
source checks sometimes require fragments. These differences are part of the
case contract, not interchangeable benchmark settings.

[JSON validation](support/validation.py) compares `(XPath, raw text)` endpoint
records together and preserves occurrence multiplicity. Schema/conservation
validation has the neutral owner [`benchmarking/results.py`](../benchmarking/results.py).
Sequence tests additionally compare annotation side, text, partner links, and
occurrence counts with atomic results. Annotation ID sets alone are insufficient;
the annotation helper does not resolve every annotated node's own XPath, so
same-text occurrences still need independent location expectations.

The interaction contracts explicitly resolve selected origin/destination nodes
for balanced two-origin/two-added-copy groups, adjacent distinct copy groups,
and a repeated-text reorder with a stationary occurrence. They require exactly
those nodes to carry atomic annotations, excluding continuing destinations and
stationary equal-text occurrences. Source archive contracts also cover identical
basenames in different subdirectories and retain the full revision-relative
filename in each admitted correspondence and selected endpoint.

Keep source expectations and reviewer policy independent of current detector
output. A missed positive remains a failing assertion. Changing or removing a
behavior expectation requires review of its rationale; do not regenerate goldens
from a failing executable. Hypotheses and population Type-3 recall remain
observations outside accepted correctness fixtures. A Type-3 fixture is still a
hard contract for its declared example.

The restructuring baseline reproduced three ordinary failures: the padded
reorder inside a paired replaced loop, the unchanged try/catch crossing, and the
edited control-header/body reorder. Their independent expectations remain
visible in `behavior/test_correspondence_interactions.py` and
`behavior/test_source_correspondence_variants.py`. The coarse hand-authored loop
encoding and its passing source-generated counterpart both remain covered.

## Outcomes, artifacts, and tool identities

`--report` writes inventory, per-method/fixture/component outcomes, status counts,
tool identities, component build directory, and unexecuted IDs. It defaults to
`ARTIFACTS/report.json`. Subtest failures remain in their parent method's details;
a method total is neither a count of independent scenarios nor an accuracy
measurement. Setup errors and unexecuted required tests stay visible. Failures,
errors, skips, and unexecuted tests make correctness exit nonzero.

`--artifacts` defaults to ignored `build/test-results`. Shared execution retains
inputs, commands, stdout/stderr, JSON/XML, and executable identities. Fixture
invocations use unique directories so later runs preserve earlier evidence.
Tool execution and malformed output errors are distinct from semantic assertion
failures. Inspect the paths named in failure details and the JSON report.

Executable discovery uses [`benchmarking/tooling.py`](../benchmarking/tooling.py):
explicit `--srcmove`/`--srcdiff`, then `SRCMOVE_BIN`/`SRCDIFF_BIN`, workspace build
outputs, then `PATH`. Missing required tools are errors. C++ components use
`build/` or `--component-build-dir`; their build identity is independent of an
alternate detector executable.

[moveSelectionBench](../moveSelectionBench/README.md) invokes this same behavior
suite for every named detector build. It shares fixtures, unittest callbacks,
preconditions, and oracles rather than maintaining a weaker benchmark copy.

## Restructure coverage accounting

The fresh baseline at `4b5256b` executed 542 Python method instances but only
518 unique methods. Module imports caused 11 repeated history methods and 13
repeated BigMoveBench methods; both imports were corrected, and discovery now
rejects duplicates. Fixture inputs and independent expectations were relocated
without regeneration.

The revised complete Docker run on 2026-10-06 executed 687 unique entries: 520
Python methods, 140 XML/source/policy fixtures, 21 selection catalog fixtures,
and six component checks. Of these, 684 passed and the three detector failures
listed above remained visible. The old runner and comparison modules contained
15 methods; their replacement has 17, including four preserved catalog-oracle
contracts and updated inventory, selection, provenance, execution-error, and
comparison contracts. Counts describe this bounded suite, not population accuracy.

Deliberate retirements are the three separate fixture CLIs, overlapping suite
selectors, duplicate execution, inactive `tests/legacy` examples, and the unused
generated canonical-subtree workflow. The production `canonical_forms_test` and
all other active component checks remain covered. No detector behavior
expectation was removed or weakened. Original completed research observations
remain in the benchmark research directories.
