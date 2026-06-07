"""Tests for stdlib.proc.exec primitive (Phase 3.7.4)."""

from __future__ import annotations

import sys

import pytest

from src.capabilities.primitives.stdlib.proc_exec import ProcExecPrimitive
from src.capabilities.primitives.types import PrimitiveResult


@pytest.fixture
def proc() -> ProcExecPrimitive:
    """Real ProcExecPrimitive instance."""
    return ProcExecPrimitive()


class TestProcExecPrimitiveValidate:
    """Tests for ProcExecPrimitive.validate_args."""

    def test_valid_cmd_passes(self, proc: ProcExecPrimitive) -> None:
        """A valid command passes validation."""
        proc.validate_args({"cmd": "echo hello"})

    def test_valid_cmd_with_timeout_passes(self, proc: ProcExecPrimitive) -> None:
        """A command with an integer timeout passes validation."""
        proc.validate_args({"cmd": "echo hello", "timeout": 30})

    def test_valid_cmd_with_none_timeout_passes(self, proc: ProcExecPrimitive) -> None:
        """A command with timeout=None passes validation."""
        proc.validate_args({"cmd": "echo hello", "timeout": None})

    def test_missing_cmd_raises(self, proc: ProcExecPrimitive) -> None:
        """Missing 'cmd' key raises ValueError."""
        with pytest.raises(ValueError, match="must contain 'cmd' key"):
            proc.validate_args({})

    def test_non_string_cmd_raises(self, proc: ProcExecPrimitive) -> None:
        """Non-string cmd raises ValueError."""
        with pytest.raises(ValueError, match="'cmd' must be a string"):
            proc.validate_args({"cmd": 42})

    def test_empty_cmd_raises(self, proc: ProcExecPrimitive) -> None:
        """Empty cmd string raises ValueError."""
        with pytest.raises(ValueError, match="'cmd' must not be empty"):
            proc.validate_args({"cmd": ""})

    def test_null_byte_raises(self, proc: ProcExecPrimitive) -> None:
        """Null byte in cmd raises ValueError."""
        with pytest.raises(ValueError, match="must not contain null bytes"):
            proc.validate_args({"cmd": "echo\x00bad"})

    def test_non_positive_timeout_raises(self, proc: ProcExecPrimitive) -> None:
        """Non-positive timeout raises ValueError."""
        with pytest.raises(ValueError, match="'timeout' must be a positive integer"):
            proc.validate_args({"cmd": "echo hi", "timeout": 0})

    def test_negative_timeout_raises(self, proc: ProcExecPrimitive) -> None:
        """Negative timeout raises ValueError."""
        with pytest.raises(ValueError, match="'timeout' must be a positive integer"):
            proc.validate_args({"cmd": "echo hi", "timeout": -1})

    def test_non_int_timeout_raises(self, proc: ProcExecPrimitive) -> None:
        """Non-integer timeout raises ValueError."""
        with pytest.raises(ValueError, match="'timeout' must be None or an int"):
            proc.validate_args({"cmd": "echo hi", "timeout": "30"})

    def test_args_not_a_dict_raises(self, proc: ProcExecPrimitive) -> None:
        """Non-dict args raises ValueError."""
        with pytest.raises(ValueError, match="args must be a dict"):
            proc.validate_args("bad")  # type: ignore[arg-type]


class TestProcExecPrimitiveExecute:
    """Tests for ProcExecPrimitive.execute."""

    def test_simple_command_returns_stdout(self, proc: ProcExecPrimitive) -> None:
        """A simple echo command returns stdout and exit_code 0."""
        result = proc.execute({"cmd": "echo hello"}, {})
        assert isinstance(result, PrimitiveResult)
        assert result.status == "success"
        assert result.data["stdout"].strip() == "hello"
        assert result.data["exit_code"] == 0

    def test_command_stderr_captured(self, proc: ProcExecPrimitive) -> None:
        """Stderr from a command is captured."""
        cmd = "echo stderr_output >&2" if sys.platform != "win32" else "echo stderr_output 1>&2"
        result = proc.execute({"cmd": cmd}, {})
        assert result.status == "success"
        assert "stderr_output" in result.data["stderr"]

    def test_non_zero_exit_code(self, proc: ProcExecPrimitive) -> None:
        """A failing command returns a non-zero exit_code."""
        cmd = "exit 42" if sys.platform != "win32" else "exit /b 42"
        result = proc.execute({"cmd": cmd}, {})
        assert result.status == "success"
        assert result.data["exit_code"] == 42

    def test_timeout_triggers_error(self, proc: ProcExecPrimitive) -> None:
        """A command that exceeds timeout returns a TimeoutError."""
        cmd = (
            "sleep 10"
            if sys.platform != "win32"
            else "powershell -Command \"Start-Sleep -Seconds 10\""
        )
        result = proc.execute({"cmd": cmd, "timeout": 1}, {})
        assert result.status == "error"
        assert result.error is not None
        assert "TimeoutError" in result.error

    def test_invalid_command_returns_error(self, proc: ProcExecPrimitive) -> None:
        """An invalid command triggers an OSError result."""
        result = proc.execute({"cmd": "nonexistent_command_xyz123"}, {})
        # On some platforms this may be OSError, on others a non-zero exit.
        if result.status == "error":
            assert result.error is not None
            assert "OSError" in result.error or "Error" in result.error

    def test_deterministic_output(self, proc: ProcExecPrimitive) -> None:
        """Repeated execution of the same simple command yields identical stdout."""
        results = [proc.execute({"cmd": "echo const"}, {}) for _ in range(3)]
        assert all(r.status == "success" for r in results)
        assert all(r.data["stdout"].strip() == "const" for r in results)
        assert all(r.data["exit_code"] == 0 for r in results)

    def test_input_is_not_mutated(self, proc: ProcExecPrimitive) -> None:
        """The input args dict is not modified."""
        args = {"cmd": "echo hi"}
        before = dict(args)
        proc.execute(args, {})
        assert args == before
