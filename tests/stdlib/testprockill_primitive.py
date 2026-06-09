"""Tests for stdlib.proc.kill primitive (Phase 3.18.9)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.proc_kill import ProcKillPrimitive


@pytest.fixture
def proc_kill() -> ProcKillPrimitive:
    return ProcKillPrimitive()


class TestProcKillPrimitive:
    """Tests for ProcKillPrimitive.validate_args and execute."""

    def test_kill_nonexistent_process(self, proc_kill: ProcKillPrimitive) -> None:
        result = proc_kill.execute({"pid": 99999999}, {})
        assert result.status == "error"

    def test_kill_negative_pid_raises_value_error(self, proc_kill: ProcKillPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a positive integer"):
            proc_kill.validate_args({"pid": -1})

    def test_kill_zero_pid_raises_value_error(self, proc_kill: ProcKillPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a positive integer"):
            proc_kill.validate_args({"pid": 0})

    def test_missing_pid_raises_value_error(self, proc_kill: ProcKillPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'pid'"):
            proc_kill.validate_args({})

    def test_pid_not_int_raises_value_error(self, proc_kill: ProcKillPrimitive) -> None:
        with pytest.raises(ValueError, match="must be an integer"):
            proc_kill.validate_args({"pid": "999"})

    def test_signal_not_int_raises_value_error(self, proc_kill: ProcKillPrimitive) -> None:
        with pytest.raises(ValueError, match="must be an integer"):
            proc_kill.validate_args({"pid": 1234, "signal": "SIGTERM"})
