"""Unversioned, development-only srcDiff output cache for BigMoveBench."""

from __future__ import annotations

import gzip
import os
import shutil
import tempfile
from pathlib import Path


CACHE_FORMAT_VERSION = 1


class DevelopmentSrcdiffCache:
    """Store compressed XML without tracking or validating the srcDiff build."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    @staticmethod
    def _digest(case_id: str) -> str:
        digest = case_id.rsplit("-", 1)[-1]
        if (
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(f"invalid generated case ID: {case_id!r}")
        return digest

    def path(self, case_id: str, wrapper_version: int) -> Path:
        digest = self._digest(case_id)
        return (
            self.root
            / f"v{CACHE_FORMAT_VERSION}"
            / f"wrapper-{wrapper_version}"
            / digest[:2]
            / digest[2:4]
            / f"{case_id}.xml.gz"
        )

    def restore(
        self,
        *,
        case_id: str,
        wrapper_version: int,
        destination: Path,
    ) -> bool:
        """Decompress a cache hit atomically; return false for a miss or damage."""

        source = self.path(case_id, wrapper_version)
        if source.is_symlink() or not source.is_file():
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        temporary = Path(temporary_name)
        try:
            with (
                gzip.open(source, "rb") as compressed,
                os.fdopen(descriptor, "wb") as output,
            ):
                shutil.copyfileobj(compressed, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
            return True
        except (EOFError, OSError):
            try:
                os.close(descriptor)
            except OSError:
                pass
            temporary.unlink(missing_ok=True)
            return False

    def store(
        self,
        *,
        case_id: str,
        wrapper_version: int,
        source: Path,
    ) -> Path:
        """Atomically replace one cache entry with a fast-compressed XML file."""

        destination = self.path(case_id, wrapper_version)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=destination.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with source.open("rb") as input_stream, gzip.open(
                temporary, "wb", compresslevel=1
            ) as compressed:
                shutil.copyfileobj(input_stream, compressed)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination
