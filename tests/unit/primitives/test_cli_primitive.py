"""
Tests for CLIPrimitive (Phase 3.1.6).

Covers: argument validation, execution semantics, error propagation,
timeout protection, side‑effect stubbing, and type correctness.
"""

from __future__ import annotations

import pytest

from src.capabilities.primitives.cli import CLIPrimitive
from src.capabilities.primitives.types import PrimitiveType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def echo_primitive() -> CLIPrimitive:
    """A CLI primitive that prints 'ok' and exits 0."""
    return CLIPrimitive(
        name="test.echo",
        description="prints ok",
        command="python",
    )


@pytest.fixture
def fail_primitive() -> CLIPrimitive:
    """A CLI primitive that exits with code 1."""
    return CLIPrimitive(
        name="test.fail",
        description="exits 1",
        command="python",
    )


@pytest.fixture
def slow_primitive() -> CLIPrimitive:
    """A CLI primitive that sleeps long enough to trigger the timeout."""
    return CLIPrimitive(
        name="test.slow",
        description="sleeps forever",
        command="python",
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_rejects_non_dict(self, echo_primitive: CLIPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a dict"):
            echo_primitive.validate_args("not-a-dict")  # type: ignore[arg-type]

    def test_accepts_empty_dict(self, echo_primitive: CLIPrimitive) -> None:
        echo_primitive.validate_args({})

    def test_accepts_arbitrary_keys(self, echo_primitive: CLIPrimitive) -> None:
        echo_primitive.validate_args({"a": 1, "b": "two", "c": 3.0})


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

class TestExecution:
    def test_success_result(self, echo_primitive: CLIPrimitive) -> None:
        result = echo_primitive.execute(
            {"-c": "print('ok')"},  # type: ignore[dict-item]
            {},
        )
        assert result.status == "success"
        assert result.error is None
        assert result.data is not None
        assert "stdout" in result.data
        assert "ok" in result.data["stdout"]

    def test_non_zero_exit(self, fail_primitive: CLIPrimitive) -> None:
        result = fail_primitive.execute(
            {"-c": "import sys; sys.exit(1)"},  # type: ignore[dict-item]
            {},
        )
        assert result.status == "error"
        assert result.error is not None
        assert result.data is None
        # The error message should mention exit code or contain stderr
        assert "1" in (result.error or "")

    def test_timeout(self, slow_primitive: CLIPrimitive) -> None:
        result = slow_primitive.execute(
            {"-c": "import time; time.sleep(10)"},  # type: ignore[dict-item]
            {},
        )
        assert result.status == "error"
        assert result.error == "timeout"

    def test_args_passed_as_positional_values(self) -> None:
        """Each value in args becomes a positional argument after the command."""
        p = CLIPrimitive(
            name="test.args",
            description="echoes args",
            command="python",
        )
        result = p.execute(
            {"-c": "import sys; print(sys.argv[1:])"},
            {},
        )
        assert result.status == "success"
        stdout = result.data["stdout"].strip() if result.data else ""
        # The first positional arg is the -c script string
        assert "sys.argv[1:]" in stdout or "[]" in stdout

    def test_stderr_captured_on_success(self, echo_primitive: CLIPrimitive) -> None:
        result = echo_primitive.execute(
            {"-c": "import sys; print('out'); print('err', file=sys.stderr)"},  # type: ignore[dict-item]
            {},
        )
        assert result.status == "success"
        assert "out" in result.data["stdout"]
        assert "err" in result.data["stderr"]

    def test_returncode_in_success_data(self, echo_primitive: CLIPrimitive) -> None:
        result = echo_primitive.execute(
            {"-c": "print('ok')"},  # type: ignore[dict-item]
            {},
        )
        assert result.data is not None
        assert result.data["returncode"] == 0


# ---------------------------------------------------------------------------
# Side effects
# ---------------------------------------------------------------------------

class TestSideEffects:
    def test_success_side_effects_empty(self, echo_primitive: CLIPrimitive) -> None:
        result = echo_primitive.execute(
            {"-c": "print('ok')"},  # type: ignore[dict-item]
            {},
        )
        assert result.side_effects == []

    def test_error_side_effects_empty(self, fail_primitive: CLIPrimitive) -> None:
        result = fail_primitive.execute(
            {"-c": "import sys; sys.exit(2)"},  # type: ignore[dict-item]
            {},
        )
        assert result.status == "error"
        assert result.side_effects == []

    def test_timeout_side_effects_empty(self, slow_primitive: CLIPrimitive) -> None:
        result = slow_primitive.execute(
            {"-c": "import time; time.sleep(10)"},  # type: ignore[dict-item]
            {},
        )
        assert result.status == "error"
        assert result.side_effects == []


# ---------------------------------------------------------------------------
# Type correctness
# ---------------------------------------------------------------------------

class TestTypeCorrectness:
    def test_primitive_type_is_cli(self, echo_primitive: CLIPrimitive) -> None:
        assert echo_primitive.primitive_type == PrimitiveType.CLI

    def test_name_and_description(self, echo_primitive: CLIPrimitive) -> None:
        assert echo_primitive.name == "test.echo"
        assert "prints" in echo_primitive.description.lower()
