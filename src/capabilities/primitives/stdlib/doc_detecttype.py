"""stdlib.doc.detecttype — Detect document type from a file path or content (Phase 3.18.7)."""

from __future__ import annotations

import mimetypes
import os
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class DocDetectTypePrimitive(PrimitiveBase):
    """Detect the document type from a file path or content snippet."""

    name = "stdlib.doc.detecttype"
    description = "Detect document type from a file path or content"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to detect the type of",
            },
        },
        "required": ["path"],
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
        if "path" not in args:
            raise ValueError("args must contain 'path' key")
        if not isinstance(args["path"], str):
            raise ValueError(f"args['path'] must be a string, got {type(args['path']).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        path = args["path"]

        ext = os.path.splitext(path)[1].lower() if "." in os.path.basename(path) else ""
        mime_type, _ = mimetypes.guess_type(path)
        if mime_type is None:
            mime_type = "application/octet-stream"

        category_map = {
            ".txt": "text",
            ".md": "markdown",
            ".rst": "restructuredtext",
            ".csv": "csv",
            ".json": "json",
            ".xml": "xml",
            ".html": "html",
            ".htm": "html",
            ".css": "css",
            ".js": "javascript",
            ".ts": "typescript",
            ".py": "python",
            ".java": "java",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c_header",
            ".rs": "rust",
            ".go": "go",
            ".rb": "ruby",
            ".php": "php",
            ".sql": "sql",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".toml": "toml",
            ".ini": "ini",
            ".cfg": "config",
            ".log": "log",
            ".pdf": "pdf",
            ".doc": "word",
            ".docx": "word",
            ".xls": "excel",
            ".xlsx": "excel",
            ".ppt": "powerpoint",
            ".pptx": "powerpoint",
            ".png": "image",
            ".jpg": "image",
            ".jpeg": "image",
            ".gif": "image",
            ".svg": "image",
            ".bmp": "image",
            ".mp3": "audio",
            ".wav": "audio",
            ".mp4": "video",
            ".zip": "archive",
            ".tar": "archive",
            ".gz": "archive",
        }
        category = category_map.get(ext, "unknown")

        return PrimitiveResult(
            status="success",
            data={
                "extension": ext,
                "mime_type": mime_type,
                "category": category,
                "is_binary": mime_type not in (
                    "text/plain", "text/html", "text/css", "text/javascript",
                    "application/json", "application/xml", "text/xml",
                    "text/csv", "text/markdown", "text/yaml",
                ) and "text/" not in (mime_type or ""),
            },
        )
