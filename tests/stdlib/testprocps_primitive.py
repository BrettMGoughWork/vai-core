"""Tests for stdlib.proc.ps primitive (Phase 3.18.9)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.proc_ps import ProcPsPrimitive


@pytest.fixture
def proc_ps() -> ProcPsPrimitive:
    return ProcPsPrimitive()


class TestProcPsPrimitive:
    """Tests for ProcPsPrimitive.validate_args and execute."""

    def test_list_processes(self, proc_ps: ProcPsPrimitive) -> None:
        result = proc_ps.execute({}, {})
        assert result.status == "success"
        assert isinstance(result.data["processes"], list)
        assert result.data["count"] > 0

    def test_list_with_name_filter(self, proc_ps: ProcPsPrimitive) -> None:
        import sys
        result = proc_ps.execute({"name_filter": "python"}, {})
        assert result.status == "success"
        for proc in result.data["processes"]:
            assert "python" in proc["name"].lower()

    def test_list_with_limit(self, proc_ps: ProcPsPrimitive) -> None:
        result = proc_ps.execute({"limit": 3}, {})
        assert result.status == "success"
        assert len(result.data["processes"]) <= 3

    def test_name_filter_not_string_raises_value_error(self, proc_ps: ProcPsPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            proc_ps.validate_args({"name_filter": 42})

    def test_limit_not_int_raises_value_error(self, proc_ps: ProcPsPrimitive) -> None:
        with pytest.raises(ValueError, match="must be an integer"):
            proc_ps.validate_args({"limit": "ten"})
