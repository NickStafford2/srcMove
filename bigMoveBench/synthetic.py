"""Build the synthetic two-file move used by BigMoveBench inputs."""

from __future__ import annotations

from pathlib import Path


SYNTHETIC_SOURCE_PATH = Path("source/input.java")
SYNTHETIC_DESTINATION_PATH = Path("destination/input.java")
STABLE_WRAPPER_VERSION = 1
STABLE_SOURCE_ROLE = "source"
STABLE_DESTINATION_ROLE = "destination"
STABLE_ROLES = (STABLE_SOURCE_ROLE, STABLE_DESTINATION_ROLE)


def indent_fragment(fragment: str) -> str:
    """Indent a BigCloneBench fragment for insertion into a class body."""

    return (
        "\n".join(f"  {line}" if line else "" for line in fragment.splitlines())
        + "\n"
    )


def _append_block(lines: list[str], block: str) -> tuple[int, int]:
    block_lines = block.rstrip("\n").splitlines()
    start_line = len(lines) + 1
    lines.extend(block_lines)
    return start_line, len(lines)


def _build_archive_unit(
    class_name: str,
    context_name: str,
    context_value: int,
    fragment: str | None,
) -> tuple[str, tuple[int, int] | None]:
    lines: list[str] = []
    _append_block(
        lines,
        f"""class {class_name} {{
  private static final int {context_name} = {context_value};""",
    )
    fragment_range = _append_block(lines, fragment) if fragment is not None else None
    _append_block(lines, "}")
    return "\n".join(lines) + "\n", fragment_range


def build_stable_archive_unit(
    role: str, generated_fragment: str | None
) -> tuple[str, tuple[int, int] | None]:
    """Render one reusable source or destination wrapper object."""

    if role == STABLE_SOURCE_ROLE:
        return _build_archive_unit(
            "BigMoveBenchSource", "SOURCE_CONTEXT", 100, generated_fragment
        )
    if role == STABLE_DESTINATION_ROLE:
        return _build_archive_unit(
            "BigMoveBenchDestination",
            "DESTINATION_CONTEXT",
            200,
            generated_fragment,
        )
    raise ValueError(f"unsupported stable wrapper role: {role}")


def build_stable_synthetic_move_archive(
    generated_fragment1: str, generated_fragment2: str
) -> tuple[
    dict[Path, str],
    dict[Path, str],
    tuple[int, int],
    tuple[int, int],
]:
    """Build the normalized archive shape from reusable stable wrappers."""

    original_source, original_range = build_stable_archive_unit(
        STABLE_SOURCE_ROLE, generated_fragment1
    )
    modified_source, _ = build_stable_archive_unit(STABLE_SOURCE_ROLE, None)
    original_destination, _ = build_stable_archive_unit(
        STABLE_DESTINATION_ROLE, None
    )
    modified_destination, modified_range = build_stable_archive_unit(
        STABLE_DESTINATION_ROLE, generated_fragment2
    )
    assert original_range is not None
    assert modified_range is not None
    return (
        {
            SYNTHETIC_SOURCE_PATH: original_source,
            SYNTHETIC_DESTINATION_PATH: original_destination,
        },
        {
            SYNTHETIC_SOURCE_PATH: modified_source,
            SYNTHETIC_DESTINATION_PATH: modified_destination,
        },
        original_range,
        modified_range,
    )


def build_synthetic_move_archive(
    class_name: str, generated_fragment1: str, generated_fragment2: str
) -> tuple[
    dict[Path, str],
    dict[Path, str],
    tuple[int, int],
    tuple[int, int],
]:
    """Build one isolated two-file archive containing a cross-file move."""

    original_source, original_range = _build_archive_unit(
        f"{class_name}Source",
        "SOURCE_CONTEXT",
        100,
        generated_fragment1,
    )
    modified_source, _ = _build_archive_unit(
        f"{class_name}Source", "SOURCE_CONTEXT", 100, None
    )
    original_destination, _ = _build_archive_unit(
        f"{class_name}Destination", "DESTINATION_CONTEXT", 200, None
    )
    modified_destination, modified_range = _build_archive_unit(
        f"{class_name}Destination",
        "DESTINATION_CONTEXT",
        200,
        generated_fragment2,
    )
    assert original_range is not None
    assert modified_range is not None
    return (
        {
            SYNTHETIC_SOURCE_PATH: original_source,
            SYNTHETIC_DESTINATION_PATH: original_destination,
        },
        {
            SYNTHETIC_SOURCE_PATH: modified_source,
            SYNTHETIC_DESTINATION_PATH: modified_destination,
        },
        original_range,
        modified_range,
    )
