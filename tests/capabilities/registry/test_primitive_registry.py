"""
Tests for PrimitiveRegistry (Phase 3.2.1).

Covers: registration, duplicate handling, get, list (with filter),
find (ranked substring search, zero-score exclusion).
"""

from __future__ import annotations

import pytest

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveType, PrimitiveResult
from src.capabilities.registry.primitive_registry import PrimitiveRegistry


# ---------------------------------------------------------------------------
# Fake primitive
# ---------------------------------------------------------------------------

class FakePrimitive(PrimitiveBase):
    """Minimal concrete primitive for registry testing."""

    def __init__(
        self,
        *,
        name: str,
        description: str = "",
        primitive_type: PrimitiveType = PrimitiveType.PYTHON,
    ) -> None:
        super().__init__(name=name, description=description, primitive_type=primitive_type)

    def validate_args(self, _args: dict) -> None:
        return

    def execute(self, _args: dict, _context: dict) -> PrimitiveResult:
        return PrimitiveResult(status="success", data=None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry() -> PrimitiveRegistry:
    """A fresh, empty PrimitiveRegistry."""
    return PrimitiveRegistry()


@pytest.fixture
def simple_primitive() -> FakePrimitive:
    return FakePrimitive(name="echo", description="prints the input")


@pytest.fixture
def populated_registry(registry: PrimitiveRegistry) -> PrimitiveRegistry:
    registry.register("echo", FakePrimitive(name="echo", description="prints the input"))
    registry.register(
        "file.read", FakePrimitive(name="file.read", description="read a file from disk")
    )
    registry.register(
        "file.write", FakePrimitive(name="file.write", description="write data to a file")
    )
    registry.register(
        "net.fetch",
        FakePrimitive(name="net.fetch", description="fetch a URL over HTTP"),
    )
    return registry


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_register_succeeds(
        self, registry: PrimitiveRegistry, simple_primitive: FakePrimitive
    ) -> None:
        registry.register(simple_primitive.name, simple_primitive)
        assert registry.get("echo") is simple_primitive

    def test_duplicate_raises_value_error(
        self, registry: PrimitiveRegistry, simple_primitive: FakePrimitive
    ) -> None:
        registry.register(simple_primitive.name, simple_primitive)
        with pytest.raises(ValueError, match="already registered"):
            registry.register("echo", FakePrimitive(name="echo", description="different"))

    def test_register_preserves_first(
        self, registry: PrimitiveRegistry, simple_primitive: FakePrimitive
    ) -> None:
        registry.register(simple_primitive.name, simple_primitive)
        with pytest.raises(ValueError):
            registry.register("echo", FakePrimitive(name="echo", description="other"))
        # The original should still be in place
        assert registry.get("echo") is simple_primitive


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------

class TestGet:
    def test_get_returns_primitive(
        self, registry: PrimitiveRegistry, simple_primitive: FakePrimitive
    ) -> None:
        registry.register("echo", simple_primitive)
        assert registry.get("echo") is simple_primitive

    def test_get_returns_none_for_missing(self, registry: PrimitiveRegistry) -> None:
        assert registry.get("ghost") is None

    def test_get_returns_none_empty_registry(self, registry: PrimitiveRegistry) -> None:
        assert registry.get("anything") is None


# ---------------------------------------------------------------------------
# list()
# ---------------------------------------------------------------------------

class TestList:
    def test_list_empty_registry(self, registry: PrimitiveRegistry) -> None:
        assert registry.list() == []

    def test_list_returns_all(self, populated_registry: PrimitiveRegistry) -> None:
        names = {p.name for p in populated_registry.list()}
        assert names == {"echo", "file.read", "file.write", "net.fetch"}

    def test_list_with_filter(self, populated_registry: PrimitiveRegistry) -> None:
        result = populated_registry.list(lambda p: "file" in p.name)
        names = {p.name for p in result}
        assert names == {"file.read", "file.write"}

    def test_list_filter_no_matches(self, populated_registry: PrimitiveRegistry) -> None:
        result = populated_registry.list(lambda p: p.name == "ghost")
        assert result == []


# ---------------------------------------------------------------------------
# find()
# ---------------------------------------------------------------------------

class TestFind:
    def test_find_name_match_scores_higher(
        self, populated_registry: PrimitiveRegistry
    ) -> None:
        results = populated_registry.find("file")
        # name matches (+2) and may also match description (+1) → ≥ 2
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)
        assert scores[0] >= 2  # "file.read" / "file.write" matched name

    def test_find_description_match_scores_lower(
        self, populated_registry: PrimitiveRegistry
    ) -> None:
        results = populated_registry.find("HTTP")
        assert len(results) >= 1
        assert results[0]["name"] == "net.fetch"
        assert results[0]["score"] == 1  # description only

    def test_find_excludes_zero_score(self, populated_registry: PrimitiveRegistry) -> None:
        results = populated_registry.find("zzzz_nonexistent_token")
        assert results == []

    def test_find_sorts_descending(self, populated_registry: PrimitiveRegistry) -> None:
        results = populated_registry.find("file")
        assert len(results) >= 2
        for i in range(len(results) - 1):
            assert results[i]["score"] >= results[i + 1]["score"]

    def test_find_case_insensitive(self, populated_registry: PrimitiveRegistry) -> None:
        lower = populated_registry.find("file.read")
        upper = populated_registry.find("FILE.READ")
        assert len(lower) == len(upper)
        assert [r["name"] for r in lower] == [r["name"] for r in upper]

    def test_find_result_structure(self, populated_registry: PrimitiveRegistry) -> None:
        results = populated_registry.find("echo")
        assert len(results) == 1
        r = results[0]
        assert r["name"] == "echo"
        assert r["score"] > 0
        assert isinstance(r["primitive"], PrimitiveBase)
