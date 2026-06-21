"""Tests for the deferral chain depth guard."""

import pytest

from src.agent.deferral.depth_guard import DeferralDepthError, DepthGuard


class TestDepthGuard:
    """Depth limiting for deferral chains."""

    def test_default_max_depth_is_3(self):
        guard = DepthGuard()
        assert guard.max_depth == 3

    def test_custom_max_depth(self):
        guard = DepthGuard(max_depth=5)
        assert guard.max_depth == 5

    def test_zero_depth_passes(self):
        guard = DepthGuard()
        guard.check(0)

    def test_depth_within_limit_passes(self):
        guard = DepthGuard(max_depth=3)
        guard.check(0)
        guard.check(1)
        guard.check(2)

    def test_depth_at_limit_raises(self):
        guard = DepthGuard(max_depth=3)
        with pytest.raises(DeferralDepthError):
            guard.check(3)

    def test_depth_beyond_limit_raises(self):
        guard = DepthGuard(max_depth=3)
        with pytest.raises(DeferralDepthError):
            guard.check(5)

    def test_max_depth_cannot_be_zero(self):
        with pytest.raises(ValueError, match=">= 1"):
            DepthGuard(max_depth=0)

    def test_max_depth_cannot_be_negative(self):
        with pytest.raises(ValueError, match=">= 1"):
            DepthGuard(max_depth=-1)

    def test_get_next_depth_increments(self):
        guard = DepthGuard()
        assert guard.get_next_depth(0) == 1
        assert guard.get_next_depth(1) == 2

    def test_get_next_depth_raises_at_limit(self):
        guard = DepthGuard(max_depth=2)
        guard.get_next_depth(0)  # -> 1, ok
        with pytest.raises(DeferralDepthError):
            guard.get_next_depth(1)  # -> 2, at limit

    def test_error_message_includes_depth_info(self):
        guard = DepthGuard(max_depth=2)
        with pytest.raises(DeferralDepthError) as exc:
            guard.check(2)
        msg = str(exc.value)
        assert "depth=2" in msg
        assert "max=2" in msg
