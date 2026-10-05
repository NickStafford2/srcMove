"""Content-addressed, author-reviewed corrections to inherited clone labels."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from bigMoveBench.categories import normalize_reported_category

REGISTRY_PATH = Path(__file__).with_name("reviewed_label_corrections.json")


class LabelCorrections:
    """An immutable-at-load snapshot used for an entire execution run."""

    def __init__(self, path: Path = REGISTRY_PATH) -> None:
        contents = path.read_bytes()
        registry = json.loads(contents)
        if (
            not isinstance(registry, dict)
            or registry.get("schema_version") != 1
            or registry.get("pair_policy") != "unordered_exact_utf8_sha256"
            or not isinstance(registry.get("corrections"), list)
        ):
            raise ValueError("unsupported reviewed-label correction registry")
        self.identity = {
            "schema_version": 1,
            "sha256": hashlib.sha256(contents).hexdigest(),
            "snapshot": registry,
        }
        self._entries: dict[tuple[str, str], dict[str, Any]] = {}
        ids: set[str] = set()
        for entry in registry["corrections"]:
            if not isinstance(entry, dict):
                raise ValueError("invalid reviewed-label correction")
            hashes = entry.get("fragment_sha256", [])
            if (
                not isinstance(hashes, list)
                or len(hashes) != 2
                or not all(
                    isinstance(h, str)
                    and len(h) == 64
                    and all(c in "0123456789abcdef" for c in h)
                    for h in hashes
                )
                or entry.get("original_match_kind") not in ("type1", "type2", "type2b", "type2c", "type3")
                or entry.get("reviewed_match_kind") not in ("type1", "type2", "type2b", "type2c", "type3")
                or not isinstance(entry.get("id"), str)
                or not entry["id"]
                or not isinstance(entry.get("reason"), str)
                or not entry["reason"]
            ):
                raise ValueError("invalid reviewed-label correction")
            key = tuple(sorted(hashes))
            if key in self._entries or entry["id"] in ids:
                raise ValueError("duplicate reviewed-label correction")
            ids.add(entry["id"])
            self._entries[key] = entry

    def match(self, metadata: Mapping[str, Any]) -> dict[str, Any] | None:
        if metadata.get("case_kind") == "known_false_positive":
            return None
        hashes = []
        for side in ("fragment_one", "fragment_two"):
            fragment = metadata.get(side)
            if not isinstance(fragment, dict) or not isinstance(fragment.get("text"), str):
                return None
            digest = hashlib.sha256(fragment["text"].encode("utf-8")).hexdigest()
            if fragment.get("sha256") not in (None, digest):
                raise ValueError(f"{side} content does not match its SHA-256")
            hashes.append(digest)
        entry = self._entries.get(tuple(sorted(hashes)))
        if (
            entry is None
            or normalize_reported_category(entry["original_match_kind"]) != normalize_reported_category(
                metadata.get("benchmark_category", f"type{metadata.get('syntactic_type')}")
            )
        ):
            if entry is not None and metadata.get("category_rules_version") is not None:
                raise ValueError("reviewed correction conflicts with inherited benchmark category; explicit review required")
            return None
        # Return a separate object so callers cannot mutate the run snapshot.
        return json.loads(json.dumps(entry))
