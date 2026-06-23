"""
Tests for Phase 3.21.1 — Primitive Error Taxonomy
"""

from __future__ import annotations

import pytest

from src.strategy.types.errors import (
    ALL_PRIMITIVE_ERROR_TYPES,
    PrimitiveContractError,
    PrimitiveDependencyError,
    PrimitiveEnvironmentError,
    PrimitiveError,
    PrimitiveExecutionError,
    PrimitiveNonRetryableError,
    PrimitiveNotFound,
    PrimitivePrivilegeError,
    PrimitiveRetryableError,
    PrimitiveSideEffectError,
    PrimitiveTimeout,
    PrimitiveValidationError,
    RecoveryAction,
    map_error_to_recovery,
)
from src.strategy.types.errors.AgentError import AgentError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make(cls, primitive_name="stdlib.test", message="test error", **kwargs):
    return cls(primitive_name=primitive_name, message=message, **kwargs)


# ===========================================================================
# Inheritance & interface
# ===========================================================================

class TestPrimitiveErrorInheritance:
    def test_is_exception(self):
        err = _make(PrimitiveExecutionError)
        assert isinstance(err, Exception)

    def test_is_agent_error(self):
        err = _make(PrimitiveExecutionError)
        assert isinstance(err, AgentError)

    def test_is_primitive_error(self):
        err = _make(PrimitiveExecutionError)
        assert isinstance(err, PrimitiveError)

    def test_all_subtypes_are_primitive_error(self):
        for cls in ALL_PRIMITIVE_ERROR_TYPES:
            err = _make(cls)
            assert isinstance(err, PrimitiveError), f"{cls.__name__} is not a PrimitiveError"

    def test_can_be_raised_and_caught_as_exception(self):
        with pytest.raises(PrimitiveError):
            raise _make(PrimitiveExecutionError)

    def test_can_be_caught_as_base_exception(self):
        with pytest.raises(Exception):
            raise _make(PrimitiveNotFound)

    def test_is_agent_error_instance(self):
        err = _make(PrimitivePrivilegeError)
        assert isinstance(err, AgentError)


# ===========================================================================
# Construction & fields
# ===========================================================================

class TestPrimitiveErrorConstruction:
    def test_primitive_name_stored(self):
        err = _make(PrimitiveExecutionError, primitive_name="stdlib.file.read")
        assert err.primitive_name == "stdlib.file.read"

    def test_message_stored(self):
        err = _make(PrimitiveExecutionError, message="something broke")
        assert err.message == "something broke"

    def test_primitive_name_in_details(self):
        err = _make(PrimitiveExecutionError, primitive_name="cap.x")
        assert err.details["primitive_name"] == "cap.x"

    def test_extra_details_merged(self):
        err = _make(PrimitiveExecutionError, details={"input_key": "val"})
        assert err.details["input_key"] == "val"
        assert "primitive_name" in err.details

    def test_type_field_matches_class_name(self):
        for cls in ALL_PRIMITIVE_ERROR_TYPES:
            err = _make(cls)
            assert err.type == cls.__name__, f"{cls.__name__}: type={err.type!r}"

    def test_timestamp_set(self):
        err = _make(PrimitiveExecutionError)
        assert err.timestamp  # non-empty ISO string

    def test_str_includes_class_name_and_primitive(self):
        err = _make(PrimitiveTimeout, primitive_name="cap.slow")
        s = str(err)
        assert "PrimitiveTimeout" in s
        assert "cap.slow" in s


# ===========================================================================
# Default retryable semantics
# ===========================================================================

class TestDefaultRetryableSemantics:
    @pytest.mark.parametrize("cls", [
        PrimitiveRetryableError,
        PrimitiveTimeout,
        PrimitiveDependencyError,
    ])
    def test_retryable_by_default(self, cls):
        err = _make(cls)
        assert err.retryable is True
        assert err.recoverable is True

    @pytest.mark.parametrize("cls", [
        PrimitiveExecutionError,
        PrimitiveNonRetryableError,
        PrimitiveSideEffectError,
        PrimitiveValidationError,
        PrimitiveContractError,
        PrimitivePrivilegeError,
        PrimitiveEnvironmentError,
        PrimitiveNotFound,
    ])
    def test_not_retryable_by_default(self, cls):
        err = _make(cls)
        assert err.retryable is False
        assert err.recoverable is False

    def test_retryable_override_to_true(self):
        err = _make(PrimitiveExecutionError, retryable=True)
        assert err.retryable is True

    def test_retryable_override_to_false(self):
        err = _make(PrimitiveRetryableError, retryable=False)
        assert err.retryable is False


# ===========================================================================
# Recovery mapping
# ===========================================================================

class TestPrimitiveRecoveryMapping:
    @pytest.mark.parametrize("cls", [
        PrimitiveRetryableError,
        PrimitiveTimeout,
        PrimitiveDependencyError,
    ])
    def test_retry_types_map_to_retry(self, cls):
        err = _make(cls)
        assert map_error_to_recovery(err) == RecoveryAction.RETRY

    @pytest.mark.parametrize("cls", [
        PrimitiveNonRetryableError,
        PrimitiveValidationError,
        PrimitiveContractError,
        PrimitiveNotFound,
    ])
    def test_replan_types_map_to_replan(self, cls):
        err = _make(cls)
        assert map_error_to_recovery(err) == RecoveryAction.REPLAN

    @pytest.mark.parametrize("cls", [
        PrimitiveSideEffectError,
        PrimitivePrivilegeError,
        PrimitiveEnvironmentError,
    ])
    def test_escalate_types_map_to_escalate(self, cls):
        err = _make(cls)
        assert map_error_to_recovery(err) == RecoveryAction.ESCALATE

    def test_execution_error_retryable_true_maps_to_retry(self):
        err = _make(PrimitiveExecutionError, retryable=True)
        assert map_error_to_recovery(err) == RecoveryAction.RETRY

    def test_execution_error_retryable_false_maps_to_replan(self):
        err = _make(PrimitiveExecutionError, retryable=False)
        assert map_error_to_recovery(err) == RecoveryAction.REPLAN

    def test_all_types_have_a_recovery_mapping(self):
        for cls in ALL_PRIMITIVE_ERROR_TYPES:
            err = _make(cls)
            result = map_error_to_recovery(err)
            assert isinstance(result, RecoveryAction), (
                f"{cls.__name__} produced no RecoveryAction"
            )


# ===========================================================================
# AgentError interface compatibility
# ===========================================================================

class TestAgentErrorCompatibility:
    def test_to_dict_contains_required_keys(self):
        err = _make(PrimitiveValidationError)
        d = err.to_dict()
        assert "type" in d
        assert "message" in d
        assert "details" in d
        assert "timestamp" in d
        assert "recoverable" in d

    def test_to_dict_type_matches_class_name(self):
        err = _make(PrimitiveNotFound, primitive_name="cap.missing")
        assert err.to_dict()["type"] == "PrimitiveNotFound"

    def test_recoverable_matches_retryable(self):
        for cls in ALL_PRIMITIVE_ERROR_TYPES:
            err = _make(cls)
            assert err.recoverable == err.retryable, (
                f"{cls.__name__}: recoverable={err.recoverable} != retryable={err.retryable}"
            )


# ===========================================================================
# ALL_PRIMITIVE_ERROR_TYPES completeness
# ===========================================================================

class TestAllPrimitiveErrorTypes:
    def test_contains_all_eleven_types(self):
        assert len(ALL_PRIMITIVE_ERROR_TYPES) == 11

    def test_no_duplicates(self):
        assert len(set(ALL_PRIMITIVE_ERROR_TYPES)) == len(ALL_PRIMITIVE_ERROR_TYPES)

    def test_all_are_primitive_error_subclasses(self):
        for cls in ALL_PRIMITIVE_ERROR_TYPES:
            assert issubclass(cls, PrimitiveError)