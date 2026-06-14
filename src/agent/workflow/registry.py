"""
Phase 5.5 — Workflow Registry
==============================

In-memory registry of workflow definitions.  Populated at startup by
loading YAML definitions.  Provides discovery by workflow_id and by
event trigger type.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.agent.workflow.workflow_definition import WorkflowDefinition


class WorkflowRegistryError(Exception):
    """Base error for workflow registry operations."""


class DuplicateWorkflowError(WorkflowRegistryError):
    """Raised when registering a workflow with a duplicate ID."""


class WorkflowNotFoundError(WorkflowRegistryError):
    """Raised when a lookup by workflow_id fails."""


class WorkflowRegistry:
    """In-memory registry of workflow definitions.

    Populated at startup from YAML files.  After startup the registry
    is read-only — no mutation, no dynamic registration.
    """

    def __init__(self) -> None:
        self._definitions: Dict[str, WorkflowDefinition] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, defn: WorkflowDefinition) -> None:
        """Register a workflow definition.

        Raises ``DuplicateWorkflowError`` if the workflow_id is
        already registered with a different definition.  Idempotent
        if the same definition is registered twice.
        """
        if not isinstance(defn, WorkflowDefinition):
            raise TypeError("defn must be a WorkflowDefinition instance")

        existing = self._definitions.get(defn.workflow_id)
        if existing is not None:
            if existing == defn:
                return
            raise DuplicateWorkflowError(
                f"workflow {defn.workflow_id!r} already registered"
            )

        self._definitions[defn.workflow_id] = defn

    # ------------------------------------------------------------------
    # Discovery (read-only)
    # ------------------------------------------------------------------

    def get(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        """Look up a workflow by its ID.

        Returns ``None`` if the workflow does not exist.
        """
        return self._definitions.get(workflow_id)

    def list(self) -> List[WorkflowDefinition]:
        """Return all registered workflow definitions."""
        return list(self._definitions.values())

    def find_by_trigger(self, event_type: str) -> List[WorkflowDefinition]:
        """Find all workflows that trigger on *event_type*."""
        return [
            defn
            for defn in self._definitions.values()
            if event_type in defn.trigger_on
        ]

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def workflow_count(self) -> int:
        """Number of registered workflow definitions."""
        return len(self._definitions)

    def has_workflow(self, workflow_id: str) -> bool:
        """Check whether a workflow ID is registered."""
        return workflow_id in self._definitions
