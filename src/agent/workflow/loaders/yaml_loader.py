"""
Phase 5.5 — YAML Workflow Definition Loader
============================================

Reads a declarative ``workflows.yaml`` file (or individual workflow YAML
files) and returns validated ``WorkflowDefinition`` instances.

Usage::

    from src.agent.workflow.loaders.yaml_loader import load_workflow

    defn = load_workflow("config/workflows/demo_chat.yaml")
    registry.register(defn)
"""

from __future__ import annotations

import yaml

from src.agent.workflow.workflow_definition import WorkflowDefinition


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_workflow(path: str) -> WorkflowDefinition:
    """Load a single workflow definition from a YAML file.

    Parameters
    ----------
    path:
        Filesystem path to the YAML workflow file.

    Returns
    -------
    WorkflowDefinition:
        A fully validated, graph-checked workflow definition.

    Raises
    ------
    FileNotFoundError:
        *path* does not exist.
    yaml.YAMLError:
        *path* is not valid YAML.
    ValueError | pydantic.ValidationError:
        The definition failed validation or the graph has errors.
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise ValueError(
            f"workflow file {path!r} must contain a top-level mapping"
        )

    return WorkflowDefinition.model_validate(data)


def load_workflow_from_string(yaml_str: str) -> WorkflowDefinition:
    """Load a workflow definition from a YAML string (for testing)."""
    data = yaml.safe_load(yaml_str)
    if not isinstance(data, dict):
        raise ValueError("YAML string must contain a top-level mapping")
    return WorkflowDefinition.model_validate(data)
