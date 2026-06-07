"""
Tests for PythonPrimitive (Phase 3.1.6).

Covers: argument validation, execution semantics, error propagation,
side‑effect stubbing, and type correctness.
"""

from __future__ import annotations

import pytest

from src.capabilities.primitives.python import PythonPrimitive
from src.capabilities.primitives.types import PrimitiveType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def add_primitive() -> PythonPrimitive:
    """A primitive wrapping a simple two-argument function."""
    return PythonPrimitive(
        name="test.add",
        description="add two numbers",
        func=lambda a, b: a + b,
    )


@pytest.fixture
def single_arg_primitive() -> PythonPrimitive:
    """A primitive wrapping a single-argument function (accepts any keys)."""
    return PythonPrimitive(
        name="test.echo",
        description="echo the args dict",
        func=lambda args: args,
    )


@pytest.fixture
def boom_primitive() -> PythonPrimitive:
    """A primitive whose function always raises."""
    return PythonPrimitive(
        name="test.fail",
        description="always fails",
        func=lambda args: (_ for _ in ()).throw(RuntimeError("fail")),
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_rejects_non_dict(self, add_primitive: PythonPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a dict"):
            add_primitive.validate_args("not-a-dict")  # type: ignore[arg-type]

    def test_missing_required_arg(self, add_primitive: PythonPrimitive) -> None:
        with pytest.raises(ValueError, match="Missing required argument"):
            add_primitive.validate_args({"a": 1})

    def test_extra_arg(self, add_primitive: PythonPrimitive) -> None:
        with pytest.raises(ValueError, match="Unexpected arguments"):
            add_primitive.validate_args({"a": 1, "b": 2, "c": 3})

    def test_valid_args(self, add_primitive: PythonPrimitive) -> None:
        # Should not raise
        add_primitive.validate_args({"a": 1, "b": 2})

    def test_single_arg_accepts_any_keys(
        self, single_arg_primitive: PythonPrimitive
    ) -> None:
        # Single-param callables accept any keys
        single_arg_primitive.validate_args({"anything": "goes", "x": 42})

    def test_empty_args_for_single_arg(
        self, single_arg_primitive: PythonPrimitive
    ) -> None:
        single_arg_primitive.validate_args({})

    def test_none_validates_all_required_absent(
        self, add_primitive: PythonPrimitive
    ) -> None:
        # Passing empty dict when func expects two required params
        with pytest.raises(ValueError, match="Missing required argument"):
            add_primitive.validate_args({})


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

class TestExecution:
    def test_success_result(self, add_primitive: PythonPrimitive) -> None:
        result = add_primitive.execute({"a": 3, "b": 4}, {})
        assert result.status == "success"
        assert result.data == 7
        assert result.error is None

    def test_error_propagation(self, boom_primitive: PythonPrimitive) -> None:
        # A multi-param callable requires keys; empty dict raises ValueError
        # But boom_primitive is defined with lambda: ... (no params) so args is
        # a single-param callable → any keys accepted, then func(args) raises
        # TypeError (0 positional args but 1 given).
        result = boom_primitive.execute({}, {})
        assert result.status == "error"
        assert result.error is not None
        assert result.data is None

    def test_exception_wrapped_as_error(
        self, add_primitive: PythonPrimitive
    ) -> None:
        """A function that raises at runtime returns an error result."""
        p = PythonPrimitive(
            name="test.boom",
            description="raises",
            func=lambda a, b: (_ for _ in ()).throw(RuntimeError("kaboom")),
        )
        result = p.execute({"a": 1, "b": 2}, {})
        assert result.status == "error"
        assert "kaboom" in (result.error or "")

    def test_execute_calls_validate_first(self) -> None:
        """Missing args should surface as ValueError before func runs."""
        p = PythonPrimitive(
            name="test.strict",
            description="strict two-param",
            func=lambda a, b: a + b,
        )
        with pytest.raises(ValueError, match="Missing required argument"):
            p.execute({"a": 1}, {})

    def test_single_arg_receives_full_dict(
        self, single_arg_primitive: PythonPrimitive
    ) -> None:
        result = single_arg_primitive.execute({"x": 1, "y": 2}, {})
        assert result.status == "success"
        assert result.data == {"x": 1, "y": 2}


# ---------------------------------------------------------------------------
# Side effects
# ---------------------------------------------------------------------------

class TestSideEffects:
    def test_success_side_effects_empty(self, add_primitive: PythonPrimitive) -> None:
        result = add_primitive.execute({"a": 1, "b": 2}, {})
        assert result.side_effects == []

    def test_error_side_effects_empty(
        self, add_primitive: PythonPrimitive
    ) -> None:
        result = add_primitive.execute({"a": 1, "b": "not_a_number"}, {})
        # This will call func(1, "not_a_number") which succeeds (Python adds
        # them if possible or concatenates strings).  Use a guaranteed error.
        p = PythonPrimitive(
            name="test.explode",
            description="raises",
            func=lambda a, b: 1 / 0,
        )
        result = p.execute({"a": 1, "b": 0}, {})
        assert result.status == "error"
        assert result.side_effects == []


# ---------------------------------------------------------------------------
# Type correctness
# ---------------------------------------------------------------------------

class TestTypeCorrectness:
    def test_primitive_type_is_python(self, add_primitive: PythonPrimitive) -> None:
        assert add_primitive.primitive_type == PrimitiveType.PYTHON

    def test_name_and_description(self, add_primitive: PythonPrimitive) -> None:
        assert add_primitive.name == "test.add"
        assert "add" in add_primitive.description.lower()
