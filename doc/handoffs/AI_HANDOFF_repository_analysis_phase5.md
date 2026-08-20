# srcMove Handoff: Repository Analysis Phase 5 Prerequisites

## Objective

Add the frozen invocation inputs needed before exposing the production
repository-history analyzer through a CLI. Phase 4 retention, reporting, and
verified resume are complete.

The canonical architecture remains
[the repository-history analysis plan](../historical_repository_analysis_plan.md).
Do not copy the experimental runner into the production package or migrate the
benchmark CLI in this slice.

## Start here

Work in `srcMove/` and read:

- `AGENTS.md`
- `doc/historical_repository_analysis_plan.md`, especially “History and pair
  definition,” “Resume and cache safety,” and Phase 5
- `repository_analysis/contracts.py`
- `repository_analysis/git.py`
- `repository_analysis/resume.py`
- `tests/unit/test_repository_analysis_*.py`
- the first-parent selection tests in `tests/unit/test_repository_history.py`

Check `git status` before editing. The user normally owns staging, commits, and
review; do not overwrite unrelated changes.

## Committed state

The latest production-analyzer commits are:

```text
4c7589f Historical Repo Analysis: Harden verified resume
dd4784c Historical Repo Analysis: phase 4 done
b133edf Historical Repo Analysis: Derive reports from sealed receipts
c51422f Historical Repo Analysis: Seal retained artifacts and acknowledge cleanup
```

Verified resume now:

- verifies only the contiguous sealed receipt prefix against frozen requested
  sequence, native Git commit IDs, and pair fingerprint;
- verifies retention-policy completeness plus every retained file's relative
  path, regular-file type, size, and SHA-256 without following path-component
  symlinks;
- accepts successful zero-move results and legitimate empty failure captures;
- rejects receipt, policy, capture-accounting, artifact, and fingerprint drift;
- executes and acknowledges only the unverified suffix;
- starts no worker sessions when all requested pairs are already verified;
- preserves interrupted pre-receipt pair storage under `unsealed-pairs/` before
  retry rather than admitting or deleting it;
- rebuilds `summary.json` and `summary.csv` from the final sealed receipts.

The public publisher has no caller-supplied resume offset or verification
bypass. The resume service alone positions its coordinator and publisher after
successful prefix verification.

## Verification evidence

After `4c7589f`:

```text
44 focused repository-analysis tests passed
151 full unit tests passed
git diff --check passed
```

The focused run promoted `ResourceWarning` to an error. Two independent
read-only reviews rechecked integrity and coordinator boundaries after fixes.
No new real-history pilot was needed because this slice changed orchestration
and artifact verification rather than Git or tool execution behavior.

## Next bounded slice

The production package currently accepts caller-injected fingerprint strings.
It cannot yet create the identity that resume promises to verify. Add that
producer before argument parsing or benchmark migration.

Implement and test:

1. A versioned frozen analysis configuration containing the selected directory,
   suffix filtering, archive/position/encoding options, and tool timeouts.
2. One-time srcDiff and srcMove executable observations using SHA-256, file
   size, and the resolved executable identity needed for diagnostics.
3. A versioned canonical pair-fingerprint encoding whose SHA-256 covers:
   repository identity; native old/new Git object-ID strings; the frozen
   configuration; both executable SHA-256 values; and relevant result,
   validator, and receipt schema versions.
4. A focused builder that creates contiguous frozen `PairWorkItem` values from
   an already resolved first-parent commit list without resolving a moving
   branch again.
5. Unit tests proving determinism, field sensitivity, native Git object-ID
   preservation, executable/configuration drift, and independence from worker
   count and dictionary ordering.

Use canonical JSON or another explicitly versioned unambiguous byte encoding.
Hash the exact canonical bytes once with SHA-256. Do not use SHA-1 for
analysis-owned identity and do not rehash Git commit IDs individually.

Repository identity and the durable frozen-history/configuration manifest need
a deliberate definition. Resolve those boundaries in this slice rather than
hiding mutable repository state behind a CLI.

## Not yet

Do not add the production CLI, installed wrapper, benchmark migration, cache
hierarchy, or experimental-runner removal yet. Those follow after the
production invocation can create and persist the exact frozen inputs that
verified resume consumes.

Receipts also do not yet freeze commit timestamp, subject, parent list, or merge
metadata. `summary.csv` therefore remains an ancestry-sequence view and must not
query mutable Git state to fill those columns.

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
repositories. Stop after the frozen-input and fingerprint producer is complete;
review it before beginning the CLI.
