"""
Phase 5.5 — Declarative Workflow Loader (YAML)
===============================================

Scans ``config/workflows/*.yaml`` at startup and deserialises each file
into a validated ``WorkflowDefinition`` via Pydantic.

Usage::

    from src.agent.workflow.loader import load_workflows_from_yaml

    definitions = load_workflows_from_yaml("config/workflows")
    for defn in definitions:
        registry.register(defn)
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import yaml

from src.agent.workflow.workflow_definition import WorkflowDefinition


def load_workflows_from_yaml(directory: str | Path) -> List[WorkflowDefinition]:
    """Scan *directory* for ``*.yaml`` / ``*.yml`` files and return a list
    of validated ``WorkflowDefinition`` instances.

    Skips non-existent directories and files that fail to parse or validate
    (printing warnings to stderr so the user knows a workflow was skipped).
    """
    root = Path(directory)
    if not root.is_dir():
        return []

    found: List[WorkflowDefinition] = []
    for yaml_path in sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml")):
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            if not isinstance(raw, dict):
                print(f"[workflow-loader] skipping {yaml_path.name}: not a mapping")
                continue
            defn = WorkflowDefinition.model_validate(raw)
            found.append(defn)
        except Exception as exc:
            print(
                f"[workflow-loader] skipping {yaml_path.name}: {exc}"
            )
    return found
