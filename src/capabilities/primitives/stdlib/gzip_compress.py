"""stdlib.gzip.compress — Gzip compress data (Phase 3.18.10)."""

from __future__ import annotations

import gzip
from pathlib import Path
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class GzipCompressPrimitive(PrimitiveBase):
    """Compress a file or data using gzip."""

    name = "stdlib.gzip.compress"
    description = "Gzip compress a file or string data"
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
        has_file = "file" in args
        has_data = "data" in args
        if not has_file and not has_data:
            raise ValueError("args must contain 'file' or 'data' key")
        if has_file:
            if not isinstance(args["file"], str):
                raise ValueError(f"args['file'] must be a string, got {type(args['file']).__name__}")
        if has_data:
            if not isinstance(args["data"], str):
                raise ValueError(f"args['data'] must be a string, got {type(args['data']).__name__}")
        if "output" in args and not isinstance(args["output"], str):
            raise ValueError(f"args['output'] must be a string, got {type(args['output']).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)

        try:
            if "file" in args:
                source = Path(args["file"])
                if not source.exists():
                    return PrimitiveResult(status="error", error=f"File not found: {source}")
                output_path = Path(args.get("output", str(source) + ".gz"))
                with open(source, "rb") as f_in:
                    with gzip.open(output_path, "wb") as f_out:
                        f_out.write(f_in.read())
                return PrimitiveResult(
                    status="success",
                    data={
                        "output": str(output_path.resolve()),
                        "original_size": source.stat().st_size,
                        "compressed_size": output_path.stat().st_size,
                    },
                )
            else:
                data = args["data"].encode("utf-8")
                compressed = gzip.compress(data)
                output_path = args.get("output")
                if output_path:
                    output_path = Path(output_path)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(output_path, "wb") as f:
                        f.write(compressed)
                    return PrimitiveResult(
                        status="success",
                        data={
                            "output": str(output_path.resolve()),
                            "original_size": len(data),
                            "compressed_size": len(compressed),
                        },
                    )
                else:
                    import base64
from src.strategy.types.validation import deadcode_ignore
                    return PrimitiveResult(
                        status="success",
                        data={
                            "compressed_base64": base64.b64encode(compressed).decode("ascii"),
                            "original_size": len(data),
                            "compressed_size": len(compressed),
                        },
                    )
        except Exception as e:
            return PrimitiveResult(
                status="error",
                error=f"Compression failed: {e}",
            )
