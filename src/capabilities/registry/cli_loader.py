"""CLI primitive loader — scans JSON/YAML definition files and registers CLIPrimitive instances."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any, Dict

import yaml

from src.capabilities.primitives.cli import CLIPrimitive

if TYPE_CHECKING:
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry


def load_cli_primitives(registry: PrimitiveRegistry, directory: str) -> None:
    """Scan *directory* for ``.json``, ``.yaml``, and ``.yml`` files defining
    CLI primitives, parse each valid definition, and register the resulting
    ``CLIPrimitive`` instances into *registry*.

    Each file must parse to a dict containing the required keys:
        ``name``, ``description``, ``command``.
    """

    REQUIRED: tuple[str, ...] = ("name", "description", "command")
    EXTENSIONS: tuple[str, ...] = (".json", ".yaml", ".yml")

    try:
        entries = os.scandir(directory)
    except OSError:
        return

    for entry in entries:
        if not entry.is_file():
            continue

        _root, ext = os.path.splitext(entry.name)
        if ext.lower() not in EXTENSIONS:
            continue

        # --- parse file ---
        try:
            with open(entry.path, "r", encoding="utf-8") as fh:
                if ext.lower() == ".json":
                    data: Dict[str, Any] = json.load(fh)
                else:
                    data = yaml.safe_load(fh)
        except Exception:
            continue

        if not isinstance(data, dict):
            continue

        # --- validate required fields ---
        if not all(isinstance(data.get(k), str) for k in REQUIRED):
            continue

        # --- instantiate and register ---
        try:
            primitive = CLIPrimitive(
                name=data["name"],
                description=data["description"],
                command=data["command"],
            )
        except Exception:
            continue

        registry.register(primitive.name, primitive)
