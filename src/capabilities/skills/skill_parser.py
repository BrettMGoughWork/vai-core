from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from src.capabilities.primitives.base import PrimitiveBase
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry


def parse_skill_file(path: str, registry: PrimitiveRegistry) -> dict[str, Any]:
    """Parse a .skill.md file, validate it, and resolve primitive references.

    Args:
        path: Path to a ``.skill.md`` file.
        registry: A ``PrimitiveRegistry`` used to resolve primitive names.

    Returns:
        A dict with keys ``name``, ``description``, ``inputs``, ``outputs``,
        and ``primitives`` (a list of resolved ``PrimitiveBase`` instances).

    Raises:
        ValueError: If the file is missing, has invalid YAML, is missing
                    required fields, or references an unknown primitive.
    """
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    yaml_text = _extract_front_matter(text, path)

    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid skill manifest in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"invalid skill manifest in {path}: YAML must be a mapping, got {type(data).__name__}")

    _validate_required_fields(data, path)
    resolved = _resolve_primitives(data["primitives"], registry, path)

    return {
        "name": data["name"],
        "description": data["description"],
        "inputs": data["inputs"],
        "outputs": data["outputs"],
        "primitives": resolved,
        "steps": data.get("steps", []),
    }


def parse_skill_text(text: str, registry: PrimitiveRegistry) -> dict[str, Any]:
    """Parse raw ``.skill.md`` content from a string (no file I/O).

    This is the in-memory equivalent of ``parse_skill_file`` — it accepts
    the full text of a ``.skill.md`` document rather than a file path.
    Used by the agent-authored skill pipeline (PHASE 3.16).

    Args:
        text: Full content of a ``.skill.md`` file as a string.
        registry: A ``PrimitiveRegistry`` used to resolve primitive names.

    Returns:
        A dict with keys ``name``, ``description``, ``inputs``, ``outputs``,
        ``steps``, and ``primitives`` (a list of resolved ``PrimitiveBase`` instances).

    Raises:
        ValueError: If the text has invalid YAML front-matter, is missing
                    required fields, or references an unknown primitive.
    """
    source = "<agent-authored>"
    yaml_text = _extract_front_matter(text, source)

    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid skill manifest: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"invalid skill manifest: YAML must be a mapping, got {type(data).__name__}"
        )

    _validate_required_fields(data, source)
    resolved = _resolve_primitives(data["primitives"], registry, source)

    return {
        "name": data["name"],
        "description": data["description"],
        "inputs": data["inputs"],
        "outputs": data["outputs"],
        "primitives": resolved,
        "steps": data.get("steps", []),
    }


def parse_skill_directory(directory: str, registry: PrimitiveRegistry) -> list[dict[str, Any]]:
    """Scan *directory* for ``.skill.md`` files and parse each one.

    Args:
        directory: Path to a directory containing ``.skill.md`` files.
        registry: A ``PrimitiveRegistry`` used to resolve primitive names.

    Returns:
        A list of parsed skill dicts.  Files that cannot be read or parsed
        are silently skipped.
    """
    if not os.path.isdir(directory):
        return []

    skills: list[dict[str, Any]] = []
    for entry in os.scandir(directory):
        if not entry.is_file():
            continue
        if not entry.name.endswith(".skill.md"):
            continue
        try:
            skills.append(parse_skill_file(entry.path, registry))
        except (ValueError, OSError):
            continue

    return skills


# ------------------------------------------------------------------ helpers --


def _extract_front_matter(text: str, source: str) -> str:
    """Extract the YAML block between ``---`` delimiters."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"invalid skill manifest in {source}: missing opening --- delimiter")

    end_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        raise ValueError(f"invalid skill manifest in {source}: missing closing --- delimiter")

    return "\n".join(lines[1:end_idx])


def _validate_required_fields(data: dict[str, Any], source: str) -> None:
    """Validate that *data* contains all required skill fields with correct types."""
    for key, expected_type in (
        ("name", str),
        ("description", str),
        ("inputs", dict),
        ("outputs", dict),
        ("primitives", list),
    ):
        if key not in data:
            raise ValueError(f"invalid skill manifest in {source}: missing required key '{key}'")
        if not isinstance(data[key], expected_type):
            raise ValueError(
                f"invalid skill manifest in {source}: '{key}' must be {expected_type.__name__}, "
                f"got {type(data[key]).__name__}"
            )

    # Each primitive name must be a string.
    for idx, pn in enumerate(data["primitives"]):
        if not isinstance(pn, str):
            raise ValueError(
                f"invalid skill manifest in {source}: primitives[{idx}] must be str, "
                f"got {type(pn).__name__}"
            )


def _resolve_primitives(
    names: list[str], registry: PrimitiveRegistry, source: str
) -> list[PrimitiveBase]:
    """Resolve each name in *names* against *registry*.

    Args:
        names: List of primitive names (strings).
        registry: The ``PrimitiveRegistry`` to query.
        source: Label for error messages.

    Returns:
        List of ``PrimitiveBase`` instances in the same order as *names*.

    Raises:
        ValueError: If any name is not found in the registry.
    """
    resolved: list[PrimitiveBase] = []
    for name in names:
        primitive = registry.get(name)
        if primitive is None:
            raise ValueError(f"unknown primitive: {name} (in {source})")
        resolved.append(primitive)
    return resolved
