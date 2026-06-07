"""
Skill manifest spec (Phase 3.0.3).

Parses .skill.md files with YAML front matter and Markdown body.

A .skill.md file has this shape:
---
skill: file.read
description: Read a file from disk
primitives:
  - file.read
inputs:
  type: object
  properties:
    path:
      type: string
      description: Path to the file
  required: [path]
steps:
  - call: file.read
    with:
      path: "{{inputs.path}}"
---

# file.read

Human-readable description and usage notes go here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


# YAML front matter regex: matches content between --- delimiters
_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class SkillManifest:
    """Parsed representation of a .skill.md file."""

    name: str
    """Skill name (from YAML front matter 'skill' key)."""

    description: str
    """Short description (from YAML front matter 'description' key)."""

    primitives: List[str] = field(default_factory=list)
    """List of primitive names this skill depends on."""

    inputs: Dict[str, Any] = field(default_factory=dict)
    """JSON Schema for the skill's input arguments."""

    steps: List[Dict[str, Any]] = field(default_factory=list)
    """Ordered list of execution steps (call: primitive refs)."""

    body: str = ""
    """Human-readable Markdown body."""

    @classmethod
    def from_file(cls, path: Path | str) -> "SkillManifest":
        """
        Parse a .skill.md file into a SkillManifest.

        Args:
            path: Path to a .skill.md file.

        Returns:
            SkillManifest instance.

        Raises:
            FileNotFoundError: If the file doesn't exist.
            ValueError: If the file has no YAML front matter or is malformed.
        """
        path = Path(path)
        content = path.read_text(encoding="utf-8")

        return cls.from_text(content, source=str(path))

    @classmethod
    def from_text(cls, text: str, source: str = "<string>") -> "SkillManifest":
        """
        Parse .skill.md text into a SkillManifest.

        Args:
            text: Full text of the .skill.md file.
            source: Label for error messages (e.g. filename).

        Returns:
            SkillManifest instance.

        Raises:
            ValueError: If no YAML front matter is found or if required keys are missing.
        """
        match = _FRONT_MATTER_RE.match(text)
        if not match:
            raise ValueError(
                f"No YAML front matter found in {source}. "
                f"Expected --- delimited block at the top of the file."
            )

        front_matter_text = match.group(1)
        body = text[match.end():].strip()

        try:
            front_matter = yaml.safe_load(front_matter_text)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML front matter in {source}: {exc}") from exc

        if not isinstance(front_matter, dict):
            raise ValueError(
                f"YAML front matter in {source} must be a mapping, "
                f"got {type(front_matter).__name__}"
            )

        if "skill" not in front_matter:
            raise ValueError(f"Missing required key 'skill' in {source} front matter")

        if "description" not in front_matter:
            raise ValueError(f"Missing required key 'description' in {source} front matter")

        return cls(
            name=front_matter["skill"],
            description=front_matter["description"],
            primitives=front_matter.get("primitives", []),
            inputs=front_matter.get("inputs", {}),
            steps=front_matter.get("steps", []),
            body=body,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the manifest back to a dictionary (for LLM consumption)."""
        return {
            "name": self.name,
            "description": self.description,
            "primitives": self.primitives,
            "inputs": self.inputs,
            "steps": self.steps,
            "body": self.body,
        }
