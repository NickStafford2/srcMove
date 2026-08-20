from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from repository_analysis.inputs import (
    AnalysisConfiguration,
    ExecutableObservation,
    FingerprintSchemaVersions,
    RepositoryIdentity,
    build_pair_work_items,
    canonical_json_bytes,
    canonical_pretty_json_bytes,
    freeze_analysis_inputs,
    load_frozen_manifest_bytes,
    observe_executable,
    pair_fingerprint,
    pair_fingerprint_bytes,
    verify_resume_inputs,
)


def executable(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    path.chmod(0o755)
    return path


class RepositoryAnalysisInputTests(unittest.TestCase):
    def test_configuration_is_frozen_in_semantic_canonical_form(self) -> None:
        configuration = AnalysisConfiguration(
            selected_directory="src/analysis/.",
            excluded_suffixes=(".PY", ".txt", ".py"),
            srcdiff_timeout_seconds=12,
            srcmove_timeout_seconds=3,
        )

        self.assertEqual(configuration.selected_directory, "src/analysis")
        self.assertEqual(configuration.excluded_suffixes, (".py", ".txt"))
        self.assertEqual(configuration.srcdiff_timeout_seconds, 12.0)
        self.assertEqual(configuration.record()["schema_version"], 1)

    def test_configuration_rejects_unsafe_or_ambiguous_values(self) -> None:
        invalid = (
            {"selected_directory": "../src"},
            {"excluded_suffixes": ("py",)},
            {"srcdiff_timeout_seconds": float("nan")},
            {"srcmove_timeout_seconds": True},
            {"source_encoding": ""},
        )
        for arguments in invalid:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                AnalysisConfiguration(**arguments)

    def test_executable_observation_resolves_and_hashes_one_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = executable(root / "tool-real", b"#!/bin/sh\nexit 0\n")
            alias = root / "tool"
            alias.symlink_to(target.name)

            observation = observe_executable(alias)

            self.assertEqual(observation.requested_path, alias)
            self.assertEqual(observation.resolved_path, target.resolve())
            self.assertEqual(observation.size_bytes, len(target.read_bytes()))
            self.assertEqual(
                observation.sha256, hashlib.sha256(target.read_bytes()).hexdigest()
            )

    def test_builder_preserves_native_object_ids_and_contiguous_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manifest = self._manifest(
                root,
                commits=("A" * 40, "b" * 64, "third-native-object-id"),
            )

            items = build_pair_work_items(manifest)

            self.assertEqual([item.sequence for item in items], [0, 1])
            self.assertEqual(items[0].old_commit, "A" * 40)
            self.assertEqual(items[0].new_commit, "b" * 64)
            self.assertEqual(items[1].old_commit, "b" * 64)
            self.assertEqual(items[1].new_commit, "third-native-object-id")
            self.assertEqual(items[0].repository, root.resolve())
            self.assertEqual(items[0].srcdiff, manifest.srcdiff.resolved_path)

    def test_fingerprint_is_deterministic_and_ignores_runtime_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first = self._manifest(root / "one")
            second = self._manifest(root / "two")

            first_items = build_pair_work_items(first)
            second_items = build_pair_work_items(second)
            for worker_count in (1, 4, 12):
                with self.subTest(worker_count=worker_count):
                    self.assertEqual(
                        [item.fingerprint for item in first_items],
                        [item.fingerprint for item in second_items],
                    )
            self.assertNotIn("worker", pair_fingerprint_bytes(first, "a", "b").decode())

    def test_fingerprint_changes_with_every_identity_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manifest = self._manifest(root)
            baseline = pair_fingerprint(manifest, "a", "b")
            changes = {
                "repository": replace(
                    manifest, repository_identity=RepositoryIdentity("other")
                ),
                "srcdiff": replace(
                    manifest,
                    srcdiff=replace(manifest.srcdiff, sha256="1" * 64),
                ),
                "srcmove": replace(
                    manifest,
                    srcmove=replace(manifest.srcmove, sha256="2" * 64),
                ),
                "schemas": replace(
                    manifest,
                    schema_versions=replace(
                        FingerprintSchemaVersions(), compact_pair=999
                    ),
                ),
            }
            for name, changed in changes.items():
                with self.subTest(name=name):
                    self.assertNotEqual(pair_fingerprint(changed, "a", "b"), baseline)
            configuration_changes = {
                "selected_directory": None,
                "excluded_suffixes": (".new",),
                "use_archive": False,
                "use_position": True,
                "source_encoding": "ISO-8859-1",
                "srcdiff_timeout_seconds": 10.0,
                "srcmove_timeout_seconds": 11.0,
            }
            for field, value in configuration_changes.items():
                with self.subTest(configuration_field=field):
                    changed = replace(
                        manifest,
                        configuration=replace(
                            manifest.configuration, **{field: value}
                        ),
                    )
                    self.assertNotEqual(
                        pair_fingerprint(changed, "a", "b"), baseline
                    )
            self.assertNotEqual(pair_fingerprint(manifest, "old", "b"), baseline)
            self.assertNotEqual(pair_fingerprint(manifest, "a", "new"), baseline)

    def test_same_executable_content_has_same_identity_and_drift_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first = self._manifest(root / "first", tool_content=b"same")
            second = self._manifest(root / "second", tool_content=b"same")
            drifted = self._manifest(root / "third", tool_content=b"changed")

            self.assertEqual(
                pair_fingerprint(first, "a", "b"),
                pair_fingerprint(second, "a", "b"),
            )
            self.assertNotEqual(
                pair_fingerprint(first, "a", "b"),
                pair_fingerprint(drifted, "a", "b"),
            )

    def test_canonical_json_is_independent_of_dictionary_order(self) -> None:
        left = {"outer": {"b": 2, "a": 1}, "value": 3}
        right = {"value": 3, "outer": {"a": 1, "b": 2}}

        self.assertEqual(canonical_json_bytes(left), canonical_json_bytes(right))
        self.assertEqual(
            hashlib.sha256(canonical_json_bytes(left)).hexdigest(),
            hashlib.sha256(canonical_json_bytes(right)).hexdigest(),
        )
        self.assertEqual(json.loads(canonical_json_bytes(left)), left)

    def test_manifest_is_versioned_and_contains_exact_frozen_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            manifest = self._manifest(Path(temporary_directory))
            record = json.loads(manifest.canonical_bytes())

            self.assertEqual(record["schema_version"], 4)
            self.assertEqual(record["commits"], ["a", "b", "c"])
            self.assertEqual(record["repository_identity"], {"value": "repo-id"})
            self.assertIn("configuration", record)
            self.assertIn("executables", record)
            self.assertIn("fingerprint_schema_versions", record)

    def test_manifest_loader_rejects_schema_and_json_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manifest = self._manifest(root / "repository")
            baseline = manifest.record()
            mutations = {
                "unknown": lambda value: value.update({"unknown": 1}),
                "missing": lambda value: value.pop("commits"),
                "wrong type": lambda value: value.update({"commits": "abc"}),
                "schema": lambda value: value.update({"schema_version": 999}),
                "duplicate commits": lambda value: value.update(
                    {"commits": ["a", "b", "a"]}
                ),
                "nested unknown": lambda value: value["configuration"].update(
                    {"unknown": True}
                ),
                "noncanonical suffixes": lambda value: value["configuration"].update(
                    {"excluded_suffixes": [".txt", ".txt"]}
                ),
            }
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    value = json.loads(json.dumps(baseline))
                    mutate(value)
                    with self.assertRaises(ValueError):
                        load_frozen_manifest_bytes(
                            canonical_pretty_json_bytes(value), context=name
                        )

            with self.assertRaisesRegex(ValueError, "unreadable"):
                load_frozen_manifest_bytes(b"{", context="malformed")

            with self.assertRaisesRegex(ValueError, "duplicate JSON field"):
                load_frozen_manifest_bytes(
                    b'{"schema_version":1,"schema_version":1}',
                    context="duplicate-field",
                )

    def test_resume_verification_rejects_input_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manifest = self._manifest(root / "frozen", tool_content=b"same")
            current_diff = observe_executable(
                executable(root / "current-diff", b"same")
            )
            current_move = observe_executable(
                executable(root / "current-move", b"same")
            )

            rebound = verify_resume_inputs(
                manifest,
                repository_identity=manifest.repository_identity,
                configuration=manifest.configuration,
                srcdiff=current_diff,
                srcmove=current_move,
            )
            self.assertEqual(
                build_pair_work_items(rebound)[0].srcdiff,
                current_diff.resolved_path,
            )

            cases = (
                {
                    "repository_identity": RepositoryIdentity("other"),
                    "configuration": manifest.configuration,
                    "srcdiff": current_diff,
                    "srcmove": current_move,
                },
                {
                    "repository_identity": manifest.repository_identity,
                    "configuration": replace(
                        manifest.configuration, use_position=True
                    ),
                    "srcdiff": current_diff,
                    "srcmove": current_move,
                },
                {
                    "repository_identity": manifest.repository_identity,
                    "configuration": manifest.configuration,
                    "srcdiff": observe_executable(
                        executable(root / "drifted-diff", b"changed")
                    ),
                    "srcmove": current_move,
                },
            )
            for arguments in cases:
                with self.subTest(arguments=arguments), self.assertRaisesRegex(
                    ValueError, "drift"
                ):
                    verify_resume_inputs(manifest, **arguments)

    def _manifest(
        self,
        root: Path,
        *,
        commits: tuple[str, ...] = ("a", "b", "c"),
        tool_content: bytes = b"tool-content",
    ):
        root.mkdir(parents=True, exist_ok=True)
        srcdiff = observe_executable(executable(root / "srcdiff", tool_content))
        srcmove = observe_executable(executable(root / "srcmove", tool_content))
        return freeze_analysis_inputs(
            repository=root,
            repository_identity=RepositoryIdentity("repo-id"),
            commits=commits,
            configuration=AnalysisConfiguration(
                selected_directory="src",
                excluded_suffixes=(".txt", ".PY"),
            ),
            srcdiff=srcdiff,
            srcmove=srcmove,
        )


if __name__ == "__main__":
    unittest.main()
