from __future__ import annotations
from typing import Dict, List, Optional

from src.capabilities.runtime.toolspec import ToolSpec

class SkillRegistry:
    """
    Global registry for all skills in the system.
    Skills register themselves via BaseSkill.__post_init__().
    """

    _skills: Dict[str, ToolSpec] = {}

    # ---------------------------------------------------------
    # Registration
    # ---------------------------------------------------------
    @classmethod
    def register(cls, skill) -> None:
        """
        Register a BaseSkill instance.
        """
        spec = skill.spec

        if spec.name in cls._skills:
            raise ValueError(f"Duplicate skill name: {spec.name}")

        cls._skills[spec.name] = spec

    # ---------------------------------------------------------
    # Lookup
    # ---------------------------------------------------------
    @classmethod
    def get(cls, name: str) -> ToolSpec:
        if name not in cls._skills:
            raise KeyError(f"Unknown skill: {name}")
        return cls._skills[name]

    @classmethod
    def get_spec(cls, name: str) -> Optional[ToolSpec]:
        return cls._skills.get(name)

    @classmethod
    def all(cls) -> List[ToolSpec]:
        return list(cls._skills.values())

    @classmethod
    def all_specs(cls) -> List[ToolSpec]:
        """
        Return only globally valid skills:
        - enabled
        - not hidden
        - not dev-only
        """
        return [
            spec
            for spec in cls._skills.values()
            if spec.enabled and not spec.hidden and not spec.dev_only
        ]
    
    @classmethod
    def all_specs_for_agent(cls, config):
        return [
            spec
            for spec in cls.all_specs()
            if spec.name in config.allowed_tools
            and spec.category in config.allowed_categories
            and spec.side_effects in config.allowed_side_effects
        ]

    # ---------------------------------------------------------
    # Filtering (used by agent policies)
    # ---------------------------------------------------------
    @classmethod
    def filter_by_category(cls, category: str) -> List[ToolSpec]:
        return [
            spec for spec in cls._skills.values()
            if spec.category == category
        ]

    @classmethod
    def filter_enabled(cls) -> List[ToolSpec]:
        return [
            spec for spec in cls._skills.values()
            if spec.enabled
        ]

    @classmethod
    def filter_allowed(cls, allowed: List[str]) -> List[ToolSpec]:
        """
        Used by agent definitions to restrict tool access.
        """
        return [
            spec for name, spec in cls._skills.items()
            if name in allowed
        ]