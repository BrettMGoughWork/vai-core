"""Tests for stdlib.sys.envlist primitive (Phase 3.18.8)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib.sys_envlist import SysEnvListPrimitive


@pytest.fixture
def sys_envlist() -> SysEnvListPrimitive:
    return SysEnvListPrimitive()


class TestSysEnvListPrimitive:
    """Tests for SysEnvListPrimitive.validate_args and execute."""

    def test_list_all_env(self, sys_envlist: SysEnvListPrimitive) -> None:
        result = sys_envlist.execute({}, {})
        assert result.status == "success"
        assert isinstance(result.data["variables"], dict)
        assert result.data["count"] > 0
        assert "PATH" in result.data["variables"]

    def test_list_with_prefix(self, sys_envlist: SysEnvListPrimitive) -> None:
        result = sys_envlist.execute({"prefix": "PATH"}, {})
        assert result.status == "success"
        assert "PATH" in result.data["variables"]
        # PATH is usually the only key with that prefix
        assert result.data["count"] >= 1

    def test_list_with_nonexistent_prefix(self, sys_envlist: SysEnvListPrimitive) -> None:
        result = sys_envlist.execute({"prefix": "ZZZ_NONEXISTENT_PREFIX_"}, {})
        assert result.data["variables"] == {}
        assert result.data["count"] == 0

    def test_prefix_not_string_raises_value_error(self, sys_envlist: SysEnvListPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            sys_envlist.validate_args({"prefix": 42})
