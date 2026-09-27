# OpenCV-derived source fixtures

These files are source inputs for the
[historical Type-3 contracts](../README.md#historical-type-3-observation-contracts),
not compilable standalone programs. Tests regenerate srcDiff from the before and
after directory roots, retaining revision-relative filenames.

The [catalog](../type3_history_contracts.json) records original OpenCV commits,
parents, derivations, source hashes, independent source oracles, and separate
observation baselines. Functor fixtures contain two extracted complete structs;
warp fixtures retain the original file context needed to reproduce srcDiff's
exclusive enclosing constructs. Do not simplify them by supplying a fabricated
common container or changing the source oracle to match diagnostics.

The source is derived from OpenCV and retains its original copyright notices
where present. The applicable upstream license is included as
[LICENSE.opencv](LICENSE.opencv).
