"""update_metadata primitive — writes sprint stage metadata to disk."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.domain.primitives import PrimitiveBase, PrimitiveResult, PrimitiveType


_PROJECTS_ROOT = Path(os.environ.get("DEVSQUAD_PROJECTS_ROOT", "/projects"))


class UpdateMetadataPrimitive(PrimitiveBase):
    """Write stage metadata to the sprint project directory.

    Each DevSquad workflow stage (bootstrap, architecture, etc.) should
    record its outcome metadata so downstream stages and the HITL client
    can inspect progress.

    Accepts ``project_dir`` (preferred) or ``project_id`` (resolved as
    ``/projects/{project_id}``), and either ``data`` (full dict) or
    ``status`` (shorthand string), along with ``stage``.
    """

    name = "stdlib.update_metadata"
    description = (
        "Write stage metadata to '{project_dir}/metadata/{stage}.json'. "
        "Accepts 'project_id' or 'project_dir' (str), 'stage' (str), "
        "and 'data' (dict) or 'status' (str)."
    )
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "project_dir": {
                "type": "string",
                "description": "Absolute path to the project directory",
            },
            "project_id": {
                "type": "string",
                "description": "Project identifier (resolved as /projects/{project_id})",
            },
            "stage": {
                "type": "string",
                "description": "Stage identifier (e.g. 'bootstrap', 'architecture')",
            },
            "data": {
                "type": "object",
                "description": "Arbitrary metadata payload for the stage",
            },
            "status": {
                "type": "string",
                "description": "Shorthand for data={'status': status}",
            },
        },
        "required": ["stage"],
    }

    def __init__(self) -> None:
        super().__init__(
            name=self.name,
            description=self.description,
            primitive_type=self.primitive_type,
        )

    def _normalize_args(self, args: dict) -> dict:
        """Resolve flexible args to canonical (project_dir, stage, data)."""
        # ── project_dir ────────────────────────────────────────────────
        if "project_dir" in args:
            project_dir = args["project_dir"]
        elif "project_id" in args:
            project_dir = str(_PROJECTS_ROOT / args["project_id"])
        else:
            raise ValueError(
                "args must contain either 'project_dir' or 'project_id'"
            )

        # ── data ───────────────────────────────────────────────────────
        if "data" in args:
            data = args["data"]
        elif "status" in args:
            data = {"status": args["status"]}
        else:
            raise ValueError(
                "args must contain either 'data' or 'status'"
            )

        return {
            "project_dir": project_dir,
            "stage": args["stage"],
            "data": data,
        }

    def validate_args(self, args: dict) -> None:
        if not isinstance(args, dict):
            raise ValueError(f"args must be a dict, got {type(args).__name__}")
        if "stage" not in args:
            raise ValueError("args must contain 'stage' key")
        if not isinstance(args["stage"], str):
            raise ValueError(
                f"'stage' must be a string, got {type(args['stage']).__name__}"
            )
        has_dir = "project_dir" in args or "project_id" in args
        has_data = "data" in args or "status" in args
        if not has_dir:
            raise ValueError(
                "args must contain either 'project_dir' or 'project_id'"
            )
        if not has_data:
            raise ValueError(
                "args must contain either 'data' or 'status'"
            )

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)

        normalized = self._normalize_args(args)

        project_dir = Path(normalized["project_dir"])
        stage = normalized["stage"]
        data = normalized["data"]

        try:
            metadata_dir = project_dir / "metadata"
            metadata_dir.mkdir(parents=True, exist_ok=True)

            out_path = metadata_dir / f"{stage}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)

            return PrimitiveResult(
                status="success",
                data={"path": str(out_path)},
            )
        except Exception as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"UpdateMetadataError: {exc}",
            )
