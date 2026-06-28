"""
Prompt Template Registry + YAML Loader
=======================================

Scans ``config/prompts/*.yaml`` at startup and registers each file as a
``PromptTemplate`` by its ``prompt_id``.  The registry is a simple
read-only dict that the workflow invoker can query at runtime when
resolving ``prompt_template`` references in step configs.

Usage::

    from src.agent.loaders.prompt_loader import (
        PromptTemplate,
        PromptRegistry,
        load_prompts_from_directory,
    )

    registry = PromptRegistry()
    count = load_prompts_from_directory(registry, "config/prompts")
    prompt = registry.get("pm-prd-generation")
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import yaml

from pydantic import BaseModel, Field


class PromptTemplate(BaseModel):
    """A declarative prompt template loaded from YAML.

    Each template belongs to one or more agents (``agent_id`` /
    ``agent_ids``) and carries a ``system_prompt`` and ``user_prompt``
    that may contain ``{placeholder}`` values for runtime interpolation.
    """

    prompt_id: str
    agent_id: Optional[str] = None
    agent_ids: Optional[List[str]] = None
    description: str = ""
    system_prompt: str = ""
    user_prompt: str = ""

    @property
    def resolved_agent_ids(self) -> List[str]:
        """Return all agent IDs this prompt targets."""
        result: list[str] = []
        if self.agent_id:
            result.append(self.agent_id)
        if self.agent_ids:
            result.extend(self.agent_ids)
        return result


class PromptRegistry:
    """In-memory registry for prompt templates.

    Populated at startup from ``config/prompts/*.yaml`` and read-only at
    runtime.  Mirrors the ``CouncilRegistry`` pattern.
    """

    def __init__(self) -> None:
        self._prompts: dict[str, PromptTemplate] = {}

    def register(self, prompt: PromptTemplate) -> None:
        """Register a prompt template.

        Raises:
            ValueError: If ``prompt.prompt_id`` is already registered.
        """
        pid = prompt.prompt_id
        if pid in self._prompts:
            raise ValueError(f"Prompt '{pid}' is already registered")
        self._prompts[pid] = prompt

    def get(self, prompt_id: str) -> PromptTemplate | None:
        """Return the prompt registered under *prompt_id*, or *None*."""
        return self._prompts.get(prompt_id)

    def list(self) -> list[PromptTemplate]:
        """Return all registered prompt templates."""
        return list(self._prompts.values())

    def find_by_agent(self, agent_id: str) -> list[PromptTemplate]:
        """Return all prompts that target *agent_id*."""
        return [
            p for p in self._prompts.values()
            if agent_id in p.resolved_agent_ids
        ]

    @property
    def count(self) -> int:
        """Number of registered prompt templates."""
        return len(self._prompts)


# ---------------------------------------------------------------------------
# YAML Loader
# ---------------------------------------------------------------------------


def load_prompts_from_directory(
    registry: PromptRegistry,
    directory: str | Path,
) -> int:
    """Scan *directory* for ``*.yaml`` / ``*.yml`` prompt template files.

    Each file should contain a single ``PromptTemplate`` definition (no
    wrapping key).  Files that fail to parse are skipped with a warning
    printed to stderr.

    Returns the count of successfully registered templates.
    """
    root = Path(directory)
    if not root.is_dir():
        return 0

    count = 0
    for yaml_path in sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml")):
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            if not isinstance(raw, dict):
                print(f"[prompt-loader] skipping {yaml_path.name}: not a mapping")
                continue
            prompt = PromptTemplate.model_validate(raw)
            registry.register(prompt)
            count += 1
        except Exception as exc:
            import sys
            print(
                f"[prompt-loader] skipping {yaml_path.name}: {exc}",
                file=sys.stderr,
            )

    return count
