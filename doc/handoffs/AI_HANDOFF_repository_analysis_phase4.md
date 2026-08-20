# srcMove Handoff: Repository Analysis Phase 4

## Objective

Continue Phase 4 of the production repository-history analyzer after its focused
Phase 3 execution path passed unit and real-binary verification.

The canonical design and phase definitions remain in
[the repository-history analysis plan](../historical_repository_analysis_plan.md).
Do not restate or redesign that architecture without evidence.

## Start here

Work in `srcMove/` and read:

- `AGENTS.md`
- `doc/historical_repository_analysis_plan.md`
- `repository_analysis/contracts.py`
- `repository_analysis/coordinator.py`
- `repository_analysis/worker.py`
- `repository_analysis/reporting.py`
- `tests/unit/test_repository_analysis_*.py`

Check `git status` before editing. The user owns staging and commits; do not
stage, commit, revert, or overwrite the current changes.

## Current state

The Phase 3 verification and initial Phase 4 reporting slice are committed at:

```text
4bdc1fd Historical Repo Analysis: Phase 3 validation succeeded. phase 4 started.
```

Only this handoff file was uncommitted when written. Commit `4bdc1fd` does the
following:

- add focused terminal-status tests for export and orchestration failures;
- cover srcDiff and srcMove nonzero exit, signal, timeout, spawn failure,
  malformed output, and missing results;
- make process termination evidence take precedence over the secondary
  missing-output validation error in human-readable failure messages;
- begin Phase 4 with deterministic, versioned pair-receipt serialization;
- atomically create ordered receipt files without replacing an existing file;
- derive constant-size status, move, and timing aggregates as the coordinator
  publishes outcomes.

`run_pairs(...)`, the frozen boundary dataclasses, queue and pending-outcome
bounds, and worker-owned Git/process resources were not changed.

## Phase 3 verification evidence

The full Docker unit suite passed after these changes:

```text
126 tests passed
```

The focused repository-analysis suite passed separately with 19 tests.

A five-pair pilot used the existing SQLite checkout at
`benchmarks/repositories/sqlite/work/repo`, selected directory `src`, excluded
`.py`, three workers, and the real binaries:

```text
/workspace/srcDiff/build/bin/srcdiff
/workspace/srcMove/build/srcmove
```

The window was chosen from the existing 300-pair SQLite baseline because it
contains all evidence classes in only five adjacent pairs:

```text
76ad3be617e8abc232ce2b6dcd2f35ac4da99beb
124f449319fdc311a6c3e46ca9b6e16c7a915820
865a8f30720d10bf74d33721c796cabaffab4555
2429af2e0ce2e4c643786f8d2533f79d974e3270
2ca10782d217708c10924cd21683eba414f32e9c
2884421c0545b02e8f051aed83328b964340520f
```

Observed statuses were three `completed`, one `no_analyzable_change`, and one
`srcdiff_failed`. Completed results included two zero-move pairs and one
positive pair with `move_count=1`. The failed pair retained a checksum-verified
458-byte srcDiff artifact with `invalid_structure`; srcDiff exited zero, the
validator reported an empty archive, and srcMove was not started. All other
retained artifact checksums reverified. Five outcomes were published in order;
maximum queued work and unpublished outcomes were both three.

This matches the statuses and normalized move counts recorded for baseline
pairs 33 through 37. No pilot driver or pilot artifacts were left in the
workspace.

## Phase 4 status

`repository_analysis/reporting.py` is only the first Phase 4 slice. It currently
provides:

- `pair_receipt(outcome)` for deterministic receipt values;
- `PairReceiptPublisher` as an ordered `run_pairs(...)` publication callback;
- atomic create-without-replacement publication under `pairs/`;
- constant-size in-memory aggregate state.

It is not yet a complete durable analysis store. In particular:

- worker-owned artifact paths are serialized but artifacts are not yet retained
  into a durable pair-owned location;
- there is no coordinator acknowledgement that permits worker cleanup;
- the aggregate summary is not yet published;
- there is no chronological CSV/browse view;
- interruption checkpoints, receipt verification, and resume are not
  implemented;
- the publisher is not yet wired into a production command.

Do not treat an absolute path in a receipt as durable retention. Do not delete a
worker directory until every artifact required by policy has been admitted into
the analysis-owned store and the coordinator has acknowledged the sealed
outcome.

## Recommended next slice

Implement retention and sealing before resume:

1. Define one explicit retention policy covering positive, zero-move, skipped,
   and failed outcomes, consistent with the canonical plan.
2. Admit required artifacts into a pair-owned durable directory without
   following symlinks or escaping the analysis root.
3. Publish a sealed receipt only after every required retained artifact has a
   verified size and SHA-256.
4. Add an explicit coordinator acknowledgement after publication so the owning
   worker may clean ephemeral inputs safely.
5. Prove with focused tests that failures retain command/termination/log/partial
   output evidence, zero-move results retain `results.json`, and cleanup cannot
   cross the analysis root.
6. Persist the aggregate and chronological summary by deriving them from sealed
   receipts, keeping receipts as the source of truth.

Only after sealing and verification are stable should resume skip completed
pairs. Resume must verify the frozen fingerprint and required artifacts; it
must not introduce a bypass such as `skip_verification=True`.

Before extending the current atomic writer, review whether crash durability
requires directory `fsync` and whether hard-link publication is the desired
portable primitive. Existing receipt files must never be silently replaced.

## Verification commands

From the workspace root:

```bash
./bin/srcml-dev-shell bash -lc \
  'cd /workspace/srcMove && python3 -m unittest discover \
  -s tests/unit -p "test_repository_analysis_*.py"'

./bin/srcml-dev-shell bash -lc \
  'cd /workspace/srcMove && make test-unit'
```

Also run `git diff --check`. Unit tests must remain offline and use fixture
executables or temporary Git repositories. Reuse the five-pair SQLite window
for another real-binary check only when the next slice needs manual artifact
inspection; do not run a large history by default.

## Non-negotiable constraints

- Preserve `run_pairs(...)` as the public coordinator function.
- Preserve immutable worker/coordinator boundary contracts.
- Keep work queues, unpublished outcomes, logs, workers, and expensive tool
  processes bounded independently of history length.
- Keep one worker-private `git cat-file --batch` session and at most one
  srcDiff or srcMove process per worker.
- Workers compute outcomes; the coordinator publishes them.
- Expected pair failures do not stop unrelated work.
- Zero moves are a successful measurement, never a substitute for missing data.
- Do not copy the generic benchmark corpus/run hierarchy into the production
  path.
- Do not stage or commit; the user handles Git publication.
