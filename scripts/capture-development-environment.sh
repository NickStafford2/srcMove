#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd -- "$REPO_ROOT/.." && pwd)"
HOST_LABEL="$(hostname -s 2>/dev/null || hostname)"
HOST_LABEL="${HOST_LABEL//[^A-Za-z0-9._-]/-}"
DEFAULT_OUTPUT="$REPO_ROOT/development-environment-reports/${HOST_LABEL}.txt"
OUTPUT_PATH="${1:-$DEFAULT_OUTPUT}"

if [[ "$OUTPUT_PATH" != /* ]]; then
  OUTPUT_PATH="$REPO_ROOT/$OUTPUT_PATH"
fi

mkdir -p "$(dirname -- "$OUTPUT_PATH")"
exec > >(tee "$OUTPUT_PATH") 2>&1

repository_revision() {
  local name="$1"
  local path="$2"

  if git -C "$path" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    printf '%-10s %s\n' "$name" "$(git -C "$path" rev-parse HEAD)"
  else
    printf '%-10s unavailable (%s)\n' "$name" "$path"
  fi
}

command_version() {
  local name="$1"
  shift

  if command -v "$1" >/dev/null 2>&1; then
    printf '%-10s ' "$name"
    "$@" 2>&1 | sed -n '1p'
  else
    printf '%-10s unavailable\n' "$name"
  fi
}

file_digest() {
  local name="$1"
  local path="$2"

  if [[ -f "$path" ]]; then
    printf '%-10s ' "$name"
    sha256sum "$path" | sed "s#  $WORKSPACE_ROOT/#  #"
  else
    printf '%-10s unavailable (%s)\n' "$name" "$path"
  fi
}

run_check() {
  local name="$1"
  shift

  printf '\n=== %s ===\n' "$name"
  "$@"
  local status=$?
  printf '\nexit_status=%d\n' "$status"
  CHECK_FAILURES=$((CHECK_FAILURES + (status != 0)))
}

cd "$REPO_ROOT"

printf 'srcMove development environment comparison\n'
printf 'captured_at_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'host=%s\n' "$HOST_LABEL"
printf 'kernel=%s\n' "$(uname -srmo)"

if [[ -r /etc/os-release ]]; then
  # The file is supplied by the operating system and contains shell assignments.
  . /etc/os-release
  printf 'os=%s %s\n' "${NAME:-unknown}" "${VERSION_ID:-unknown}"
fi

printf '\n=== Source revisions ===\n'
repository_revision srcML "$WORKSPACE_ROOT/srcML"
repository_revision srcReader "$WORKSPACE_ROOT/srcReader"
repository_revision srcDiff "$WORKSPACE_ROOT/srcDiff"
repository_revision srcMove "$REPO_ROOT"
printf '%-10s %s\n' "srcReader" "branch=$(git -C "$WORKSPACE_ROOT/srcReader" branch --show-current 2>/dev/null || printf unavailable)"

printf '\n=== Toolchain ===\n'
command_version python python3 --version
command_version cmake cmake --version
command_version clang clang++ --version

printf '\n=== Executable identities ===\n'
file_digest srcml "$WORKSPACE_ROOT/srcML-install/bin/srcml"
file_digest srcdiff "$WORKSPACE_ROOT/srcDiff/build/bin/srcdiff"
file_digest srcMove "$REPO_ROOT/build/srcMove"

CHECK_FAILURES=0

if [[ -x "$REPO_ROOT/build/srcMove" ]]; then
  run_check "Focused XML regression" \
    python3 tests/regression/xml/run.py \
      --srcmove build/srcMove \
      --case 1x1_basic
else
  printf '\n=== Focused XML regression ===\n'
  printf 'SKIP: build/srcMove is not executable\n'
  CHECK_FAILURES=$((CHECK_FAILURES + 1))
fi

run_check "Focused srcmove_history unit test" \
  python3 -m unittest \
    tests.unit.srcmove_history.test_srcmove_history_worker.PairExecutorTests.test_worker_reuses_one_git_batch_and_runs_tools_in_order

printf '\n=== Summary ===\n'
printf 'focused_check_failures=%d\n' "$CHECK_FAILURES"
printf 'report=%s\n' "$OUTPUT_PATH"

exit "$CHECK_FAILURES"
