"""Tests for stdlib.sys.envget primitive (Phase 3.18.8)."""

from __future__ import annotations

import os

import pytest

from src.capabilities.primitives.stdlib.sys_envget import SysEnvGetPrimitive


@pytest.fixture
def sys_envget() -> SysEnvGetPrimitive:
    return SysEnvGetPrimitive()


class TestSysEnvGetPrimitive:
    """Tests for SysEnvGetPrimitive.validate_args and execute."""

    def test_get_existing_var(self, sys_envget: SysEnvGetPrimitive) -> None:
        result = sys_envget.execute({"key": "PATH"}, {})
        assert result.status == "success"
        assert result.data["found"] is True
        assert result.data["value"] is not None

    def test_get_missing_var_with_default(self, sys_envget: SysEnvGetPrimitive) -> None:
        result = sys_envget.execute({"key": "NONEXISTENT_VAR_XYZ", "default": "fallback"}, {})
        assert result.status == "success"
        assert result.data["value"] == "fallback"
        assert result.data["found"] is True

    def test_get_missing_var_no_default(self, sys_envget: SysEnvGetPrimitive) -> None:
        result = sys_envget.execute({"key": "NONEXISTENT_VAR_XYZ"}, {})
        assert result.status == "success"
        assert result.data["value"] is None
        assert result.data["found"] is False

    def test_set_and_get_var(self, sys_envget: SysEnvGetPrimitive) -> None:
        os.environ["VAI_TEST_VAR"] = "test_value"
        try:
            result = sys_envget.execute({"key": "VAI_TEST_VAR"}, {})
            assert result.data["value"] == "test_value"
        finally:
            del os.environ["VAI_TEST_VAR"]

    def test_missing_key_raises_value_error(self, sys_envget: SysEnvGetPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'key'"):
            sys_envget.validate_args({})

    def test_empty_key_raises_value_error(self, sys_envget: SysEnvGetPrimitive) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            sys_envget.validate_args({"key": ""})

    def test_key_not_string_raises_value_error(self, sys_envget: SysEnvGetPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            sys_envget.validate_args({"key": 123})
