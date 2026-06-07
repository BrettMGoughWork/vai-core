"""Tests for stdlib.echo primitive (Phase 3.7.1)."""

from __future__ import annotations

import copy

import pytest

from src.capabilities.primitives.stdlib.echo import EchoPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def echo() -> EchoPrimitive:
    """Real EchoPrimitive instance."""
    return EchoPrimitive()


class TestEchoPrimitive:
    """Tests for EchoPrimitive.validate_args and execute."""

    def test_valid_input_returns_identical_output(self, echo: EchoPrimitive) -> None:
        """A JSON-serializable value is returned unchanged."""
        for value in ("hello", 42, 3.14, True, None, [1, 2, 3], {"a": 1}):
            result = echo.execute({"value": value}, {})
            assert isinstance(result, PrimitiveResult)
            assert result.status == "success"
            assert result.data == {"value": value}
            assert result.error is None

    def test_input_is_not_mutated(self, echo: EchoPrimitive) -> None:
        """The primitive does not mutate the input dict or the value."""
        original_args = {"value": {"nested": [1, 2, 3]}}
        args = copy.deepcopy(original_args)
        result = echo.execute(args, {})
        assert result.status == "success"
        assert result.data == original_args
        # Verify input was not mutated.
        assert args == original_args

    def test_missing_value_raises_value_error(self, echo: EchoPrimitive) -> None:
        """Missing 'value' key raises ValueError."""
        with pytest.raises(ValueError, match="must contain 'value' key"):
            echo.validate_args({})

    def test_none_value_is_valid(self, echo: EchoPrimitive) -> None:
        """None is a valid JSON-serializable value."""
        result = echo.execute({"value": None}, {})
        assert result.status == "success"
        assert result.data == {"value": None}

    def test_deterministic_output(self, echo: EchoPrimitive) -> None:
        """Repeated calls with the same input produce identical results."""
        args = {"value": "deterministic"}
        results = [echo.execute(args, {}) for _ in range(5)]
        assert all(r.data == results[0].data for r in results)
        assert all(r.status == "success" for r in results)

    def test_context_is_ignored(self, echo: EchoPrimitive) -> None:
        """The context dict is read but not used."""
        result = echo.execute({"value": 1}, {"trace_id": "abc"})
        assert result.status == "success"

    def test_no_side_effects(self, echo: EchoPrimitive) -> None:
        """Primitive result has an empty side_effects list."""
        result = echo.execute({"value": "x"}, {})
        assert result.side_effects == []
