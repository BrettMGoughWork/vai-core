"""stdlib.zip.extract — Extract a zip archive (Phase 3.18.10)."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class ZipExtractPrimitive(PrimitiveBase):
    """Extract files from a zip archive to a directory."""

    name = "stdlib.zip.extract"
    description = "Extract a zip archive"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "archive": {
                "type": "string",
                "description": "Path to the zip archive to extract",
            },
            "destination": {
                "type": "string",
                "description": "Directory to extract files into (default: same directory as archive)",
            },
        },
        "required": ["archive"],
    }

    def __init__(self) -> None:
        super().__init__(
            name=self.name,
            description=self.description,
            primitive_type=self.primitive_type,
        )

    def validate_args(self, args: dict) -> None:
        if not isinstance(args, dict):
            raise ValueError(f"args must be a dict, got {type(args).__name__}")
        if "archive" not in args:
            raise ValueError("args must contain 'archive' key")
        if not isinstance(args["archive"], str):
            raise ValueError(f"args['archive'] must be a string, got {type(args['archive']).__name__}")
        if "destination" in args and not isinstance(args["destination"], str):
            raise ValueError(f"args['destination'] must be a string, got {type(args['destination']).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        archive = Path(args["archive"])
        destination = Path(args.get("destination", archive.parent))

        if not archive.exists():
            return PrimitiveResult(
                status="error",
                error=f"Archive not found: {archive}",
            )
        if not zipfile.is_zipfile(archive):
            return PrimitiveResult(
                status="error",
                error=f"Not a valid zip file: {archive}",
            )

        try:
            destination.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive, "r") as zf:
                members = zf.namelist()
                zf.extractall(destination)

            return PrimitiveResult(
                status="success",
                data={
                    "extracted_to": str(destination.resolve()),
                    "files_extracted": len(members),
                    "file_list": members[:50],
                    "total_files": len(members),
                },
            )
        except Exception as e:
            return PrimitiveResult(
                status="error",
                error=f"Failed to extract archive: {e}",
            )
