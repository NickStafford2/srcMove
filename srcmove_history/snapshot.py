"""Immutable, portable evidence snapshots of a completed history frontier."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import os
import zipfile
from uuid import uuid4

from .database import AnalysisDatabase
from .inputs import canonical_pretty_json_bytes
from .locking import AnalysisOperationLock
from .queries import AnalysisReader
from .report import build_report, render_report


def export_snapshot(root: Path) -> dict[str, object]:
    """Export a consistent frontier; reuse identical bytes without overwriting."""
    with AnalysisOperationLock(root, command="snapshot"):
        reader = AnalysisReader(root)
        status = reader.status().record()
        # A snapshot describes evidence, not one container's mount layout.
        # Keep the same bytes when exporting this state through /workspace
        # in the development shell or /history in the viewer container.
        status["analysis"]["root"] = "."
        status["analysis"]["repository"] = ".."
        if status["pending"] is not None:
            raise ValueError("finish the pending history batch before exporting a snapshot")
        with AnalysisDatabase.open(root, read_only=True) as database:
            definition = database.initial_manifest().record()
        pairs = []
        cursor = None
        while True:
            page = reader.list_pairs(limit=1000, after_distance=cursor)
            pairs.extend(reader.show(item.number).record() for item in page.items)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        files = {
            "definition.json": canonical_pretty_json_bytes(definition),
            "status.json": canonical_pretty_json_bytes(status),
            "pairs.jsonl": b"".join(json.dumps(pair, sort_keys=True).encode() + b"\n" for pair in pairs),
            "report.txt": (render_report(replace(build_report(root), analysis_root=Path("."))) + "\n").encode(),
            "config.toml": (root / "config.toml").read_bytes(),
        }
        for pair in pairs:
            directory = root / "comparisons" / f"{pair['old_commit']}-to-{pair['new_commit']}"
            verification = directory / "history-evidence.json"
            if verification.exists():
                record = json.loads(verification.read_text())
                if record["pair_fingerprint"] != pair["pair_fingerprint"]:
                    raise ValueError("saved comparison belongs to different evidence")
                for name, expected in record["files"].items():
                    content = (directory / name).read_bytes()
                    if hashlib.sha256(content).hexdigest() != expected:
                        raise ValueError("saved comparison checksum mismatch")
                    files[f"comparisons/{pair['number']}/{name}"] = content
                files[f"comparisons/{pair['number']}/history-evidence.json"] = verification.read_bytes()
        for name in ("srcMove.build-receipt.json", "workflow-provenance.json"):
            if (root / name).is_file():
                files[name] = (root / name).read_bytes()
        checksums = {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())}
        identity = hashlib.sha256(canonical_pretty_json_bytes(checksums)).hexdigest()
        manifest = {
            "schema_version": 1, "snapshot_id": identity,
            "covered_commit_pairs": len(pairs), "files": checksums,
            "definition_sha256": checksums["definition.json"],
            "note": "Detector observations; source review judgments are separate. Comparisons are included only when regenerated output matched stored detections.",
        }
        files["manifest.json"] = canonical_pretty_json_bytes(manifest)
        destination = root / "snapshots" / f"{identity}.zip"
        destination.parent.mkdir(exist_ok=True)
        temporary = destination.parent / f".snapshot-{uuid4().hex}.zip"
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in sorted(files.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, content)
        if destination.exists():
            if destination.read_bytes() != temporary.read_bytes():
                raise ValueError("snapshot identity already exists with different bytes")
            temporary.unlink()
        else:
            os.replace(temporary, destination)
        return {"schema_version": 1, "snapshot_id": identity, "path": str(destination), "covered_commit_pairs": len(pairs)}
