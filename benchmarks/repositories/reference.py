"""Reference-repository configuration and local clone management."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


def _run(
    command: list[str], *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _require_ok(result: subprocess.CompletedProcess[str], what: str) -> None:
    if result.returncode != 0:
        raise RuntimeError(
            f"{what} failed with exit code {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def normalize_repository_subdirectory(
    value: object, context: str
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"invalid 'directory' in {context}: must be a string")
    subdirectory = value.strip().replace("\\", "/").strip("/")
    if not subdirectory or subdirectory in (".", "./"):
        return None
    if (
        subdirectory.startswith("../")
        or "/../" in subdirectory
        or subdirectory == ".."
    ):
        raise RuntimeError(
            f"invalid 'directory' in {context}: must stay within the repository"
        )
    return subdirectory


@dataclass(frozen=True)
class ReferenceConfiguration:
    name: str
    url: str
    checkout: str
    analysis_directory: str | None
    roles: tuple[str, ...]


def _required_string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"missing or invalid {context}")
    return value


def load_reference_configuration(
    path: Path, name: str
) -> ReferenceConfiguration:
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise RuntimeError(f"unsupported or malformed repository registry: {path}")
    repositories = data.get("repositories")
    if not isinstance(repositories, dict):
        raise RuntimeError(f"missing or invalid 'repositories' object in {path}")
    raw = repositories.get(name)
    if not isinstance(raw, dict):
        raise RuntimeError(f"unknown reference repository {name!r} in {path}")
    checkout = _required_string(raw.get("checkout"), f"checkout for {name!r}")
    if Path(checkout).name != checkout or checkout in (".", ".."):
        raise RuntimeError(f"checkout for {name!r} must be one directory name")
    raw_roles = raw.get("roles", [])
    if not isinstance(raw_roles, list) or any(
        not isinstance(role, str) or not role for role in raw_roles
    ):
        raise RuntimeError(f"roles for {name!r} must be strings")
    return ReferenceConfiguration(
        name=name,
        url=_required_string(raw.get("url"), f"URL for {name!r}"),
        checkout=checkout,
        analysis_directory=normalize_repository_subdirectory(
            raw.get("analysis_directory"), f"{path}: {name}"
        ),
        roles=tuple(raw_roles),
    )


def _origin_url(repository: Path) -> str | None:
    result = _run(["git", "remote", "get-url", "origin"], cwd=repository)
    return result.stdout.strip() if result.returncode == 0 else None


def _clone(repository_url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = _run(["git", "clone", repository_url, str(destination)])
    _require_ok(result, "git clone")


def update_reference_repository(repository: Path) -> None:
    result = _run(
        ["git", "fetch", "origin", "--tags", "--prune"], cwd=repository
    )
    _require_ok(result, "git fetch origin --tags --prune")


def ensure_reference_repository(
    repository_url: str,
    destination: Path,
    *,
    offline: bool,
    update: bool,
) -> bool:
    """Prepare a reference clone and report whether network work was performed."""

    if not destination.exists():
        if offline:
            raise RuntimeError(
                f"reference repository is missing in offline mode: {destination}"
            )
        _clone(repository_url, destination)
        return True
    if not (destination / ".git").exists():
        raise RuntimeError(f"existing path is not a Git repository: {destination}")
    current_origin = _origin_url(destination)
    if current_origin != repository_url:
        raise RuntimeError(
            "reference repository origin mismatch: expected "
            f"{repository_url}, found {current_origin}"
        )
    if update:
        update_reference_repository(destination)
        return True
    return False
