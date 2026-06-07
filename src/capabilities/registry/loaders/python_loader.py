"""Python primitive loader — scans modules for PrimitiveBase subclasses and auto-registers them."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import TYPE_CHECKING

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveType

if TYPE_CHECKING:
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry


def load_python_primitives(registry: PrimitiveRegistry) -> None:
    """Scan all modules in the primitives package for PrimitiveBase subclasses
    and register valid instances into *registry*.

    Modules excluded from scanning:
        - ``__init__`` (package init)
        - ``types`` (type definitions)
        - ``base`` (abstract base class)
    """
    import src.capabilities.primitives as primitives_pkg

    EXCLUDED = {"__init__", "types", "base"}

    for _finder, module_name, _ispkg in pkgutil.iter_modules(
        primitives_pkg.__path__, primitives_pkg.__name__ + "."
    ):
        short_name = module_name.split(".")[-1]
        if short_name in EXCLUDED or _ispkg:
            continue

        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue

        for _attr_name, cls in inspect.getmembers(module, inspect.isclass):
            if cls is PrimitiveBase or not issubclass(cls, PrimitiveBase):
                continue

            if not (
                isinstance(getattr(cls, "name", None), str)
                and isinstance(getattr(cls, "description", None), str)
                and isinstance(getattr(cls, "primitive_type", None), PrimitiveType)
            ):
                continue

            try:
                instance = cls()
            except Exception:
                continue

            registry.register(instance.name, instance)
