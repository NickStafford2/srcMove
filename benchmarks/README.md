# srcMove Benchmarks

Benchmarks are experiments and are intentionally separate from deterministic
correctness tests in `tests/`.

- [BigCloneBench](bigclonebench/README.md): synthetic positive-case Type-1 and
  Type-2 detection workloads generated from BigCloneBench clone pairs.
- [Repository benchmarks](repositories/README.md): end-to-end `srcdiff` and
  `srcMove` runs across configured revisions of real repositories.
- `profile.py`: repeatable internal `srcMove --profile` measurements over
  prepared XML inputs.

Generated benchmark data is ignored. Archive thesis-quality results with their
manifest and metadata rather than treating a mutable working directory as the
authoritative result.

The planned upgrade to separate prepared srcDiff corpora, provenance, failure
incidents, and publication runs is described in the
[benchmarking upgrade plan](../doc/benchmarking_upgrade_plan.md).

## Upgrade contracts

`contracts.py` is the versioned shared boundary for the upgrade. It defines the
canonical content-identity encoding, process/XML/provenance status vocabulary,
development/publication labels, and the narrow interface implemented by dataset
adapters. Dataset adapters may prepare inputs and add semantic eligibility
checks; they must not replace shared execution, provenance, storage, or
reporting.

Phase 0 characterization is entirely offline. Tiny source and srcDiff fixtures,
a configurable fake executable, and strict BigCloneBench oracle tests live under
`tests/`. BigCloneBench remains an external manual prerequisite and normal tests
must neither download it nor depend on historical large-run counts.

The legacy interfaces remain unchanged at this checkpoint:

- `benchmarks/bigclonebench/run.py` generates and evaluates cases together,
  writing ignored cases and a replaceable `cases/summary.csv`.
- `benchmarks/repositories/run_case.py` exports revisions and runs both tools,
  writing ignored artifacts below each case's `work/` directory.
- `benchmarks/profile.py` reads existing XML inputs and writes ignored local
  profiles unless an explicit output is selected.

Previously archived thesis results are historical evidence, not regression
expectations for the refactored implementation.
