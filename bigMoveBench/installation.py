"""Locate and describe the external BigCloneBench installation."""

from __future__ import annotations

import shutil
from pathlib import Path

from benchmarking.provenance import sha256_file
from benchmarking.tooling import run_command


PACKAGE_ROOT = Path(__file__).resolve().parent
BCE_DIR = PACKAGE_ROOT / "data" / "BigCloneEval"


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
    has_flat_sources = any(
        next((ijadataset / kind).glob("*.java"), None) is not None
        for kind in ("default", "sample", "selected")
    )
    has_reduced_sources = (
        next(ijadataset.glob("bcb_reduced/*/*/*.java"), None) is not None
    )
    if not has_flat_sources and not has_reduced_sources:
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
