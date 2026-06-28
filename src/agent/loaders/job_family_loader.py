"""
Job Family Definition + YAML Loader
====================================

Scans ``config/job-families/*.yaml`` at startup and registers each
definition into a ``JobFamilyRegistry``.  Job families describe the
relationship between agents, events, and retry/timeout policies for
DevSquad sprint stages.

Usage::

    from src.agent.loaders.job_family_loader import (
        JobFamilyDefinition,
        JobFamilyRegistry,
        load_job_families_from_yaml,
    )

    registry = JobFamilyRegistry()
    count = load_job_families_from_yaml(registry, "config/job-families")
    family = registry.get("job-family-pm")
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import yaml

from pydantic import BaseModel, Field


class JobFamilyDefinition(BaseModel):
    """A DevSquad job family definition loaded from YAML.

    Maps a job role (PM, Architect, Engineer, etc.) to its agent,
    trigger/completion events, and resilience policies.
    """

    job_family_id: str
    agent_id: Optional[str] = None
    agent_ids: Optional[List[str]] = None
    description: str = ""
    trigger_events: List[str] = Field(default_factory=list)
    completion_events: List[str] = Field(default_factory=list)
    max_retries: int = 0
    timeout_seconds: int = 3600
    use_council: bool = False
    council_id: Optional[str] = None
    requires_human_input: bool = False

    @property
    def resolved_agent_ids(self) -> List[str]:
        """Return all agent IDs this job family targets."""
        result: list[str] = []
        if self.agent_id:
            result.append(self.agent_id)
        if self.agent_ids:
            result.extend(self.agent_ids)
        return result


class JobFamilyRegistry:
    """In-memory registry for job family definitions.

    Populated at startup from ``config/job-families/*.yaml``.
    """

    def __init__(self) -> None:
        self._families: dict[str, JobFamilyDefinition] = {}

    def register(self, family: JobFamilyDefinition) -> None:
        """Register a job family.

        Raises:
            ValueError: If ``family.job_family_id`` is already registered.
        """
        fid = family.job_family_id
        if fid in self._families:
            raise ValueError(f"Job family '{fid}' is already registered")
        self._families[fid] = family

    def get(self, job_family_id: str) -> JobFamilyDefinition | None:
        """Return the family registered under *job_family_id*, or *None*."""
        return self._families.get(job_family_id)

    def list(self) -> list[JobFamilyDefinition]:
        """Return all registered job families."""
        return list(self._families.values())

    def find_by_agent(self, agent_id: str) -> list[JobFamilyDefinition]:
        """Return all job families that target *agent_id*."""
        return [
            f for f in self._families.values()
            if agent_id in f.resolved_agent_ids
        ]

    def find_by_trigger(self, event_type: str) -> list[JobFamilyDefinition]:
        """Return all job families triggered by *event_type*."""
        return [
            f for f in self._families.values()
            if event_type in f.trigger_events
        ]

    @property
    def count(self) -> int:
        """Number of registered job families."""
        return len(self._families)


# ---------------------------------------------------------------------------
# YAML Loader
# ---------------------------------------------------------------------------


def load_job_families_from_yaml(
    registry: JobFamilyRegistry,
    directory: str | Path,
) -> int:
    """Scan *directory* for ``*.yaml`` / ``*.yml`` job family files.

    Files should contain a top-level ``job_families`` list, each entry
    being a ``JobFamilyDefinition``.  Files that fail to parse are
    skipped with a warning printed to stderr.

    Returns the count of successfully registered families.
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
                print(f"[job-family-loader] skipping {yaml_path.name}: not a mapping")
                continue

            families_raw = raw.get("job_families")
            if not isinstance(families_raw, list):
                print(
                    f"[job-family-loader] skipping {yaml_path.name}: "
                    f"missing 'job_families' list"
                )
                continue

            for entry in families_raw:
                if not isinstance(entry, dict):
                    print(
                        f"[job-family-loader] skipping entry in {yaml_path.name}: "
                        f"not a mapping"
                    )
                    continue
                family = JobFamilyDefinition.model_validate(entry)
                registry.register(family)
                count += 1

        except Exception as exc:
            import sys
            print(
                f"[job-family-loader] skipping {yaml_path.name}: {exc}",
                file=sys.stderr,
            )

    return count
