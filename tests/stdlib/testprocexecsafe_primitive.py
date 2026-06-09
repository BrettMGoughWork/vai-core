"""Tests for stdlib.proc.execsafe primitive (Phase 3.18.9)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.proc_execsafe import ProcExecSafePrimitive


@pytest.fixture
def proc_execsafe() -> ProcExecSafePrimitive:
    return ProcExecSafePrimitive()


class TestProcExecSafePrimitive:
    """Tests for ProcExecSafePrimitive.validate_args and execute."""

    def test_allowed_command(self, proc_execsafe: ProcExecSafePrimitive) -> None:
        result = proc_execsafe.execute(
            {"command": "echo hello", "allowed_commands": ["echo"]}, {}
        )
        assert result.status == "success"
        assert "hello" in result.data["stdout"]

    def test_allowed_list_command(self, proc_execsafe: ProcExecSafePrimitive) -> None:
        result = proc_execsafe.execute(
            {"command": ["echo", "test"], "allowed_commands": ["echo"]}, {}
        )
        assert result.status == "success"
        assert "test" in result.data["stdout"]

    def test_command_not_allowed(self, proc_execsafe: ProcExecSafePrimitive) -> None:
        result = proc_execsafe.execute(
            {"command": "echo hello", "allowed_commands": ["python"]}, {}
        )
        assert result.status == "error"
        assert "not in allowed_commands" in result.error or result.data.get("blocked")

    def test_blocked_command(self, proc_execsafe: ProcExecSafePrimitive) -> None:
        result = proc_execsafe.execute({"command": "rm -rf /"}, {})
        assert result.status == "error"
        assert result.data.get("blocked") is True

    def test_missing_command_raises_value_error(self, proc_execsafe: ProcExecSafePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'command'"):
            proc_execsafe.validate_args({})

    def test_empty_command_raises_value_error(self, proc_execsafe: ProcExecSafePrimitive) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            proc_execsafe.validate_args({"command": ""})

    def test_command_not_string_or_list_raises_value_error(self, proc_execsafe: ProcExecSafePrimitive) -> None:
        with pytest.raises(ValueError, match="must be a string or list"):
            proc_execsafe.validate_args({"command": 42})

    def test_list_command_with_non_string_raises_value_error(self, proc_execsafe: ProcExecSafePrimitive) -> None:
        with pytest.raises(ValueError, match="must contain only strings"):
            proc_execsafe.validate_args({"command": ["echo", 123]})
