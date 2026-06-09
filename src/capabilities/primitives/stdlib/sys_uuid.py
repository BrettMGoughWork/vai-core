"""stdlib.sys.uuid — Generate a UUID (Phase 3.18.8)."""

from __future__ import annotations

import uuid
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


class SysUUIDPrimitive(PrimitiveBase):
    """Generate a UUID (v4 by default, v1/v3/v5 supported)."""

    name = "stdlib.sys.uuid"
    description = "Generate a UUID"
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
        version = args.get("version", 4)
        if not isinstance(version, int):
            raise ValueError(f"args['version'] must be an integer, got {type(version).__name__}")
        if version not in (1, 3, 4, 5):
            raise ValueError(f"args['version'] must be 1, 3, 4, or 5, got {version}")
        fmt = args.get("format", "standard")
        if fmt not in ("standard", "hex", "urn", "bytes"):
            raise ValueError(f"args['format'] must be 'standard', 'hex', 'urn', or 'bytes', got {fmt}")
        if version in (3, 5):
            if "namespace" not in args or "name" not in args:
                raise ValueError("args must contain 'namespace' and 'name' for UUID v3/v5")
            if not isinstance(args["namespace"], str):
                raise ValueError(f"args['namespace'] must be a string, got {type(args['namespace']).__name__}")
            if not isinstance(args["name"], str):
                raise ValueError(f"args['name'] must be a string, got {type(args['name']).__name__}")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        version = args.get("version", 4)
        fmt = args.get("format", "standard")

        if version == 1:
            uid = uuid.uuid1()
        elif version == 3:
            namespace = uuid.UUID(args["namespace"])
            uid = uuid.uuid3(namespace, args["name"])
        elif version == 5:
            namespace = uuid.UUID(args["namespace"])
            uid = uuid.uuid5(namespace, args["name"])
        else:
            uid = uuid.uuid4()

        if fmt == "hex":
            value = uid.hex
        elif fmt == "urn":
            value = uid.urn
        elif fmt == "bytes":
            value = uid.bytes.hex()
        else:
            value = str(uid)

        return PrimitiveResult(
            status="success",
            data={"uuid": value, "version": version, "format": fmt},
        )
