"""
Tests for the Python primitive loader (Phase 3.2.2).

Covers: module scanning, class detection, instantiation failure,
module exclusion, and subpackage skipping via monkeypatch.
"""

from __future__ import annotations

from types import ModuleType
from unittest.mock import patch

import pytest

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveType, PrimitiveResult
from src.capabilities.registry.loaders.python_loader import load_python_primitives
from src.capabilities.registry.primitive_registry import PrimitiveRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeDiscoverable(PrimitiveBase):
    """A valid, no-arg-instantiable primitive subclass."""
    name = "discovered.echo"
    description = "discovered echo"
    primitive_type = PrimitiveType.PYTHON

    def __init__(self) -> None:
        super().__init__(
            name=self.name,
            description=self.description,
            primitive_type=self.primitive_type,
        )

    def validate_args(self, args: dict) -> None:
        pass

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        return PrimitiveResult(status="success", data=None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry() -> PrimitiveRegistry:
    return PrimitiveRegistry()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPythonLoader:
    def test_registers_valid_primitive_class(self, registry: PrimitiveRegistry) -> None:
        """A module containing a valid PrimitiveBase subclass with class-level
        attributes should be instantiated and registered."""
        fake_module = ModuleType("fake_dynamic_module")
        fake_module.FakeDiscoverable = FakeDiscoverable

        with (
            patch(
                "src.capabilities.registry.loaders.python_loader.pkgutil.iter_modules",
                return_value=[(None, "fake_dynamic_module", False)],
            ),
            patch(
                "src.capabilities.registry.loaders.python_loader.importlib.import_module",
                return_value=fake_module,
            ),
        ):
            load_python_primitives(registry)

        got = registry.get("discovered.echo")
        assert got is not None
        assert got.name == "discovered.echo"

    def test_skips_module_import_failure(self, registry: PrimitiveRegistry) -> None:
        """A module that raises during import should be silently skipped."""

        with (
            patch(
                "src.capabilities.registry.loaders.python_loader.pkgutil.iter_modules",
                return_value=[(None, "broken_mod", False)],
            ),
            patch(
                "src.capabilities.registry.loaders.python_loader.importlib.import_module",
                side_effect=ImportError("nope"),
            ),
        ):
            load_python_primitives(registry)

        assert registry.list() == []

    def test_skips_class_instantiation_failure(self, registry: PrimitiveRegistry) -> None:
        """A class whose __init__ raises should be silently skipped."""

        class BrokenInit(PrimitiveBase):
            name = "broken"
            description = "breaks on init"
            primitive_type = PrimitiveType.PYTHON

            def __init__(self) -> None:
                raise RuntimeError("boom")

            def validate_args(self, args: dict) -> None:
                pass

            def execute(self, args: dict, context: dict) -> PrimitiveResult:
                return PrimitiveResult(status="success", data=None)

        fake_module = ModuleType("fake_broken_mod")
        fake_module.BrokenInit = BrokenInit

        with (
            patch(
                "src.capabilities.registry.loaders.python_loader.pkgutil.iter_modules",
                return_value=[(None, "fake_broken_mod", False)],
            ),
            patch(
                "src.capabilities.registry.loaders.python_loader.importlib.import_module",
                return_value=fake_module,
            ),
        ):
            load_python_primitives(registry)

        assert registry.list() == []

    def test_excludes_base_and_types_and_init(self, registry: PrimitiveRegistry) -> None:
        """Modules named '__init__', 'types', or 'base' should be excluded."""
        with patch(
            "src.capabilities.registry.loaders.python_loader.pkgutil.iter_modules",
        ) as mock_iter:
            mock_iter.return_value = [
                (None, "__init__", False),
                (None, "types", False),
                (None, "base", False),
            ]
            load_python_primitives(registry)

        assert registry.list() == []

    def test_skips_subpackages(self, registry: PrimitiveRegistry) -> None:
        """Subpackages (ispkg=True) should be skipped."""
        with patch(
            "src.capabilities.registry.loaders.python_loader.pkgutil.iter_modules"
        ) as mock_iter:
            mock_iter.return_value = [
                (None, "subpkg", True),
                (None, "valid_mod", False),
            ]
            with patch(
                "src.capabilities.registry.loaders.python_loader.importlib.import_module",
                return_value=ModuleType("valid_mod"),
            ):
                load_python_primitives(registry)

        # "valid_mod" had no valid classes → nothing registered
        assert registry.list() == []

    def test_skips_non_primitive_classes(self, registry: PrimitiveRegistry) -> None:
        """Classes that are not subclasses of PrimitiveBase should be skipped."""
        fake_module = ModuleType("fake_non_prim_mod")

        class NotAPrimitive:
            pass

        fake_module.NotAPrimitive = NotAPrimitive

        with (
            patch(
                "src.capabilities.registry.loaders.python_loader.pkgutil.iter_modules",
                return_value=[(None, "fake_non_prim_mod", False)],
            ),
            patch(
                "src.capabilities.registry.loaders.python_loader.importlib.import_module",
                return_value=fake_module,
            ),
        ):
            load_python_primitives(registry)

        assert registry.list() == []

    def test_skips_missing_attributes(self, registry: PrimitiveRegistry) -> None:
        """Subclasses missing 'name', 'description', or 'primitive_type' are skipped."""

        class NoAttrs(PrimitiveBase):
            def validate_args(self, args: dict) -> None:
                pass

            def execute(self, args: dict, context: dict) -> PrimitiveResult:
                return PrimitiveResult(status="success", data=None)

        fake_module = ModuleType("fake_no_attrs_mod")
        fake_module.NoAttrs = NoAttrs

        with (
            patch(
                "src.capabilities.registry.loaders.python_loader.pkgutil.iter_modules",
                return_value=[(None, "fake_no_attrs_mod", False)],
            ),
            patch(
                "src.capabilities.registry.loaders.python_loader.importlib.import_module",
                return_value=fake_module,
            ),
        ):
            load_python_primitives(registry)

        assert registry.list() == []
