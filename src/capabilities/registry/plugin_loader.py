"""
Plugin loader — discovers, validates, and registers filesystem plugins.

A plugin is a directory containing a ``plugin.yml`` manifest plus
``primitives/`` and/or ``mcp/`` subdirectories.  The PluginLoader scans
a ``plugins/`` directory, validates manifests, imports Python primitives,
and registers everything into the existing ``PrimitiveRegistry``.

Usage::

    from src.capabilities.registry.plugin_loader import PluginLoader
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry

    prim_registry = PrimitiveRegistry()
    loader = PluginLoader(prim_registry)
    loader.load_all("plugins/")
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.registry.plugin_schema import PluginManifest
from src.capabilities.registry.snapshot import SnapshotManager

if TYPE_CHECKING:
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry


class PluginLoader:
    """Discovers, loads, unloads, and reloads filesystem plugins."""

    def __init__(
        self,
        prim_registry: PrimitiveRegistry,
    ) -> None:
        self._prim_registry = prim_registry
        self._loaded: dict[str, _LoadedPlugin] = {}
        self._snapshot_manager = SnapshotManager()
        # Persist paths of unloaded plugins so reload_plugin works after explicit unload.
        self._reloadable_paths: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_plugins(self, plugins_dir: str) -> list[str]:
        """Scan *plugins_dir* for subdirectories containing a ``plugin.yml``.

        Returns:
            Plugin names (directory names, sorted for determinism).
        """
        plugins: list[str] = []
        root = Path(plugins_dir).resolve()
        if not root.is_dir():
            return plugins
        for entry in sorted(root.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                manifest_path = entry / "plugin.yml"
                if manifest_path.is_file():
                    plugins.append(entry.name)
        return plugins

    def load_plugin(self, plugin_dir: str) -> str:
        """Load a single plugin from *plugin_dir*.

        Args:
            plugin_dir: Path to the plugin directory (must contain ``plugin.yml``).

        Returns:
            The plugin name from the manifest.

        Raises:
            ValueError: If the manifest is invalid, a primitive fails to load,
                        a skill references an unknown primitive, or the plugin
                        name collides with an already-loaded plugin or stdlib.
            FileNotFoundError: If ``plugin_dir`` does not exist or has no manifest.
        """
        plugin_path = Path(plugin_dir).resolve()
        manifest_path = plugin_path / "plugin.yml"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"No plugin.yml found in {plugin_dir}")

        manifest = _parse_manifest(manifest_path)

        # --- collision detection ---
        if manifest.name in self._loaded:
            raise ValueError(
                f"Plugin '{manifest.name}' is already loaded. "
                f"Unload it first before re‑loading."
            )
        if self._prim_registry.get(manifest.name) is not None:
            raise ValueError(
                f"Plugin name '{manifest.name}' collides with a stdlib primitive "
                f"— plugin names must not shadow built‑ins."
            )

        # --- load primitives ---
        primitive_names: list[str] = []
        primitives_dir = plugin_path / "primitives"
        if primitives_dir.is_dir():
            for stem in manifest.primitives:
                py_file = _resolve_primitive_file(primitives_dir, stem)
                instances = _load_primitives_from_file(py_file, manifest.name)
                for inst in instances:
                    inst.plugin_name = manifest.name
                    inst.plugin_version = manifest.version
                    self._prim_registry.register(inst.name, inst)
                    primitive_names.append(inst.name)

        # --- auto-discover primitives not listed in manifest ---
        if primitives_dir.is_dir():
            for py_file in sorted(primitives_dir.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue
                stem = py_file.stem
                if stem in manifest.primitives:
                    continue  # already loaded above
                instances = _load_primitives_from_file(py_file, manifest.name)
                for inst in instances:
                    inst.plugin_name = manifest.name
                    inst.plugin_version = manifest.version
                    self._prim_registry.register(inst.name, inst)
                    primitive_names.append(inst.name)

        # --- load MCP servers (via MCPLoader from YAML config) ---
        mcp_config_path = plugin_path / "mcp" / "mcp_servers.yaml"
        if mcp_config_path.is_file():
            from src.capabilities.registry.loaders.mcp_loader import MCPLoader
            with open(mcp_config_path) as f:
                config = yaml.safe_load(f) or {}
            for prim in MCPLoader.load_from_config(config):
                prim.plugin_name = manifest.name
                prim.plugin_version = manifest.version
                self._prim_registry.register(prim.name, prim)
                primitive_names.append(prim.name)

        # --- track ---
        self._loaded[manifest.name] = _LoadedPlugin(
            manifest=manifest,
            primitive_names=primitive_names,
            plugin_path=str(plugin_path),
        )

        self._capture_snapshot()
        return manifest.name

    def load_all(self, plugins_dir: str) -> list[str]:
        """Scan *plugins_dir* and load every discovered plugin.

        Plugins that fail to load are skipped (with a warning printed to
        stderr).  Already-loaded plugins are not re‑loaded.

        Returns:
            List of plugin names that were successfully loaded.
        """
        loaded: list[str] = []
        for name in self.scan_plugins(plugins_dir):
            if name in self._loaded:
                continue
            plugin_path = str(Path(plugins_dir).resolve() / name)
            try:
                self.load_plugin(plugin_path)
                loaded.append(name)
            except Exception as exc:
                import sys as _sys
                print(
                    f"  ⚠ Failed to load plugin '{name}': {exc}",
                    file=_sys.stderr,
                )
        return loaded

    def unload_plugin(self, plugin_name: str) -> None:
        """Unregister all primitives and skills from a loaded plugin.

        Raises:
            KeyError: If *plugin_name* is not currently loaded.
        """
        info = self._loaded.get(plugin_name)
        if info is None:
            raise KeyError(f"Plugin '{plugin_name}' is not currently loaded")

        # Remember the path so reload_plugin can find it later.
        self._reloadable_paths[plugin_name] = info.plugin_path

        # Deregister primitives
        for prim_name in info.primitive_names:
            self._prim_registry.remove(prim_name)

        del self._loaded[plugin_name]
        self._capture_snapshot()

    def reload_plugin(self, plugin_name: str) -> str:
        """Unload and then reload a plugin from its recorded path.

        Returns:
            The plugin name on success.

        Raises:
            KeyError: If *plugin_name* is not currently loaded.
            ValueError: If the reload fails (original state is *not* restored).
        """
        # First check if still loaded; if not, look in the unloaded-path map.
        info = self._loaded.get(plugin_name)
        if info is not None:
            # Still loaded: normal reload path.
            plugin_path = info.plugin_path
            self.unload_plugin(plugin_name)
            return self.load_plugin(plugin_path)

        plugin_path = self._reloadable_paths.pop(plugin_name, None)
        if plugin_path is None:
            raise KeyError(f"Plugin '{plugin_name}' is not currently loaded")
        return self.load_plugin(plugin_path)

    def _capture_snapshot(self) -> None:
        """Capture a deterministic registry snapshot after state change."""
        primitives = sorted(
            self._prim_registry.list(),
            key=lambda p: p.name,
        )
        self._snapshot_manager.capture([], primitives)

    def list_loaded(self) -> list[str]:
        """Return sorted list of currently loaded plugin names."""
        return sorted(self._loaded.keys())


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


class _LoadedPlugin:
    """Bookkeeping for a loaded plugin."""

    def __init__(
        self,
        manifest: PluginManifest,
        primitive_names: list[str],
        plugin_path: str,
    ) -> None:
        self.manifest = manifest
        self.primitive_names = primitive_names
        self.plugin_path = plugin_path


def _parse_manifest(path: Path) -> PluginManifest:
    """Parse and validate a plugin.yml file."""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(
            f"Invalid plugin manifest in {path}: YAML must be a mapping"
        )
    return PluginManifest.from_dict(data)


def _resolve_primitive_file(primitives_dir: Path, stem: str) -> Path:
    """Find a Python file matching *stem* in *primitives_dir*."""
    candidate = primitives_dir / f"{stem}.py"
    if candidate.is_file():
        return candidate
    candidate = primitives_dir / stem
    if candidate.is_file() and candidate.suffix == ".py":
        return candidate
    raise FileNotFoundError(
        f"Primitive file '{stem}.py' not found in {primitives_dir}"
    )


def _load_primitives_from_file(
    py_file: Path, plugin_name: str
) -> list[PrimitiveBase]:
    """Import a Python file and return all PrimitiveBase subclass instances."""
    module_name = f"_vai_plugin_{plugin_name}_{py_file.stem}"
    spec = importlib.util.spec_from_file_location(module_name, str(py_file))
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load primitive module: {py_file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ValueError(
            f"Failed to import primitive module '{py_file}': {exc}"
        ) from exc

    instances: list[PrimitiveBase] = []
    for attr_name in dir(module):
        if not attr_name.endswith("Primitive"):
            continue
        cls = getattr(module, attr_name)
        if not isinstance(cls, type) or not issubclass(cls, PrimitiveBase):
            continue
        if cls is PrimitiveBase:
            continue
        try:
            instances.append(cls())
        except Exception as exc:
            raise ValueError(
                f"Failed to instantiate {attr_name} from '{py_file}': {exc}"
            ) from exc

    if not instances:
        raise ValueError(
            f"No PrimitiveBase subclass found in '{py_file}'"
        )
    return instances

