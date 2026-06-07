"""
Tests for the MCP primitive loader (Phase 3.2.4).

Covers: valid manifests, missing top-level fields, missing tool fields,
invalid files, and duplicate-name rejection.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest
import yaml

from src.capabilities.registry.mcp_loader import load_mcp_primitives
from src.capabilities.registry.primitive_registry import PrimitiveRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry() -> PrimitiveRegistry:
    return PrimitiveRegistry()


@pytest.fixture
def manifests_dir() -> str:
    """Temporary directory with MCP manifest files."""
    tmp = tempfile.mkdtemp(prefix="mcp_test_")

    # Valid JSON manifest with two tools
    with open(os.path.join(tmp, "filesystem.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "server_name": "fs",
                "tools": [
                    {"name": "read", "description": "read a file"},
                    {"name": "write", "description": "write a file"},
                ],
            },
            f,
        )

    # Valid YAML manifest with one tool
    with open(os.path.join(tmp, "database.yaml"), "w", encoding="utf-8") as f:
        yaml.dump(
            {
                "server_name": "db",
                "tools": [
                    {"name": "query", "description": "run SQL query"},
                ],
            },
            f,
        )

    # Missing server_name
    with open(os.path.join(tmp, "no_server.json"), "w", encoding="utf-8") as f:
        json.dump({"tools": [{"name": "x", "description": "y"}]}, f)

    # Missing tools
    with open(os.path.join(tmp, "no_tools.yaml"), "w", encoding="utf-8") as f:
        yaml.dump({"server_name": "orphan"}, f)

    # Tool missing description
    with open(os.path.join(tmp, "bad_tool.json"), "w", encoding="utf-8") as f:
        json.dump(
            {"server_name": "bad", "tools": [{"name": "incomplete"}]},
            f,
        )

    # Invalid JSON
    with open(os.path.join(tmp, "garbage.json"), "w", encoding="utf-8") as f:
        f.write("not json {{{")

    # Non-manifest file
    with open(os.path.join(tmp, "notes.txt"), "w", encoding="utf-8") as f:
        f.write("ignore me")

    yield tmp

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMCPLoader:
    def test_valid_manifests_registered(
        self, registry: PrimitiveRegistry, manifests_dir: str
    ) -> None:
        load_mcp_primitives(registry, manifests_dir)
        names = {p.name for p in registry.list()}
        assert names == {"fs.read", "fs.write", "db.query"}

    def test_missing_server_name_skipped(
        self, registry: PrimitiveRegistry, manifests_dir: str
    ) -> None:
        load_mcp_primitives(registry, manifests_dir)
        # No primitive from "no_server.json" should be registered
        assert registry.get("x") is None

    def test_missing_tools_skipped(
        self, registry: PrimitiveRegistry, manifests_dir: str
    ) -> None:
        load_mcp_primitives(registry, manifests_dir)
        # No primitive from "no_tools.yaml"
        assert len(registry.list()) == 3  # only fs.read, fs.write, db.query

    def test_tool_missing_description_skipped(
        self, registry: PrimitiveRegistry, manifests_dir: str
    ) -> None:
        load_mcp_primitives(registry, manifests_dir)
        assert registry.get("bad.incomplete") is None

    def test_invalid_json_skipped(
        self, registry: PrimitiveRegistry, manifests_dir: str
    ) -> None:
        load_mcp_primitives(registry, manifests_dir)
        assert len(registry.list()) == 3

    def test_directory_not_found_no_error(self, registry: PrimitiveRegistry) -> None:
        load_mcp_primitives(registry, "Z:\\missing")
        assert registry.list() == []

    def test_duplicate_name_raises_value_error(
        self, registry: PrimitiveRegistry
    ) -> None:
        """Two manifests that produce the same primitive name should raise."""
        tmp = tempfile.mkdtemp(prefix="mcp_dup_")
        with open(os.path.join(tmp, "a.json"), "w", encoding="utf-8") as f:
            json.dump(
                {"server_name": "svc", "tools": [{"name": "run", "description": "first"}]},
                f,
            )
        with open(os.path.join(tmp, "b.yaml"), "w", encoding="utf-8") as f:
            yaml.dump(
                {"server_name": "svc", "tools": [{"name": "run", "description": "second"}]},
                f,
            )

        with pytest.raises(ValueError, match="already registered"):
            load_mcp_primitives(registry, tmp)

        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    def test_non_dict_tool_entry_skipped(
        self, registry: PrimitiveRegistry
    ) -> None:
        tmp = tempfile.mkdtemp(prefix="mcp_non_dict_tool_")
        with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(
                {"server_name": "s", "tools": [{"name": "ok", "description": "ok"}, "not-a-dict"]},
                f,
            )

        load_mcp_primitives(registry, tmp)
        names = {p.name for p in registry.list()}
        assert names == {"s.ok"}

        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
