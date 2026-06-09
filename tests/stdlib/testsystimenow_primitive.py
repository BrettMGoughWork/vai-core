"""Tests for stdlib.sys.timenow primitive (Phase 3.18.8)."""

from __future__ import annotations

import time

import pytest

from src.capabilities.primitives.stdlib.sys_timenow import SysTimeNowPrimitive


@pytest.fixture
def sys_timenow() -> SysTimeNowPrimitive:
    return SysTimeNowPrimitive()


class TestSysTimeNowPrimitive:
    """Tests for SysTimeNowPrimitive.validate_args and execute."""

    def test_default_iso8601(self, sys_timenow: SysTimeNowPrimitive) -> None:
        result = sys_timenow.execute({}, {})
        assert result.status == "success"
        assert "T" in result.data["datetime"]  # ISO format
        assert result.data["timestamp"] > 0
        assert result.data["timestamp_ms"] > 0

    def test_unix_format(self, sys_timenow: SysTimeNowPrimitive) -> None:
        result = sys_timenow.execute({"format": "unix"}, {})
        assert isinstance(result.data["formatted"], int)

    def test_unix_ms_format(self, sys_timenow: SysTimeNowPrimitive) -> None:
        result = sys_timenow.execute({"format": "unix_ms"}, {})
        assert isinstance(result.data["formatted"], int)
        assert result.data["formatted"] > 1_000_000_000_000

    def test_readable_format(self, sys_timenow: SysTimeNowPrimitive) -> None:
        result = sys_timenow.execute({"format": "readable"}, {})
        assert "UTC" in result.data["formatted"]

    def test_custom_strftime(self, sys_timenow: SysTimeNowPrimitive) -> None:
        result = sys_timenow.execute({"format": "%Y-%m-%d"}, {})
        import datetime
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        assert result.data["formatted"] == today

    def test_timestamp_near_now(self, sys_timenow: SysTimeNowPrimitive) -> None:
        before = int(time.time())
        result = sys_timenow.execute({}, {})
        after = int(time.time())
        assert before <= result.data["timestamp"] <= after + 1

    def test_format_not_string_raises_value_error(self, sys_timenow: SysTimeNowPrimitive) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            sys_timenow.validate_args({"format": 123})
