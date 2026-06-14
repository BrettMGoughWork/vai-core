"""Tests for S4.8.4 Health Checks — HealthResponse, check_liveness(),
check_readiness(), check_worker_pool_health(), registration API.

Covers:
- HealthResponse schema
- init_health / mark_shutdown
- check_liveness with various states (uninitialized, shutdown, ok)
- check_readiness with conditions (liveness fail, queue depth, panic, health, degraded)
- check_worker_pool_health (unregistered, error, unhealthy mix, no workers, healthy)
- clear_registrations
"""

from __future__ import annotations

import pytest

from src.platform.observability import health as mod


# ------------------------------------------------------------------
# HealthResponse
# ------------------------------------------------------------------


class TestHealthResponse:
    def _make(self, status: str = "ok", details: dict | None = None):
        return mod.HealthResponse(status, "2026-01-01T00:00:00", "test", details or {})

    def test_default_status(self):
        r = self._make()
        assert r.status == "ok"

    def test_ok_status(self):
        r = self._make("ok", {"liveness": "ok"})
        assert r.status == "ok"

    def test_degraded_status(self):
        r = self._make("degraded", {"queue_depth": "100"})
        assert r.status == "degraded"

    def test_unhealthy_status(self):
        r = self._make("unhealthy", {"liveness": "fail", "readiness": "fail"})
        assert r.status == "unhealthy"

    def test_invalid_status_defaults_to_unhealthy(self):
        r = self._make("bogus")
        assert r.status == "unhealthy"

    def test_to_dict_shape(self):
        r = mod.HealthResponse("ok", "2026-01-01T00:00:00", "s4", {"reason": "running"})
        d = r.to_dict()
        assert d["status"] == "ok"
        assert d["timestamp"] == "2026-01-01T00:00:00"
        assert d["component"] == "s4"
        assert d["details"] == {"reason": "running"}


# ------------------------------------------------------------------
# check_liveness
# ------------------------------------------------------------------


class TestCheckLiveness:
    def test_uninitialized_fails(self):
        mod.clear_registrations()
        try:
            result = mod.check_liveness()
            assert result.status == "unhealthy"
        finally:
            mod.clear_registrations()

    def test_shutdown_fails(self):
        mod.clear_registrations()
        try:
            mod.init_health()
            mod.mark_shutdown()
            result = mod.check_liveness()
            assert result.status == "unhealthy"
        finally:
            mod.clear_registrations()

    def test_substrate_unreachable_fails(self):
        mod.clear_registrations()
        mod.init_health()
        mod.register_liveness_substrate(lambda: False)
        try:
            result = mod.check_liveness()
            assert result.status == "unhealthy"
        finally:
            mod.clear_registrations()

    def test_all_checks_pass(self):
        mod.clear_registrations()
        mod.init_health()
        mod.register_liveness_substrate(lambda: True)
        try:
            result = mod.check_liveness()
            assert result.status == "ok"
        finally:
            mod.clear_registrations()


# ------------------------------------------------------------------
# check_readiness
# ------------------------------------------------------------------


class TestCheckReadiness:
    def test_readiness_fails_if_liveness_fails(self):
        mod.clear_registrations()
        mod.init_health()
        mod.register_liveness_substrate(lambda: False)
        try:
            result = mod.check_readiness()
            assert result.status == "unhealthy"
        finally:
            mod.clear_registrations()

    def test_queue_depth_warning(self):
        mod.clear_registrations()
        mod.init_health()
        mod.register_liveness_substrate(lambda: True)
        mod.register_queue_depth(lambda: 51)
        try:
            result = mod.check_readiness()
            assert result.status == "degraded"
        finally:
            mod.clear_registrations()

    def test_queue_depth_ok(self):
        mod.clear_registrations()
        mod.init_health()
        mod.register_liveness_substrate(lambda: True)
        mod.register_queue_depth(lambda: 10)
        try:
            result = mod.check_readiness()
            assert result.status == "ok"
        finally:
            mod.clear_registrations()

    def test_panic_guard_triggers_unhealthy(self):
        mod.clear_registrations()
        mod.init_health()
        mod.register_liveness_substrate(lambda: True)
        mod.register_queue_depth(lambda: 5)
        mod.register_panic_active(lambda: True)
        try:
            result = mod.check_readiness()
            assert result.status == "unhealthy"
        finally:
            mod.clear_registrations()

    def test_all_workers_unhealthy_returns_unhealthy(self):
        mod.clear_registrations()
        mod.init_health()
        mod.register_liveness_substrate(lambda: True)
        mod.register_queue_depth(lambda: 5)
        mod.register_supervisor_health(
            lambda: {"healthy": 0, "unhealthy": 3, "total": 3}
        )
        try:
            result = mod.check_readiness()
            assert result.status == "unhealthy"
        finally:
            mod.clear_registrations()

    def test_mixed_worker_health_degrades(self):
        mod.clear_registrations()
        mod.init_health()
        mod.register_liveness_substrate(lambda: True)
        mod.register_queue_depth(lambda: 5)
        mod.register_supervisor_health(
            lambda: {"healthy": 3, "unhealthy": 2, "total": 5}
        )
        try:
            result = mod.check_readiness()
            assert result.status == "degraded"
        finally:
            mod.clear_registrations()

    def test_all_checks_pass_returns_ok(self):
        mod.clear_registrations()
        mod.init_health()
        mod.register_liveness_substrate(lambda: True)
        mod.register_queue_depth(lambda: 5)
        mod.register_supervisor_health(
            lambda: {"healthy": 5, "unhealthy": 0, "total": 5}
        )
        try:
            result = mod.check_readiness()
            assert result.status == "ok"
        finally:
            mod.clear_registrations()


# ------------------------------------------------------------------
# check_worker_pool_health
# ------------------------------------------------------------------


class TestCheckWorkerPoolHealth:
    def test_unregistered(self):
        mod.clear_registrations()
        try:
            result = mod.check_worker_pool_health()
            assert result.status == "unhealthy"
        finally:
            mod.clear_registrations()

    def test_detail_provider_raises_error(self):
        mod.clear_registrations()
        mod.init_health()

        def _broken():
            raise RuntimeError("boom")

        mod.register_worker_pool_detail(_broken)
        try:
            result = mod.check_worker_pool_health()
            assert result.status == "unhealthy"
        finally:
            mod.clear_registrations()

    def test_all_workers_unhealthy(self):
        mod.clear_registrations()
        mod.init_health()
        mod.register_worker_pool_detail(
            lambda: {
                "total_workers": 5,
                "healthy_workers": 0,
                "unhealthy_workers": 5,
            }
        )
        try:
            result = mod.check_worker_pool_health()
            assert result.status == "unhealthy"
        finally:
            mod.clear_registrations()

    def test_mixed_health(self):
        mod.clear_registrations()
        mod.init_health()
        mod.register_worker_pool_detail(
            lambda: {
                "total_workers": 5,
                "healthy_workers": 3,
                "unhealthy_workers": 2,
            }
        )
        try:
            result = mod.check_worker_pool_health()
            assert result.status == "degraded"
        finally:
            mod.clear_registrations()

    def test_no_workers(self):
        mod.clear_registrations()
        mod.init_health()
        mod.register_worker_pool_detail(
            lambda: {
                "total_workers": 0,
                "healthy_workers": 0,
                "unhealthy_workers": 0,
            }
        )
        try:
            result = mod.check_worker_pool_health()
            assert result.status == "degraded"
        finally:
            mod.clear_registrations()

    def test_all_healthy(self):
        mod.clear_registrations()
        mod.init_health()
        mod.register_worker_pool_detail(
            lambda: {
                "total_workers": 5,
                "healthy_workers": 5,
                "unhealthy_workers": 0,
            }
        )
        try:
            result = mod.check_worker_pool_health()
            assert result.status == "ok"
        finally:
            mod.clear_registrations()


# ------------------------------------------------------------------
# Registration API
# ------------------------------------------------------------------


class TestRegistrationAPI:
    def test_init_health_and_clear(self):
        mod.clear_registrations()

        assert mod.check_liveness().status == "unhealthy"

        mod.init_health()
        mod.register_liveness_substrate(lambda: True)
        assert mod.check_liveness().status == "ok"

        mod.clear_registrations()
        assert mod.check_liveness().status == "unhealthy"

    def test_register_liveness_substrate_invoked_during_liveness(self):
        mod.clear_registrations()
        mod.init_health()
        called = False

        def _check():
            nonlocal called
            called = True
            return True

        mod.register_liveness_substrate(_check)
        mod.check_liveness()
        assert called
        mod.clear_registrations()

    def test_register_queue_depth_invoked_during_readiness(self):
        mod.clear_registrations()
        mod.init_health()
        called = False

        def _check():
            nonlocal called
            called = True
            return 5

        mod.register_queue_depth(_check)
        mod.check_readiness()
        assert called
        mod.clear_registrations()

    def test_register_worker_pool_detail_invoked_during_pool_check(self):
        mod.clear_registrations()
        mod.init_health()
        called = False

        def _check():
            nonlocal called
            called = True
            return {
                "total_workers": 1,
                "healthy_workers": 1,
                "unhealthy_workers": 0,
            }

        mod.register_worker_pool_detail(_check)
        mod.check_worker_pool_health()
        assert called
        mod.clear_registrations()
