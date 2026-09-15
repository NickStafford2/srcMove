"""Shared BigCloneBench source-resolution and extraction rules."""

from __future__ import annotations

from pathlib import Path


EXTRACTION_POLICY_VERSION = 1


def source_path(
    bce_dir: Path,
    kind: str,
    name: str,
    functionality_id: int,
) -> Path:
    """Resolve a function source in the full or reduced IJaDataset layout."""

    ijadataset = bce_dir / "ijadataset"
    flat = ijadataset / kind / name
    if flat.is_file():
        return flat

    reduced = ijadataset / "bcb_reduced" / str(functionality_id) / kind / name
    if reduced.is_file() or (ijadataset / "bcb_reduced").is_dir():
        return reduced
    return flat


def extract_lines(path: Path, startline: int, endline: int) -> str:
    """Extract an inclusive LF-based BigCloneBench source range."""

    return extract_bytes(path.read_bytes(), startline, endline, source=path)


def extract_bytes(
    value: bytes,
    startline: int,
    endline: int,
    *,
    source: Path | str = "<bytes>",
) -> str:
    """Extract a range from source bytes already loaded by a bulk compiler."""

    if startline < 1 or endline < startline:
        raise ValueError(
            f"invalid BigCloneBench line range {startline}:{endline}: {source}"
        )
    # Some IJaDataset files contain standalone CR characters inside comments.
    # splitlines() would count those as source lines and shift later fragments.
    lines = value.decode("utf-8", errors="replace").split("\n")
    if endline > len(lines):
        raise ValueError(
            f"BigCloneBench line range {startline}:{endline} exceeds "
            f"{len(lines)} LF-delimited lines: {source}"
        )
    fragment = [line.removesuffix("\r") for line in lines[startline - 1 : endline]]
    value = "\n".join(fragment).rstrip() + "\n"
    if not value.strip():
        raise ValueError(
            f"BigCloneBench line range {startline}:{endline} is empty: {source}"
        )
    return value
