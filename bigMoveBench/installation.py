"""Locate and describe the external BigCloneBench installation."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarking.provenance import sha256_file
from benchmarking.tooling import run_command


BCE_DIR = PACKAGE_ROOT / "data" / "BigCloneEval"


def _corpus_layouts(bce_dir: Path) -> list[str]:
    ijadataset = bce_dir / "ijadataset"
    layouts = []
    if any(
        next((ijadataset / kind).glob("*.java"), None) is not None
        for kind in ("default", "sample", "selected")
    ):
        layouts.append("flat")
    if next(ijadataset.glob("bcb_reduced/*/*/*.java"), None) is not None:
        layouts.append("reduced")
    return layouts


def preflight(bce_dir: Path = BCE_DIR) -> list[str]:
    """Return actionable missing-prerequisite messages without fetching data."""

    bce_dir = bce_dir.expanduser().resolve()
    required = {
        "BigCloneBench database": bce_dir / "bigclonebenchdb" / "bcb.h2.db",
        "H2 driver": bce_dir / "libs" / "h2-1.3.176.jar",
    }
    failures = [
        f"{label} not found: {path}"
        for label, path in required.items()
        if not path.exists()
    ]
    ijadataset = bce_dir / "ijadataset"
    if not _corpus_layouts(bce_dir):
        failures.append(
            "IJaDataset Java corpus not found: expected either "
            f"{ijadataset}/{{default,sample,selected}}/*.java or "
            f"{ijadataset}/bcb_reduced/<functionality>/"
            "{default,sample,selected}/*.java"
        )
    if shutil.which("java") is None:
        failures.append("Java executable not found on PATH")
    return failures


def require_preflight(bce_dir: Path = BCE_DIR) -> None:
    """Raise with setup guidance when BigCloneBench cannot be used."""

    failures = preflight(bce_dir)
    if failures:
        joined = "\n  - ".join(failures)
        raise RuntimeError(
            "BigCloneBench is an external manual prerequisite; it will not be "
            "downloaded automatically.\n  - "
            f"{joined}\nSee bigMoveBench/README.md for setup guidance."
        )


def java_identity() -> dict[str, str]:
    """Return the identity of the Java runtime used to query BigCloneBench."""

    executable = shutil.which("java")
    if executable is None:
        return {"status": "unavailable"}
    result = run_command([executable, "-version"])
    version = (result.stderr or result.stdout).strip().splitlines()
    resolved = Path(executable).resolve()
    return {
        "executable": resolved.name,
        "sha256": sha256_file(resolved),
        "version": version[0] if version else "unknown",
    }


def main(bce_dir: Path = BCE_DIR) -> int:
    bce_dir = bce_dir.expanduser().resolve()
    failures = preflight(bce_dir)
    if failures:
        print(
            "error: BigCloneBench prerequisites are unavailable:",
            file=sys.stderr,
        )
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        print("See bigMoveBench/README.md for setup guidance.", file=sys.stderr)
        return 2
    layouts = " + ".join(_corpus_layouts(bce_dir))
    java = shutil.which("java")
    assert java is not None
    print("BigCloneBench preflight passed")
    print(f"  [ok] Database:   {bce_dir / 'bigclonebenchdb' / 'bcb.h2.db'}")
    print(f"  [ok] H2 driver:  {bce_dir / 'libs' / 'h2-1.3.176.jar'}")
    print(f"  [ok] IJaDataset: {bce_dir / 'ijadataset'} ({layouts} layout)")
    print(f"  [ok] Java:       {Path(java).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
