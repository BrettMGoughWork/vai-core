"""stdlib.zip.create — Create a zip archive (Phase 3.18.10)."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


class ZipCreatePrimitive(PrimitiveBase):
    """Create a zip archive from files or directories."""

    name = "stdlib.zip.create"
    description = "Create a zip archive"
    primitive_type = PrimitiveType.PYTHON

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
        if "sources" not in args:
            raise ValueError("args must contain 'sources' key")
        if not isinstance(args["sources"], list):
            raise ValueError(f"args['sources'] must be a list, got {type(args['sources']).__name__}")
        for source in args["sources"]:
            if not isinstance(source, str):
                raise ValueError(f"args['sources'] items must be strings, got {type(source).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        archive = Path(args["archive"])
        sources = [Path(s) for s in args["sources"]]

        # Verify all sources exist
        missing = [str(s) for s in sources if not s.exists()]
        if missing:
            return PrimitiveResult(
                status="error",
                error=f"Source paths not found: {missing}",
            )

        try:
            archive.parent.mkdir(parents=True, exist_ok=True)
            file_count = 0
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                for source in sources:
                    if source.is_file():
                        zf.write(source, source.name)
                        file_count += 1
                    elif source.is_dir():
                        for root, _, files in os.walk(source):
                            for file in files:
                                file_path = Path(root) / file
                                arcname = file_path.relative_to(source.parent)
                                zf.write(file_path, arcname)
                                file_count += 1

            return PrimitiveResult(
                status="success",
                data={
                    "archive": str(archive.resolve()),
                    "files_added": file_count,
                    "size_bytes": archive.stat().st_size,
                },
            )
        except Exception as e:
            # Clean up partial archive on failure
            if archive.exists():
                archive.unlink(missing_ok=True)
            return PrimitiveResult(
                status="error",
                error=f"Failed to create archive: {e}",
            )
