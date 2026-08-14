# srcMove Benchmarks

Benchmarks are experiments and are intentionally separate from deterministic
correctness tests in `tests/`.

- [BigCloneBench](bigclonebench/README.md): synthetic Type-1 and Type-2 accuracy
  workloads generated from BigCloneBench clone pairs.
- [Repository benchmarks](repositories/README.md): end-to-end `srcdiff` and
  `srcMove` runs across configured revisions of real repositories.
- `profile.py`: repeatable internal `srcMove --profile` measurements over
  prepared XML inputs.

Generated benchmark data is ignored. Archive thesis-quality results with their
manifest and metadata rather than treating a mutable working directory as the
authoritative result.
