# srcMove Tests

The repository `Makefile` is the developer interface. From the repository root:

```bash
make test                         # build, then run every correctness suite
make test-unit                    # Python infrastructure tests only
make test-xml                     # build, then run XML regressions
make test-source                  # build, then run source-pair regressions
```

`tests/run.py` is the underlying test selector and expects an existing build.
Use it directly for case-level selection and inventory:

```bash
python3 tests/run.py --list
python3 tests/run.py --case 1x1_basic
python3 tests/run.py --case 1x1_basic --case blocks_swapped
```

`--case` finds the owning regression suite automatically. Combine it with
`--suite` if the same case name ever exists in both regression suites.

## Suites

- `unit`: Python tests for test and benchmark infrastructure.
- `xml`: checked-in srcDiff XML fixtures run directly through `srcMove`.
- `source`: checked-in source pairs regenerated with `srcdiff`, then run through
  `srcMove`.

Fixture discovery and layout validation are defined once in
`tests/support/cases.py`. XML cases contain `input.xml`, `expected.xml`, and
`expected.json`. Source cases contain `oracle.json` plus either one
`original.*`/`modified.*` file pair or `original/`/`modified/` directories for
archive comparisons. Malformed case directories are errors rather than being
silently ignored.

Generated artifacts never live beside checked-in fixtures. Both regression
suites write to `build/test-results/<suite>/<case>/`, using `srcdiff.xml`,
`srcmove.xml`, and `results.json` where applicable.

The unit suite also exercises benchmark attempts and corpus replay entirely
offline with fake executables. These cases cover termination and XML failures,
timeout process-group cleanup, bounded logs, interrupted-attempt recovery,
content-stable identifiers, checksum enforcement, and replay without source
trees or srcDiff. They also cover non-destructive filters, resumable batches,
retry lineage, resource observations, and srcDiff replay/subset reduction.
Repository-orchestrator fixtures verify that one command reuses immutable
preparations and corpora, appends distinct srcMove runs and series records, and
saves srcDiff failures without starting a misleading srcMove run.
Tiny BigCloneBench fixtures additionally verify semantic eligibility, strict
match-kind enforcement, append-only summaries, reconciled outcomes, and reuse
of one immutable corpus across multiple fake srcMove builds. They do not require
or download BigCloneBench.

Performance-runner fixtures compare fake srcMove builds over checked-in srcDiff
XML. They verify reproducible position-balanced schedules, identical input
checksums, paired summaries, append-only artifacts, and preservation of failed
measurements without running large workloads.

CTest is retired for this project. The Makefile owns building; `tests/run.py`
owns deterministic correctness-test selection and execution.

## Tool Selection

All test and benchmark entry points use `tests/support/tooling.py` for executable
discovery and command execution. Explicit CLI paths take precedence, followed
by `SRCMOVE_BIN` or `SRCDIFF_BIN`, workspace build outputs, and finally `PATH`.
Override either tool when needed:

```bash
python3 tests/run.py --srcmove /path/to/srcMove --srcdiff /path/to/srcdiff
SRCMOVE_BIN=/path/to/srcMove python3 tests/run.py --suite xml
```

## Benchmarks

BigCloneBench and repository-scale workloads are experiments, not correctness
test suites. They have separate runners and are never included implicitly by
`tests/run.py`. See the [benchmark index](../benchmarks/README.md).
