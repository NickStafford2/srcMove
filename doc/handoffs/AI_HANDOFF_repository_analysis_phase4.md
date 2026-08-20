# srcMove Handoff: Repository Analysis Phase 4 Resume

## Objective

Implement only the verified-resume subphase of the production
repository-history analyzer. Retention, sealing, coordinator cleanup
acknowledgement, and receipt-derived reporting are complete and committed.

The canonical architecture remains in
[the repository-history analysis plan](../historical_repository_analysis_plan.md).
Do not redesign it or begin Phase 5 CLI/benchmark migration in this slice.

## Start here

Work in `srcMove/` and read, in order:

- `AGENTS.md`
- `doc/historical_repository_analysis_plan.md`, especially “Resume and cache
  safety” and the Phase 4 verification requirements
- `repository_analysis/contracts.py`
- `repository_analysis/coordinator.py`
- `repository_analysis/worker.py`
- `repository_analysis/retention.py`
- `repository_analysis/reporting.py`
- `tests/unit/test_repository_analysis_*.py`

Check `git status` before editing. The user owns staging, commits, and review;
do not stage, commit, revert, or overwrite their changes.

## Committed state

The relevant commits are:

```text
b133edf Historical Repo Analysis: Derive reports from sealed receipts
c51422f Historical Repo Analysis: Seal retained artifacts and acknowledge cleanup
4bdc1fd Historical Repo Analysis: Phase 3 validation succeeded. phase 4 started.
```

Commit `c51422f` adds:

- an explicit policy retaining successful `results.json`, optional positive
  XML, and failed command/log/partial-output evidence;
- checksum-verified admission into analysis-owned pair directories;
- schema-v2 sealed pair receipts with analysis-root-relative artifact paths;
- create-without-replacement receipt publication with file and directory
  `fsync`;
- coordinator acknowledgement only after successful publication;
- worker cleanup that does not follow symlinks or cross the analysis root.

Commit `b133edf` adds:

- constant-memory aggregate derivation from sealed receipts rather than
  in-memory publisher state;
- replaceable `summary.json` and chronological `summary.csv` views;
- contiguous filename/sequence, schema, seal, status, metrics, and timing
  validation while loading receipts;
- CSV-first and JSON-last atomic replacement, with the CSV checksum recorded in
  `summary.json` so a two-file crash mismatch is detectable;
- completed-outcome invariants requiring exactly one retained valid
  `results.json` and all four normalized move-count metrics;
- retry safety when a malformed completed outcome is rejected before durable
  pair storage is allocated.

`summary.csv` is currently the initial human browse view. Receipts do not yet
contain frozen commit timestamp, subject, or merge metadata, so the CSV honestly
uses ancestry sequence order and does not query mutable Git state.

## Verification evidence

After `b133edf`:

```text
32 focused repository-analysis tests passed
139 full unit tests passed
git diff --check passed
```

The focused run promoted `ResourceWarning` to an error. Tests cover sealed
result requirements, missing-measurement rejection, deterministic report
rebuilds, formula-safe CSV fields, receipt gaps, unsealed receipts, derived-file
publication failures, crash mismatch detection, and retry after rejected seal
input.

The earlier five-pair SQLite real-binary pilot remains documented in Git history
and in the previous version of this handoff. Do not run a large history by
default. A new five-pair pilot is appropriate only if resume needs manual
artifact inspection after unit verification.

## Checksum decision: SHA-256, not SHA-1

Use SHA-256 for every content-integrity or cache-identity decision owned by this
tool:

- retained artifact verification;
- executable observations;
- canonical configuration and pair fingerprints when their producer is added;
- report or receipt-set digests;
- any future cache entry identity.

Do not add SHA-1 as a second checksum and do not downgrade existing SHA-256
fields. SHA-1 provides no compatibility benefit for analysis-owned artifacts
and is weaker for collision resistance.

Git commit and blob object IDs are different: preserve the repository’s native
Git object IDs exactly as returned by Git. Existing repositories commonly use
40-hex SHA-1 object IDs, while Git can also use SHA-256 object format. Do not
rehash commit IDs, label a Git object ID as an artifact checksum, or assume all
future object IDs are 40 characters. A pair fingerprint should include the
native old/new commit ID strings but itself be a versioned SHA-256 digest of the
canonical frozen inputs.

## Next subphase: verified resume

Design the resume boundary before editing. A read-only child-agent review is
recommended because this is the highest-risk Phase 4 slice.

Resume must:

1. Load only the contiguous sealed receipt prefix in sequence order.
2. Match each receipt’s sequence, old/new commits, and pair fingerprint against
   the frozen requested work item.
3. Reverify every policy-required retained artifact using its analysis-root-
   relative path, expected size, and SHA-256.
4. Reject absolute paths, `..` traversal, symlinks, missing files, unexpected
   file types, size drift, checksum drift, schema drift, and fingerprint drift.
5. Treat a successful zero-move result as a verified completed measurement, not
   as missing data or a skip.
6. Skip execution only for fully verified terminal receipts.
7. Continue at the first unverified sequence without rerunning the verified
   prefix or replacing any existing receipt.
8. Leave unsealed worker directories as diagnostic evidence; never admit them
   as cache entries.
9. Rebuild aggregate JSON and chronological CSV from the final sealed receipts.
10. Provide no bypass such as `skip_verification=True`.

Expected interruption coverage includes:

- interruption before sealing;
- interruption after sealing but before derived-report publication;
- receipt present with a missing or modified retained artifact;
- fingerprint/configuration/executable drift;
- resume with zero, some, and all pairs already verified;
- proof that verified pairs do not invoke srcDiff or srcMove again;
- identical normalized outcomes across worker counts and resumed/non-resumed
  execution.

## Coordinator and publisher design constraints

- Preserve `run_pairs(...)` as the public coordinator function.
- Preserve the frozen worker/coordinator boundary dataclasses unless evidence
  requires a deliberate schema migration.
- Current `run_pairs(...)` assumes sequences start at zero, and
  `PairReceiptPublisher` initializes its next sequence to zero. Resume needs an
  explicit, verified starting boundary rather than renumbering work items or
  weakening the contiguous-order checks.
- Do not let an existing filename alone cause a skip. The receipt, fingerprint,
  and every required artifact must verify first.
- Keep work queues, unpublished outcomes, logs, workers, and expensive tool
  processes bounded independently of history length.
- Workers compute outcomes; the coordinator publishes them.
- Existing receipts are immutable and must never be silently replaced.
- Derived `summary.json` and `summary.csv` are replaceable views and remain
  rebuildable from receipts.
- Resume is not optional cache publication. Do not introduce cache hierarchy or
  generic benchmark corpus/run layers.

Prefer a small explicit resume plan such as a verifier that returns a typed
verified prefix plus a coordinator/publisher starting sequence. Do not make
`PairReceiptPublisher` trust or infer an offset merely because files exist.

## Verification commands

From the workspace root:

```bash
./bin/srcml-dev-shell bash -lc \
  'cd /workspace/srcMove && python3 -W error::ResourceWarning \
  -m unittest discover -s tests/unit -p "test_repository_analysis_*.py"'

./bin/srcml-dev-shell make --no-print-directory -C srcMove test-unit

git -C srcMove diff --check
```

Unit tests must remain offline and use fixture executables or temporary Git
repositories. Stop after verified resume is implemented and tested. The user
will review and commit before Phase 5 begins.
