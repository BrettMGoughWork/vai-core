"""
Tests for Phase 3.21.3 — Planner Error Semantics
"""

from __future__ import annotations

import pytest

from src.agent.types.errors.planner_errors import (
    ALL_PLANNER_ERROR_TYPES,
    PlanAmbiguous,
    PlanDegraded,
    PlanExecutionFailed,
    PlanInvalid,
    PlanMissingCapabilities,
    PlannerError,
    PlanUnsafe,
)
from src.agent.types.errors.recovery import RecoveryAction, map_error_to_recovery


# ===========================================================================
# PlannerError base
# ===========================================================================

class TestPlannerErrorBase:
    def test_construction_minimal(self):
        e = PlannerError("something went wrong")
        assert e.message == "something went wrong"
        assert e.type == "PlannerError"
        assert e.plan_id is None
        assert e.retryable is False

    def test_construction_with_plan_id(self):
        e = PlannerError("fail", plan_id="plan-abc")
        assert e.plan_id == "plan-abc"
        assert "plan_id" in e.context

    def test_retryable_override(self):
        e = PlannerError("fail", retryable=True)
        assert e.retryable is True

    def test_context_merged(self):
        e = PlannerError("fail", context={"step": "3"}, plan_id="p1")
        assert e.context["step"] == "3"
        assert e.context["plan_id"] == "p1"

    def test_is_exception(self):
        e = PlannerError("fail")
        assert isinstance(e, Exception)

    def test_is_raisable(self):
        with pytest.raises(PlannerError):
            raise PlannerError("test")

    def test_str_is_message(self):
        e = PlannerError("something failed")
        assert "something failed" in str(e)

    def test_timestamp_set(self):
        e = PlannerError("fail")
        assert e.timestamp is not None


# ===========================================================================
# PlanInvalid
# ===========================================================================

class TestPlanInvalid:
    def test_default_not_retryable(self):
        e = PlanInvalid("circular dependency")
        assert e.retryable is False

    def test_type_name(self):
        e = PlanInvalid("bad plan")
        assert e.type == "PlanInvalid"

    def test_isinstance_hierarchy(self):
        e = PlanInvalid("bad plan")
        assert isinstance(e, PlannerError)
        assert isinstance(e, Exception)

    def test_recovery_is_replan(self):
        e = PlanInvalid("bad plan")
        assert map_error_to_recovery(e) == RecoveryAction.REPLAN


# ===========================================================================
# PlanAmbiguous
# ===========================================================================

class TestPlanAmbiguous:
    def test_default_not_retryable(self):
        e = PlanAmbiguous("unclear intent")
        assert e.retryable is False

    def test_type_name(self):
        e = PlanAmbiguous("unclear")
        assert e.type == "PlanAmbiguous"

    def test_isinstance_hierarchy(self):
        e = PlanAmbiguous("unclear")
        assert isinstance(e, PlannerError)

    def test_recovery_is_clarify(self):
        e = PlanAmbiguous("which file?")
        assert map_error_to_recovery(e) == RecoveryAction.CLARIFY


# ===========================================================================
# PlanMissingCapabilities
# ===========================================================================

class TestPlanMissingCapabilities:
    def test_default_not_retryable(self):
        e = PlanMissingCapabilities("missing primitives")
        assert e.retryable is False

    def test_type_name(self):
        e = PlanMissingCapabilities("missing")
        assert e.type == "PlanMissingCapabilities"

    def test_missing_capabilities_stored(self):
        e = PlanMissingCapabilities(
            "missing skills",
            missing_capabilities=("stdlib.db.query", "stdlib.file.watch"),
        )
        assert "stdlib.db.query" in e.missing_capabilities
        assert "stdlib.file.watch" in e.missing_capabilities

    def test_missing_capabilities_in_context(self):
        e = PlanMissingCapabilities(
            "missing skills",
            missing_capabilities=("stdlib.db.query",),
        )
        assert "missing_capabilities" in e.context
        assert "stdlib.db.query" in e.context["missing_capabilities"]

    def test_empty_missing_capabilities(self):
        e = PlanMissingCapabilities("missing")
        assert e.missing_capabilities == ()

    def test_recovery_is_replan(self):
        e = PlanMissingCapabilities("missing primitives")
        assert map_error_to_recovery(e) == RecoveryAction.REPLAN

    def test_isinstance_hierarchy(self):
        e = PlanMissingCapabilities("missing")
        assert isinstance(e, PlannerError)


# ===========================================================================
# PlanUnsafe
# ===========================================================================

class TestPlanUnsafe:
    def test_default_not_retryable(self):
        e = PlanUnsafe("safety violation")
        assert e.retryable is False

    def test_type_name(self):
        e = PlanUnsafe("unsafe")
        assert e.type == "PlanUnsafe"

    def test_violated_rule_stored(self):
        e = PlanUnsafe("deletes system files", violated_rule="no-system-delete")
        assert e.violated_rule == "no-system-delete"
        assert e.context["violated_rule"] == "no-system-delete"

    def test_violated_rule_optional(self):
        e = PlanUnsafe("unsafe")
        assert e.violated_rule is None

    def test_recovery_is_escalate(self):
        e = PlanUnsafe("safety violation")
        assert map_error_to_recovery(e) == RecoveryAction.ESCALATE

    def test_isinstance_hierarchy(self):
        e = PlanUnsafe("unsafe")
        assert isinstance(e, PlannerError)


# ===========================================================================
# PlanExecutionFailed
# ===========================================================================

class TestPlanExecutionFailed:
    def test_default_retryable(self):
        e = PlanExecutionFailed("step failed")
        assert e.retryable is True

    def test_type_name(self):
        e = PlanExecutionFailed("failed")
        assert e.type == "PlanExecutionFailed"

    def test_failed_step_stored(self):
        e = PlanExecutionFailed("network error", failed_step="fetch_data")
        assert e.failed_step == "fetch_data"
        assert e.context["failed_step"] == "fetch_data"

    def test_failed_step_optional(self):
        e = PlanExecutionFailed("failed")
        assert e.failed_step is None

    def test_recovery_retry_when_retryable(self):
        e = PlanExecutionFailed("transient", retryable=True)
        assert map_error_to_recovery(e) == RecoveryAction.RETRY

    def test_recovery_replan_when_not_retryable(self):
        e = PlanExecutionFailed("permanent", retryable=False)
        assert map_error_to_recovery(e) == RecoveryAction.REPLAN

    def test_recovery_default_is_retry(self):
        e = PlanExecutionFailed("failed")
        assert map_error_to_recovery(e) == RecoveryAction.RETRY

    def test_isinstance_hierarchy(self):
        e = PlanExecutionFailed("failed")
        assert isinstance(e, PlannerError)


# ===========================================================================
# PlanDegraded
# ===========================================================================

class TestPlanDegraded:
    def test_default_retryable(self):
        e = PlanDegraded("fallback used")
        assert e.retryable is True

    def test_type_name(self):
        e = PlanDegraded("degraded")
        assert e.type == "PlanDegraded"

    def test_fallback_used_stored(self):
        e = PlanDegraded("used slow path", fallback_used="slow_read_skill")
        assert e.fallback_used == "slow_read_skill"
        assert e.context["fallback_used"] == "slow_read_skill"

    def test_fallback_used_optional(self):
        e = PlanDegraded("degraded")
        assert e.fallback_used is None

    def test_recovery_is_retry(self):
        e = PlanDegraded("fallback used")
        assert map_error_to_recovery(e) == RecoveryAction.RETRY

    def test_isinstance_hierarchy(self):
        e = PlanDegraded("degraded")
        assert isinstance(e, PlannerError)


# ===========================================================================
# ALL_PLANNER_ERROR_TYPES catalogue
# ===========================================================================

class TestAllPlannerErrorTypes:
    def test_contains_all_six_types(self):
        expected = {
            PlanInvalid,
            PlanAmbiguous,
            PlanMissingCapabilities,
            PlanUnsafe,
            PlanExecutionFailed,
            PlanDegraded,
        }
        assert set(ALL_PLANNER_ERROR_TYPES) == expected

    def test_all_are_planner_error_subclasses(self):
        for cls in ALL_PLANNER_ERROR_TYPES:
            assert issubclass(cls, PlannerError)

    def test_all_are_exception_subclasses(self):
        for cls in ALL_PLANNER_ERROR_TYPES:
            assert issubclass(cls, Exception)

    def test_all_have_recovery_mapping(self):
        for cls in ALL_PLANNER_ERROR_TYPES:
            e = cls("test")
            action = map_error_to_recovery(e)
            assert isinstance(action, RecoveryAction)


# ===========================================================================
# Recovery mapping completeness
# ===========================================================================

class TestPlannerErrorRecoveryMapping:
    @pytest.mark.parametrize(
        "cls,expected",
        [
            (PlanInvalid, RecoveryAction.REPLAN),
            (PlanAmbiguous, RecoveryAction.CLARIFY),
            (PlanMissingCapabilities, RecoveryAction.REPLAN),
            (PlanUnsafe, RecoveryAction.ESCALATE),
            (PlanDegraded, RecoveryAction.RETRY),
        ],
    )
    def test_recovery_mapping(self, cls, expected):
        e = cls("test")
        assert map_error_to_recovery(e) == expected

    def test_plan_execution_failed_retryable_true(self):
        assert (
            map_error_to_recovery(PlanExecutionFailed("t", retryable=True))
            == RecoveryAction.RETRY
        )

    def test_plan_execution_failed_retryable_false(self):
        assert (
            map_error_to_recovery(PlanExecutionFailed("t", retryable=False))
            == RecoveryAction.REPLAN
        )


# ===========================================================================
# Exports from __init__
# ===========================================================================

class TestPlannerErrorExports:
    def test_importable_from_package(self):
        from src.agent.types.errors import (
            PlannerError,
            PlanInvalid,
            PlanAmbiguous,
            PlanMissingCapabilities,
            PlanUnsafe,
            PlanExecutionFailed,
            PlanDegraded,
            ALL_PLANNER_ERROR_TYPES,
        )
        assert PlannerError is not None
        assert len(ALL_PLANNER_ERROR_TYPES) == 6