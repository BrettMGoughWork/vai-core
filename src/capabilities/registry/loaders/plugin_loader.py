"""Plugin primitive loader — loads primitives from external plugin packages."""

from __future__ import annotations

from typing import List, Optional

from src.capabilities.primitives.base import PrimitiveBase


class PluginLoader:
    """Loads primitives from external plugin packages."""

    @staticmethod
    def discover_plugins(search_paths: Optional[List[str]] = None) -> List[PrimitiveBase]:
        """Discover primitives from installed plugins.

        Plugins are Python packages that expose primitives via
        an entry point or convention-based module.
        """
        primitives: List[PrimitiveBase] = []
        try:
            from importlib.metadata import entry_points
            for ep in entry_points(group="vai.primitives"):
                factory = ep.load()
                result = factory()
                if isinstance(result, list):
                    primitives.extend(result)
                elif isinstance(result, PrimitiveBase):
                    primitives.append(result)
        except Exception:
            # Plugin discovery is best-effort
            pass
        return primitives


__all__ = ["PluginLoader"]
