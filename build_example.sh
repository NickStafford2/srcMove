#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./build_example.sh <keyword> [--position]

Description:
  Runs the opencv stress-test case using the revisions configured in
  test/stress/opencv/info.json, then copies the generated srcDiff and srcMove
  XML outputs into examples/ using the requested keyword.

Examples:
  ./build_example.sh baseline
  ./build_example.sh baseline --position
EOF
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$script_dir"
stress_runner="$repo_root/test/stress/diff_and_move_repo.py"
stress_case="opencv"
stress_work_dir="$repo_root/test/stress/$stress_case/work"
examples_dir="$repo_root/examples"

keyword=""
use_position=0

while (($# > 0)); do
  case "$1" in
    --position)
      use_position=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "error: unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      if [[ -n "$keyword" ]]; then
        echo "error: expected exactly one keyword argument" >&2
        usage >&2
        exit 1
      fi
      keyword="$1"
      shift
      ;;
  esac
done

if [[ -z "$keyword" ]]; then
  echo "error: missing keyword" >&2
  usage >&2
  exit 1
fi

if [[ ! "$keyword" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "error: keyword may only contain letters, numbers, dot, underscore, and hyphen" >&2
  exit 1
fi

if [[ ! -f "$stress_runner" ]]; then
  echo "error: stress runner not found: $stress_runner" >&2
  exit 1
fi

runner_cmd=(python3 "$stress_runner" "$stress_case")
if ((use_position)); then
  runner_cmd+=(--position)
fi

echo "Running stress case: $stress_case"
"${runner_cmd[@]}"

src_diff="$stress_work_dir/diff.xml"
src_move="$stress_work_dir/diff_new.xml"

if [[ ! -f "$src_diff" ]]; then
  echo "error: expected generated diff file not found: $src_diff" >&2
  exit 1
fi

if [[ ! -f "$src_move" ]]; then
  echo "error: expected generated move diff file not found: $src_move" >&2
  exit 1
fi

mkdir -p "$examples_dir"

name_prefix="$stress_case.$keyword"
if ((use_position)); then
  name_prefix="$name_prefix.position"
fi

dest_diff="$examples_dir/$name_prefix.diff.xml"
dest_move="$examples_dir/$name_prefix.move.diff.xml"

cp "$src_diff" "$dest_diff"
cp "$src_move" "$dest_move"

echo
echo "Saved example files:"
echo "  $dest_diff"
echo "  $dest_move"
