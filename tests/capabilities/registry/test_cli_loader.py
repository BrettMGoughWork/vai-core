"""
Tests for the CLI primitive loader (Phase 3.2.3).

Covers: valid JSON/YAML loading, missing fields, invalid files,
mixed directories, and duplicate-name rejection.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest
import yaml

from src.capabilities.registry.cli_loader import load_cli_primitives
from src.capabilities.registry.primitive_registry import PrimitiveRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry() -> PrimitiveRegistry:
    return PrimitiveRegistry()


@pytest.fixture
def manifests_dir() -> str:
    """Create a temporary directory populated with CLI manifest files."""
    tmp = tempfile.mkdtemp(prefix="cli_test_")

    # Valid JSON
    with open(os.path.join(tmp, "echo.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "cli.echo", "description": "echo to stdout", "command": "echo"}, f)

    # Valid YAML
    with open(os.path.join(tmp, "date.yaml"), "w", encoding="utf-8") as f:
        yaml.dump({"name": "cli.date", "description": "print date", "command": "date"}, f)

    # Missing 'command'
    with open(os.path.join(tmp, "no_command.json"), "w", encoding="utf-8") as f:
        json.dump({"name": "broken", "description": "no command field"}, f)

    # Invalid JSON
    with open(os.path.join(tmp, "bad.json"), "w", encoding="utf-8") as f:
        f.write("this is not json {{{")

    # Non-manifest file (should be ignored)
    with open(os.path.join(tmp, "README.txt"), "w", encoding="utf-8") as f:
        f.write("just some text")

    # .yml extension
    with open(os.path.join(tmp, "ls.yml"), "w", encoding="utf-8") as f:
        yaml.dump({"name": "cli.ls", "description": "list files", "command": "ls"}, f)

    yield tmp

    # Cleanup
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCLILoader:
    def test_valid_files_registered(
        self, registry: PrimitiveRegistry, manifests_dir: str
    ) -> None:
        load_cli_primitives(registry, manifests_dir)
        names = {p.name for p in registry.list()}
        assert names == {"cli.echo", "cli.date", "cli.ls"}

    def test_missing_required_fields_skipped(
        self, registry: PrimitiveRegistry, manifests_dir: str
    ) -> None:
        load_cli_primitives(registry, manifests_dir)
        assert registry.get("broken") is None

    def test_invalid_file_skipped(
        self, registry: PrimitiveRegistry, manifests_dir: str
    ) -> None:
        load_cli_primitives(registry, manifests_dir)
        # No primitives registered from "bad.json"
        assert registry.get("bad") is None

    def test_non_manifest_files_ignored(
        self, registry: PrimitiveRegistry, manifests_dir: str
    ) -> None:
        load_cli_primitives(registry, manifests_dir)
        # README.txt is not a manifest → nothing from it
        assert len(registry.list()) == 3  # only the 3 valid manifests

    def test_directory_not_found_no_error(self, registry: PrimitiveRegistry) -> None:
        load_cli_primitives(registry, "Z:\\nonexistent\\dir")
        assert registry.list() == []

    def test_duplicate_name_raises_value_error(
        self, registry: PrimitiveRegistry
    ) -> None:
        """If two manifests define the same name, the second register raises."""
        tmp = tempfile.mkdtemp(prefix="cli_dup_")

        with open(os.path.join(tmp, "a.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "dup", "description": "first", "command": "a"}, f)
        with open(os.path.join(tmp, "b.yaml"), "w", encoding="utf-8") as f:
            yaml.dump({"name": "dup", "description": "second", "command": "b"}, f)

        with pytest.raises(ValueError, match="already registered"):
            load_cli_primitives(registry, tmp)

        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    def test_non_dict_yaml_skipped(self, registry: PrimitiveRegistry) -> None:
        tmp = tempfile.mkdtemp(prefix="cli_nondict_")
        with open(os.path.join(tmp, "list.yml"), "w", encoding="utf-8") as f:
            yaml.dump([1, 2, 3], f)

        load_cli_primitives(registry, tmp)
        assert registry.list() == []

        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
