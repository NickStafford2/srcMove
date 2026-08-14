# Repository Benchmarks

These benchmarks compare two configured revisions of a real repository, run
`srcdiff`, then run `srcMove`. Each case directory contains an `info.json`; its
generated checkout, exports, XML, results, and timing report live under the
ignored `work/` directory.

Run one case from the repository root:

```bash
python3 benchmarks/repositories/run_case.py notepadpp
```

Override revisions or refresh the cached checkout when needed:

```bash
python3 benchmarks/repositories/run_case.py notepadpp \
  --old-rev OLD \
  --new-rev NEW \
  --refresh-repo
```

`run.py` executes the small configured batch. `build_examples.py` turns selected
benchmark results into ignored example artifacts for documentation or manual
inspection.
