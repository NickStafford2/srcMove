"""Status vocabulary and content identity shared by benchmark components."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum


CONTRACT_VERSION = 2


class RunMode(StrEnum):
    DEVELOPMENT = "development"
    PUBLICATION = "publication"


class ProvenanceStatus(StrEnum):
    VERIFIED = "verified"
    STALE = "stale"
    UNVERIFIED = "unverified"
    UNAVAILABLE = "unavailable"


class TerminationStatus(StrEnum):
    EXITED = "exited"
    SIGNALED = "signaled"
    TIMED_OUT = "timed_out"
    SPAWN_FAILED = "spawn_failed"
    ORCHESTRATION_INTERRUPTED = "orchestration_interrupted"


class XmlStatus(StrEnum):
    VALID = "valid"
    MISSING = "missing"
    EMPTY = "empty"
    MALFORMED = "malformed"
    INVALID_STRUCTURE = "invalid_structure"
    NOT_CHECKED = "not_checked"


JsonValue = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


def canonical_json(value: JsonValue) -> bytes:
    """Serialize an identity payload deterministically as UTF-8 JSON.

    Object keys are sorted, array order is significant, insignificant
    whitespace is removed, and non-finite floats are rejected. Paths,
    timestamps, and labels are not stripped implicitly: callers must build an
    identity payload containing only durable identity inputs.
    """

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def content_identifier(kind: str, payload: JsonValue) -> str:
    """Return a namespaced SHA-256 identifier for a canonical payload."""

    allowed_characters = "abcdefghijklmnopqrstuvwxyz0123456789-"
    if not kind or any(character not in allowed_characters for character in kind):
        raise ValueError(
            "identity kind must contain only lowercase letters, digits, and hyphens"
        )
    digest = hashlib.sha256(canonical_json(payload)).hexdigest()
    return f"{kind}-sha256-{digest}"
