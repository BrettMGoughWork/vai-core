"""CLI primitive loader — loads CLIPrimitive instances from configuration."""

from __future__ import annotations

from typing import Any, Dict, List

from src.capabilities.primitives.base import PrimitiveBase


class CLILoader:
    """Loads CLIPrimitive instances from configuration or discovery."""

    @staticmethod
    def load_from_config(config: Dict[str, Any]) -> List[PrimitiveBase]:
        """Create CLIPrimitive instances from configuration dictionaries.

        Each entry should have: name, description, command, and optionally
        input_schema, side_effects, timeout_ms.
        """
        from src.capabilities.primitives.cli import CLIPrimitive

        primitives: List[PrimitiveBase] = []
        if isinstance(config, list):
            entries = config
        else:
            entries = config.get("cli_primitives", [])
        for entry in entries:
            prim = CLIPrimitive(
                name=entry["name"],
                description=entry["description"],
                command=entry["command"],
                input_schema=entry.get("input_schema"),
                side_effects=entry.get("side_effects"),
                timeout_ms=entry.get("timeout_ms"),
            )
            primitives.append(prim)
        return primitives


__all__ = ["CLILoader"]
