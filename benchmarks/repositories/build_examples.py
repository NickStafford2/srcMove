#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
TESTS_ROOT = REPO_ROOT / "tests"
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from support.tooling import run_command

DEFAULT_CONFIG = SCRIPT_DIR / "example_builds.json"
RUNNER = SCRIPT_DIR / "run_case.py"


@dataclass(frozen=True)
class ExampleSpec:
    case: str
    name: str
    old_rev: str
    new_rev: str
    position: bool
    directory: str | None


@dataclass(frozen=True)
class BuiltExample:
    case: str
    name: str
    old_rev: str
    new_rev: str
    old_commit: str
    new_commit: str
    position: bool
    directory: str | None
    srcdiff_file: str
    srcmove_file: str
    report_file: str
    srcdiff_seconds: float | None
    srcmove_seconds: float | None
    move_count: int | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build configured srcdiff/srcMove example files."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"Path to example config JSON. Default: {DEFAULT_CONFIG}",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate examples even when output files already exist.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be built without running srcdiff/srcMove.",
    )
    parser.add_argument(
        "--only",
        default=None,
        help=(
            "Build only one example, using '<case>:<name>' or just '<name>' if unique."
        ),
    )
    parser.add_argument(
        "--refresh-repo",
        action="store_true",
        help="Pass --refresh-repo through to run_case.py.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise RuntimeError(f"expected JSON object in {path}")

    return data


def require_str(value: Any, field: str, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"missing or invalid '{field}' in {context}")

    return value.strip()


def require_bool(value: Any, field: str, context: str) -> bool:
    if not isinstance(value, bool):
        raise RuntimeError(f"missing or invalid '{field}' in {context}")

    return value


def normalize_directory(value: Any, field: str, context: str) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise RuntimeError(f"missing or invalid '{field}' in {context}")

    directory = value.strip()
    if not directory:
        return None

    directory = directory.replace("\\", "/").strip("/")

    if directory in (".", "./"):
        return None

    if directory.startswith("../") or "/../" in directory or directory == "..":
        raise RuntimeError(f"invalid '{field}' in {context}: must stay within the repo")

    return directory


def validate_example_name(name: str) -> None:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    bad_chars = sorted(set(name) - allowed)

    if bad_chars:
        chars = "".join(bad_chars)
        raise RuntimeError(
            f"invalid example name '{name}': unsupported character(s): {chars!r}"
        )


def load_specs(config_path: Path) -> tuple[Path, list[ExampleSpec]]:
    config = load_json(config_path)

    examples_root_raw = config.get("examples_root", "../../examples")
    examples_root = Path(
        require_str(examples_root_raw, "examples_root", str(config_path))
    )

    if not examples_root.is_absolute():
        examples_root = (config_path.parent / examples_root).resolve()

    defaults = config.get("defaults", {})
    if defaults is None:
        defaults = {}
    if not isinstance(defaults, dict):
        raise RuntimeError(f"invalid 'defaults' in {config_path}: must be an object")

    default_position = defaults.get("position", True)
    default_position = require_bool(
        default_position,
        "defaults.position",
        str(config_path),
    )
    default_directory = normalize_directory(
        defaults.get("directory"),
        "defaults.directory",
        str(config_path),
    )

    cases = config.get("cases")
    if not isinstance(cases, list):
        raise RuntimeError(f"missing or invalid 'cases' in {config_path}")

    specs: list[ExampleSpec] = []

    for case_index, case_data in enumerate(cases):
        context = f"{config_path}: cases[{case_index}]"

        if not isinstance(case_data, dict):
            raise RuntimeError(f"invalid case entry in {context}: must be an object")

        case = require_str(case_data.get("case"), "case", context)
        case_position = case_data.get("position", default_position)
        case_directory = normalize_directory(
            case_data.get("directory", default_directory),
            "directory",
            context,
        )

        if not isinstance(case_position, bool):
            raise RuntimeError(f"invalid 'position' in {context}: must be a boolean")

        examples = case_data.get("examples")
        if not isinstance(examples, list):
            raise RuntimeError(f"missing or invalid 'examples' in {context}")

        for example_index, example_data in enumerate(examples):
            example_context = f"{context}.examples[{example_index}]"

            if not isinstance(example_data, dict):
                raise RuntimeError(
                    f"invalid example entry in {example_context}: must be an object"
                )

            name = require_str(example_data.get("name"), "name", example_context)
            old_rev = require_str(
                example_data.get("old_rev"), "old_rev", example_context
            )
            new_rev = require_str(
                example_data.get("new_rev"), "new_rev", example_context
            )

            placeholder_values = {
                "REPLACE_WITH_OLD_REV",
                "REPLACE_WITH_NEW_REV",
            }

            if old_rev in placeholder_values or new_rev in placeholder_values:
                raise RuntimeError(
                    f"placeholder revision left in {example_context}: "
                    "replace old_rev/new_rev with real commits, tags, or branches"
                )

            position = example_data.get("position", case_position)
            directory = normalize_directory(
                example_data.get("directory", case_directory),
                "directory",
                example_context,
            )

            if not isinstance(position, bool):
                raise RuntimeError(
                    f"invalid 'position' in {example_context}: must be a boolean"
                )

            validate_example_name(name)

            specs.append(
                ExampleSpec(
                    case=case,
                    name=name,
                    old_rev=old_rev,
                    new_rev=new_rev,
                    position=position,
                    directory=directory,
                )
            )

    return examples_root, specs


def filter_specs(specs: list[ExampleSpec], only: str | None) -> list[ExampleSpec]:
    if only is None:
        return specs

    if ":" in only:
        case, name = only.split(":", 1)
        matches = [spec for spec in specs if spec.case == case and spec.name == name]
    else:
        matches = [spec for spec in specs if spec.name == only]

    if not matches:
        raise RuntimeError(f"no configured example matched --only {only!r}")

    if len(matches) > 1:
        choices = ", ".join(f"{spec.case}:{spec.name}" for spec in matches)
        raise RuntimeError(
            f"--only {only!r} matched multiple examples; use one of: {choices}"
        )

    return matches


def safe_filename_part(value: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    cleaned = "".join(ch if ch in allowed else "_" for ch in value.strip())

    if not cleaned:
        raise RuntimeError(f"could not make safe filename from {value!r}")

    return cleaned


def short_commit(commit: str) -> str:
    return commit[:12]


def output_prefix(spec: ExampleSpec, old_commit: str, new_commit: str) -> str:
    name = safe_filename_part(spec.name)

    old_label = safe_filename_part(spec.old_rev)
    new_label = safe_filename_part(spec.new_rev)

    old_short = short_commit(old_commit)
    new_short = short_commit(new_commit)

    base = f"{spec.case}.{name}.{old_label}-to-{new_label}.{old_short}-to-{new_short}"

    if spec.position:
        return f"{base}.position"

    return base


def expected_static_prefix(spec: ExampleSpec) -> str:
    name = safe_filename_part(spec.name)
    base = f"{spec.case}.{name}"

    if spec.position:
        return f"{base}.position"

    return base


def case_relative_output_dir(spec: ExampleSpec) -> Path:
    if spec.directory is None:
        return Path()

    return Path(*spec.directory.split("/"))


def output_dir_for_spec(*, examples_root: Path, spec: ExampleSpec) -> Path:
    return examples_root / spec.case / case_relative_output_dir(spec)


def existing_outputs_for_spec(
    *,
    examples_root: Path,
    spec: ExampleSpec,
) -> tuple[Path, Path, Path] | None:
    case_dir = examples_root / spec.case
    output_dir = output_dir_for_spec(examples_root=examples_root, spec=spec)

    if not output_dir.is_dir():
        return None

    name = safe_filename_part(spec.name)
    old_label = safe_filename_part(spec.old_rev)
    new_label = safe_filename_part(spec.new_rev)

    position_suffix = ".position" if spec.position else ""

    report_glob = (
        f"{spec.case}.{name}.{old_label}-to-{new_label}.*{position_suffix}.report.json"
    )

    reports = sorted(output_dir.glob(report_glob))

    if not reports:
        return None

    report_path = reports[-1]

    with report_path.open("r", encoding="utf-8") as f:
        report = json.load(f)

    example = report.get("example")
    if not isinstance(example, dict):
        return None

    srcdiff_file = example.get("srcdiff_file")
    srcmove_file = example.get("srcmove_file")

    if not isinstance(srcdiff_file, str) or not isinstance(srcmove_file, str):
        return None

    srcdiff_path = case_dir / srcdiff_file
    srcmove_path = case_dir / srcmove_file

    if srcdiff_path.is_file() and srcmove_path.is_file() and report_path.is_file():
        return srcdiff_path, srcmove_path, report_path

    return None


def run_single_example(
    *,
    spec: ExampleSpec,
    refresh_repo: bool,
) -> dict[str, Any]:
    resolved_old_rev = resolve_config_rev(spec.case, spec.old_rev)
    resolved_new_rev = resolve_config_rev(spec.case, spec.new_rev)

    cmd = [
        sys.executable,
        str(RUNNER),
        spec.case,
        "--old-rev",
        resolved_old_rev,
        "--new-rev",
        resolved_new_rev,
    ]

    if spec.position:
        cmd.append("--position")

    if spec.directory:
        cmd.extend(["--directory", spec.directory])

    if refresh_repo:
        cmd.append("--refresh-repo")

    print(f"running: {' '.join(cmd)}")
    result = run_command(cmd, cwd=REPO_ROOT, capture_output=False)

    if result.returncode != 0:
        raise RuntimeError(f"example failed: {spec.case}:{spec.name}")

    report_path = SCRIPT_DIR / spec.case / "work" / "report.json"
    if not report_path.is_file():
        raise RuntimeError(f"expected report not found: {report_path}")

    return load_json(report_path)


def copy_built_files(
    *,
    examples_root: Path,
    spec: ExampleSpec,
    runner_report: dict[str, Any],
) -> BuiltExample:
    paths = runner_report.get("paths")
    if not isinstance(paths, dict):
        raise RuntimeError("runner report is missing 'paths' object")

    diff_xml_raw = paths.get("diff_xml")
    move_xml_raw = paths.get("diff_new_xml")

    if not isinstance(diff_xml_raw, str):
        raise RuntimeError("runner report is missing paths.diff_xml")
    if not isinstance(move_xml_raw, str):
        raise RuntimeError("runner report is missing paths.diff_new_xml")

    diff_xml = Path(diff_xml_raw)
    move_xml = Path(move_xml_raw)

    if not diff_xml.is_file():
        raise RuntimeError(f"generated srcdiff file not found: {diff_xml}")
    if not move_xml.is_file():
        raise RuntimeError(f"generated srcMove file not found: {move_xml}")

    old_commit = require_str(
        runner_report.get("old_commit"), "old_commit", "runner report"
    )
    new_commit = require_str(
        runner_report.get("new_commit"), "new_commit", "runner report"
    )

    case_dir = examples_root / spec.case
    output_dir = output_dir_for_spec(examples_root=examples_root, spec=spec)
    output_dir.mkdir(parents=True, exist_ok=True)

    prefix = output_prefix(spec, old_commit, new_commit)

    dest_diff = output_dir / f"{prefix}.diff.xml"
    dest_move = output_dir / f"{prefix}.move.diff.xml"
    dest_report = output_dir / f"{prefix}.report.json"

    shutil.copy2(diff_xml, dest_diff)
    shutil.copy2(move_xml, dest_move)

    srcdiff_seconds = runner_report.get("srcdiff_seconds")
    srcmove_seconds = runner_report.get("srcmove_seconds")
    move_count = runner_report.get("move_count")

    if not isinstance(srcdiff_seconds, int | float):
        srcdiff_seconds = None
    if not isinstance(srcmove_seconds, int | float):
        srcmove_seconds = None
    if not isinstance(move_count, int):
        move_count = None

    built = BuiltExample(
        case=spec.case,
        name=spec.name,
        old_rev=spec.old_rev,
        new_rev=spec.new_rev,
        old_commit=old_commit,
        new_commit=new_commit,
        position=spec.position,
        directory=spec.directory,
        srcdiff_file=dest_diff.relative_to(case_dir).as_posix(),
        srcmove_file=dest_move.relative_to(case_dir).as_posix(),
        report_file=dest_report.relative_to(case_dir).as_posix(),
        srcdiff_seconds=srcdiff_seconds,
        srcmove_seconds=srcmove_seconds,
        move_count=move_count,
    )

    report = {
        **runner_report,
        "example": {
            "name": spec.name,
            "position": spec.position,
            "directory": spec.directory,
            "srcdiff_file": built.srcdiff_file,
            "srcmove_file": built.srcmove_file,
            "report_file": built.report_file,
        },
    }

    with dest_report.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return built


def load_existing_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.is_file():
        return {
            "schema_version": 1,
            "examples": [],
        }

    return load_json(manifest_path)


def example_key(example: dict[str, Any]) -> tuple[str, str, str, bool]:
    case = example.get("case")
    name = example.get("name")
    directory = example.get("directory")
    position = example.get("position")

    if not isinstance(case, str):
        case = ""
    if not isinstance(name, str):
        name = ""
    if not isinstance(directory, str):
        directory = ""
    if not isinstance(position, bool):
        position = False

    return case, name, directory, position


def built_example_to_manifest_entry(built: BuiltExample) -> dict[str, Any]:
    return {
        "case": built.case,
        "name": built.name,
        "old_rev": built.old_rev,
        "new_rev": built.new_rev,
        "old_commit": built.old_commit,
        "new_commit": built.new_commit,
        "position": built.position,
        "directory": built.directory,
        "srcdiff_file": f"{built.case}/{built.srcdiff_file}",
        "srcmove_file": f"{built.case}/{built.srcmove_file}",
        "report_file": f"{built.case}/{built.report_file}",
        "srcdiff_seconds": built.srcdiff_seconds,
        "srcmove_seconds": built.srcmove_seconds,
        "move_count": built.move_count,
    }


def write_manifest(
    *,
    examples_root: Path,
    built_examples: list[BuiltExample],
) -> None:
    manifest_path = examples_root / "manifest.json"
    manifest = load_existing_manifest(manifest_path)

    existing_entries = manifest.get("examples")
    if not isinstance(existing_entries, list):
        existing_entries = []

    by_key: dict[tuple[str, str, str, bool], dict[str, Any]] = {}

    for entry in existing_entries:
        if isinstance(entry, dict):
            by_key[example_key(entry)] = entry

    for built in built_examples:
        entry = built_example_to_manifest_entry(built)
        by_key[example_key(entry)] = entry

    manifest["schema_version"] = 1
    manifest["examples"] = sorted(
        by_key.values(),
        key=lambda entry: (
            str(entry.get("case", "")),
            str(entry.get("name", "")),
            str(entry.get("directory", "")),
            str(entry.get("old_commit", "")),
            str(entry.get("new_commit", "")),
            str(entry.get("position", "")),
        ),
    )

    examples_root.mkdir(parents=True, exist_ok=True)

    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"manifest: {manifest_path}")


def build_examples(
    *,
    examples_root: Path,
    specs: list[ExampleSpec],
    force: bool,
    dry_run: bool,
    refresh_repo: bool,
) -> int:
    built_examples: list[BuiltExample] = []
    skipped = 0

    for spec in specs:
        label = f"{spec.case}:{spec.name}"

        existing = existing_outputs_for_spec(
            examples_root=examples_root,
            spec=spec,
        )

        if existing is not None and not force:
            skipped += 1
            diff_path, move_path, report_path = existing
            print(f"skip existing: {label}")
            print(f"  {diff_path}")
            print(f"  {move_path}")
            print(f"  {report_path}")
            continue

        if dry_run:
            print(f"would build: {label}")
            print(f"  old_rev : {spec.old_rev}")
            print(f"  new_rev : {spec.new_rev}")
            print(f"  position: {spec.position}")
            if spec.directory:
                print(f"  directory: {spec.directory}")
            continue

        print(f"build: {label}")
        runner_report = run_single_example(
            spec=spec,
            refresh_repo=refresh_repo,
        )
        built = copy_built_files(
            examples_root=examples_root,
            spec=spec,
            runner_report=runner_report,
        )
        built_examples.append(built)

        print("saved:")
        print(f"  {examples_root / built.case / built.srcdiff_file}")
        print(f"  {examples_root / built.case / built.srcmove_file}")
        print(f"  {examples_root / built.case / built.report_file}")

    if built_examples and not dry_run:
        write_manifest(
            examples_root=examples_root,
            built_examples=built_examples,
        )

    print()
    print("================================")
    print(f"configured: {len(specs)}")
    print(f"built     : {len(built_examples)}")
    print(f"skipped   : {skipped}")

    return 0


def main() -> int:
    args = parse_args()

    if not RUNNER.is_file():
        print(f"error: runner not found: {RUNNER}", file=sys.stderr)
        return 1

    examples_root, specs = load_specs(args.config)
    specs = filter_specs(specs, args.only)

    return build_examples(
        examples_root=examples_root,
        specs=specs,
        force=args.force,
        dry_run=args.dry_run,
        refresh_repo=args.refresh_repo,
    )


def load_commit_manifest(case: str) -> dict[str, Any] | None:
    manifest_path = SCRIPT_DIR / case / "commits.json"

    if not manifest_path.is_file():
        return None

    return load_json(manifest_path)


def build_commit_lookup(case: str) -> dict[str, str]:
    manifest = load_commit_manifest(case)

    if manifest is None:
        return {}

    commits = manifest.get("commits")
    if not isinstance(commits, list):
        raise RuntimeError(f"invalid commits.json for {case}: missing commits list")

    lookup: dict[str, str] = {}

    for entry in commits:
        if not isinstance(entry, dict):
            continue

        seq = entry.get("seq")
        commit = entry.get("commit")
        short = entry.get("short")

        if isinstance(seq, str) and isinstance(commit, str):
            lookup[seq] = commit

        if isinstance(short, str) and isinstance(commit, str):
            lookup[short] = commit

    return lookup


def resolve_config_rev(case: str, rev: str) -> str:
    lookup = build_commit_lookup(case)

    return lookup.get(rev, rev)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)
