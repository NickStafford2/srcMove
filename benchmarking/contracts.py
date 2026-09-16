"""Shared vocabulary for persisted benchmark records."""

from __future__ import annotations

from enum import StrEnum


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
