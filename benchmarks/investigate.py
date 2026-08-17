#!/usr/bin/env python3
"""Replay or reduce a preserved srcDiff benchmark attempt."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.corpus import (  # noqa: E402
    PREPARATION_SCHEMA_VERSION,
    _load_manifest,
    _resolve_manifest,
    _verify_preparation,
)
from benchmarks.process import (  # noqa: E402
    execute_attempt,
    validate_srcdiff_xml,
    write_json_atomic,
)
from benchmarks.provenance import observe_executable, sha256_file, utc_now  # noqa: E402


DEFAULT_DATA_ROOT = REPO_ROOT / "benchmark-data"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("replay", "isolate"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("attempt")
        subparser.add_argument("--srcdiff", type=Path)
        subparser.add_argument("--timeout", type=float)
        subparser.add_argument(
            "--relative-path",
            action="append",
            default=[],
            help="Replay only this preserved relative path (repeatable).",
        )
    subparsers.choices["isolate"].add_argument("--max-attempts", type=int, default=32)
    return parser.parse_args()


def load_attempt(data_root: Path, value: str) -> tuple[Path, dict[str, Any]]:
    supplied = Path(value)
    candidates = [
        supplied,
        supplied / "attempt.json",
        data_root / "attempts" / value / "attempt.json",
    ]
    for candidate in candidates:
        path = candidate / "attempt.json" if candidate.is_dir() else candidate
        if path.is_file():
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("stage") != "srcdiff":
                raise ValueError("investigation requires a srcdiff attempt")
            return path.resolve(), record
    raise FileNotFoundError(f"attempt record not found: {value}")


def prepared_inputs(
    data_root: Path, attempt: dict[str, Any]
) -> tuple[Path, Path, Path]:
    context = attempt.get("context", {})
    preparation = context.get("preparation_id")
    if not isinstance(preparation, str):
        raise ValueError("attempt predates preserved preparation references")
    manifest_path = _resolve_manifest(data_root, "preparations", preparation)
    manifest = _load_manifest(
        manifest_path, PREPARATION_SCHEMA_VERSION, "preparation_id"
    )
    _verify_preparation(manifest_path.parent, manifest)
    if sha256_file(manifest_path) != context.get("preparation_manifest_sha256"):
        raise ValueError("preserved preparation manifest checksum mismatch")
    return (
        manifest_path.parent,
        manifest_path.parent / context["original_path"],
        manifest_path.parent / context["modified_path"],
    )


def copy_relative_files(source: Path, destination: Path, paths: Sequence[str]) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    if source.is_file():
        if paths and source.name not in paths:
            return
        shutil.copy2(source, destination / source.name)
        return
    for value in paths:
        relative = Path(value)
        candidate = source / relative
        if candidate.is_file():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, target)


def relative_inventory(original: Path, modified: Path) -> list[str]:
    paths: set[str] = set()
    for root in (original, modified):
        if root.is_file():
            paths.add(root.name)
        else:
            paths.update(
                candidate.relative_to(root).as_posix()
                for candidate in root.rglob("*")
                if candidate.is_file()
            )
    return sorted(paths)


def reproduction_inventory(original: Path, modified: Path) -> list[dict[str, Any]]:
    inventory = []
    for side, root in (("original", original), ("modified", modified)):
        for relative in relative_inventory(root, root):
            path = root / relative if root.is_dir() else root
            if path.is_file():
                inventory.append(
                    {
                        "side": side,
                        "path": relative,
                        "size_bytes": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                )
    return inventory


def replay_command(
    attempt: dict[str, Any], executable: Path, original: Path, modified: Path
):
    prior = attempt["command"]
    output_index = prior.index("-o")
    prefix = prior[1 : output_index - 2]

    def command(output: Path) -> Sequence[str]:
        return [
            str(executable),
            *prefix,
            str(original),
            str(modified),
            "-o",
            str(output),
        ]

    return command


def run_replay(
    *,
    data_root: Path,
    attempt: dict[str, Any],
    original: Path,
    modified: Path,
    executable: Path,
    timeout: float,
    context: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    return execute_attempt(
        attempts_root=data_root / "attempts",
        stage="srcdiff",
        case_id=attempt["case_id"],
        command_factory=replay_command(attempt, executable, original, modified),
        cwd=original.parent,
        timeout_seconds=timeout,
        xml_validator=lambda path: validate_srcdiff_xml(
            path, attempt["context"]["expected_shape"]
        ),
        output_filename="partial.srcdiff.xml",
        parent_attempt_id=attempt["attempt_id"],
        retry_ordinal=attempt.get("retry_ordinal", 0) + 1,
        context=context,
    )


def main() -> int:
    args = parse_args()
    data_root = args.data_root.expanduser().resolve()
    _, attempt = load_attempt(data_root, args.attempt)
    _, original, modified = prepared_inputs(data_root, attempt)
    executable = (args.srcdiff or Path(attempt["command"][0])).expanduser().resolve()
    observation = observe_executable(executable)
    if observation.get("artifact", {}).get("status") != "observed":
        raise ValueError(f"srcdiff executable unavailable: {executable}")
    timeout = args.timeout if args.timeout is not None else attempt["timeout_seconds"]
    inventory = relative_inventory(original, modified)
    selected = args.relative_path or inventory
    unknown = set(selected) - set(inventory)
    if unknown:
        raise ValueError(f"unknown relative path(s): {', '.join(sorted(unknown))}")

    investigation_id = f"investigation-{uuid.uuid4()}"
    investigation_dir = data_root / "investigations" / investigation_id
    investigation_dir.mkdir(parents=True, exist_ok=False)

    def materialize(paths: Sequence[str], ordinal: int) -> tuple[Path, Path]:
        subset = investigation_dir / f"subset-{ordinal:03d}"
        copy_relative_files(original, subset / "original", paths)
        copy_relative_files(modified, subset / "modified", paths)
        return subset / "original", subset / "modified"

    attempts: list[dict[str, Any]] = []
    if args.command == "replay":
        replay_original, replay_modified = materialize(selected, 0)
        _, replay = run_replay(
            data_root=data_root,
            attempt=attempt,
            original=replay_original,
            modified=replay_modified,
            executable=executable,
            timeout=timeout,
            context={**attempt["context"], "investigation_id": investigation_id},
        )
        attempts.append(
            {
                "paths": selected,
                "attempt_id": replay["attempt_id"],
                "admitted": replay["admitted"],
                "command": replay["command"],
                "termination": replay["termination"],
            }
        )
        reproduction_original = replay_original
        reproduction_modified = replay_modified
    else:
        current = selected
        while len(current) > 1 and len(attempts) < args.max_attempts:
            midpoint = (len(current) + 1) // 2
            candidates = (current[:midpoint], current[midpoint:])
            reduced = False
            for candidate in candidates:
                if not candidate or len(attempts) >= args.max_attempts:
                    continue
                replay_original, replay_modified = materialize(candidate, len(attempts))
                _, replay = run_replay(
                    data_root=data_root,
                    attempt=attempt,
                    original=replay_original,
                    modified=replay_modified,
                    executable=executable,
                    timeout=timeout,
                    context={
                        **attempt["context"],
                        "investigation_id": investigation_id,
                    },
                )
                attempts.append(
                    {
                        "paths": candidate,
                        "attempt_id": replay["attempt_id"],
                        "admitted": replay["admitted"],
                        "command": replay["command"],
                        "termination": replay["termination"],
                    }
                )
                if not replay["admitted"]:
                    current = list(candidate)
                    reduced = True
                    break
            if not reduced:
                break
        selected = current
        reproduction_original, reproduction_modified = materialize(
            selected, len(attempts)
        )

    manifest = {
        "schema_version": 1,
        "investigation_id": investigation_id,
        "created_at": utc_now(),
        "source_attempt_id": attempt["attempt_id"],
        "preparation_id": attempt["context"]["preparation_id"],
        "srcdiff": observation,
        "timeout_seconds": timeout,
        "selected_paths": selected,
        "reproduction": {
            "original_path": str(reproduction_original.relative_to(investigation_dir)),
            "modified_path": str(reproduction_modified.relative_to(investigation_dir)),
            "files": reproduction_inventory(
                reproduction_original, reproduction_modified
            ),
        },
        "attempts": attempts,
        "note": (
            "A reduced failure is diagnostic; files may interact when neither half "
            "fails alone."
        ),
    }
    write_json_atomic(investigation_dir / "manifest.json", manifest)
    print(f"investigation_id={investigation_id}")
    print(f"directory={investigation_dir}")
    return 0 if attempts and attempts[-1]["admitted"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2)
