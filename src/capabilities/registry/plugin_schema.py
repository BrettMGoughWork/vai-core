"""
Plugin manifest schema (Phase 3.14.1).

Defines the ``PluginManifest`` dataclass that validates a ``plugin.yml``
file and the ``PLUGIN_MANIFEST_SCHEMA`` JSON Schema for external validation.

A plugin bundles primitives, skills, and optional MCP servers into a
single distributable directory::

    plugins/my-plugin/
    ├── plugin.yml          # manifest
    ├── primitives/         # Python files with PrimitiveBase subclasses
    ├── skills/             # .skill.md files
    └── mcp/                # MCP server manifests (.json / .yaml)

Usage::

    from src.capabilities.registry.plugin_schema import PluginManifest
    manifest = PluginManifest.from_dict(yaml.safe_load(plugin_yml_text))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


PLUGIN_MANIFEST_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "PluginManifest",
    "description": "Schema for a vai-core plugin manifest (plugin.yml).",
    "type": "object",
    "required": ["name", "version", "description"],
    "properties": {
        "name": {
            "type": "string",
            "description": "Unique plugin identifier (e.g. 'my-plugin').",
            "minLength": 1,
        },
        "version": {
            "type": "string",
            "description": "Semantic version (e.g. '1.0.0').",
            "pattern": r"^\d+\.\d+\.\d+$",
        },
        "description": {
            "type": "string",
            "description": "Human-readable description of what this plugin provides.",
            "minLength": 1,
        },
        "author": {
            "type": "string",
            "description": "Author attribution (optional).",
        },
        "dependencies": {
            "type": "object",
            "description": "Plugin dependencies as {plugin_name: version_constraint}.",
            "additionalProperties": {"type": "string"},
        },
        "primitives": {
            "type": "array",
            "description": "Python files under primitives/ to load.",
            "items": {"type": "string"},
        },
        "skills": {
            "type": "array",
            "description": "Skill manifest files under skills/ to load.",
            "items": {"type": "string"},
        },
        "mcp_servers": {
           "type": "array",
           "description": "MCP server manifest files under mcp/ to load.",
           "items": {"type": "string"},
        },
    },
    "additionalProperties": False,
}


@dataclass
class PluginManifest:
    """Validated representation of a plugin.yml manifest."""

    name: str
    """Unique plugin identifier (e.g. ``'my-plugin'``)."""

    version: str
    """Semantic version string (e.g. ``'1.0.0'``)."""

    description: str
    """Human-readable description of what this plugin provides."""

    author: str = ""
    """Optional author attribution."""

    dependencies: dict[str, str] = field(default_factory=dict)
    """Plugin dependencies as ``{name: version_constraint}``."""

    primitives: list[str] = field(default_factory=list)
    """Python file names under the plugin's ``primitives/`` directory."""

    skills: list[str] = field(default_factory=list)
    """Skill file names under the plugin's ``skills/`` directory."""

    mcp_servers: list[str] = field(default_factory=list)
    """MCP server manifest file names under the plugin's ``mcp/`` directory."""

    def validate(self) -> None:
        """Validate all manifest fields.

        Raises:
            ValueError: If any required field is missing or has an invalid type.
        """
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("PluginManifest.name must be a non-empty str")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("PluginManifest.version must be a non-empty str")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("PluginManifest.description must be a non-empty str")
        if not isinstance(self.dependencies, dict):
            raise ValueError("PluginManifest.dependencies must be a dict")
        for k, v in self.dependencies.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValueError(
                    f"PluginManifest.dependencies['{k}']: "
                    f"both key and value must be str"
                )
        if not isinstance(self.primitives, list):
            raise ValueError("PluginManifest.primitives must be a list")
        if not all(isinstance(p, str) for p in self.primitives):
            raise ValueError("PluginManifest.primitives must be a list of str")
        if not isinstance(self.skills, list):
            raise ValueError("PluginManifest.skills must be a list")
        if not all(isinstance(s, str) for s in self.skills):
            raise ValueError("PluginManifest.skills must be a list of str")
        if not isinstance(self.mcp_servers, list):
            raise ValueError("PluginManifest.mcp_servers must be a list")
        if not all(isinstance(s, str) for s in self.mcp_servers):
            raise ValueError("PluginManifest.mcp_servers must be a list of str")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginManifest:
        """Construct and validate a PluginManifest from a parsed YAML dict.

        Args:
            data: Dict produced by parsing a ``plugin.yml`` file.

        Returns:
            A validated ``PluginManifest`` instance.

        Raises:
            ValueError: If *data* fails validation.
        """
        manifest = cls(
            name=data.get("name", ""),
            version=data.get("version", ""),
            description=data.get("description", ""),
            author=data.get("author", ""),
            dependencies=data.get("dependencies", {}),
            primitives=data.get("primitives", []),
            skills=data.get("skills", []),
            mcp_servers=data.get("mcp_servers", []),
        )
        manifest.validate()
        return manifest
