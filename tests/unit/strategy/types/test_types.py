"""Tests for src.strategy.types — CognitiveStepOutcome and StepResult."""
import pytest
from dataclasses import FrozenInstanceError

from src.strategy.types.cognitive_step_outcome import CognitiveStepOutcome
from src.strategy.types.step_result import StepResult
from src.strategy.types.errors.ValidationError import ValidationError


# ── CognitiveStepOutcome ──────────────────────────────────────────────────────

class TestCognitiveStepOutcome:
    def test_all_variants_exist(self):
        assert CognitiveStepOutcome.SUCCESS
        assert CognitiveStepOutcome.FAILURE
        assert CognitiveStepOutcome.TOOL_NEEDED
        assert CognitiveStepOutcome.CONTINUE

    def test_enum_values_are_strings(self):
        assert CognitiveStepOutcome.SUCCESS.value == "success"
        assert CognitiveStepOutcome.FAILURE.value == "failure"
        assert CognitiveStepOutcome.TOOL_NEEDED.value == "tool_needed"
        assert CognitiveStepOutcome.CONTINUE.value == "continue"

    def test_variants_are_distinct(self):
        variants = [CognitiveStepOutcome.SUCCESS, CognitiveStepOutcome.FAILURE, CognitiveStepOutcome.TOOL_NEEDED, CognitiveStepOutcome.CONTINUE]
        assert len(set(variants)) == 4

    def test_lookup_by_value(self):
        assert CognitiveStepOutcome("success") is CognitiveStepOutcome.SUCCESS
        assert CognitiveStepOutcome("failure") is CognitiveStepOutcome.FAILURE
        assert CognitiveStepOutcome("tool_needed") is CognitiveStepOutcome.TOOL_NEEDED
        assert CognitiveStepOutcome("continue") is CognitiveStepOutcome.CONTINUE


# ── StepResult construction ───────────────────────────────────────────────────

class TestStepResultConstruction:
    def test_minimal_construction(self):
        result = StepResult(outcome=CognitiveStepOutcome.SUCCESS, reason="ok")

        assert result.outcome is CognitiveStepOutcome.SUCCESS
        assert result.reason == "ok"

    def test_payload_defaults_to_empty_dict(self):
        result = StepResult(outcome=CognitiveStepOutcome.SUCCESS, reason="ok")

        assert result.payload == {}

    def test_trace_defaults_to_empty_dict(self):
        result = StepResult(outcome=CognitiveStepOutcome.SUCCESS, reason="ok")

        assert result.trace == {}

    def test_explicit_payload_stored(self):
        result = StepResult(outcome=CognitiveStepOutcome.SUCCESS, reason="ok", payload={"key": "value"})

        assert result.payload == {"key": "value"}

    def test_all_four_outcomes_construct(self):
        for outcome in CognitiveStepOutcome:
            result = StepResult(outcome=outcome, reason="r")
            assert result.outcome is outcome

    def test_is_frozen(self):
        result = StepResult(outcome=CognitiveStepOutcome.SUCCESS, reason="ok")

        with pytest.raises(FrozenInstanceError):
            result.reason = "changed"

    def test_canonical_hash_present_after_construction(self):
        result = StepResult(outcome=CognitiveStepOutcome.SUCCESS, reason="ok")

        assert isinstance(result.canonical_hash, str)
        assert len(result.canonical_hash) == 64  # SHA-256 hex


# ── StepResult.failure() factory ─────────────────────────────────────────────

class TestStepResultFailureFactory:
    def test_outcome_is_failure(self):
        result = StepResult.failure("something went wrong")

        assert result.outcome is CognitiveStepOutcome.FAILURE

    def test_reason_is_set(self):
        result = StepResult.failure("timeout exceeded")

        assert result.reason == "timeout exceeded"

    def test_payload_defaults_to_empty_dict(self):
        result = StepResult.failure("err")

        assert result.payload == {}

    def test_trace_defaults_to_empty_list(self):
        result = StepResult.failure("err")

        assert result.trace == []

    def test_explicit_payload_stored(self):
        result = StepResult.failure("err", payload={"code": 404})

        assert result.payload == {"code": 404}

    def test_explicit_trace_stored(self):
        result = StepResult.failure("err", trace=["step-1", "step-2"])

        assert result.trace == ["step-1", "step-2"]


# ── StepResult canonical_hash ─────────────────────────────────────────────────

class TestStepResultCanonicalHash:
    def test_hash_is_stable_for_same_inputs(self):
        r1 = StepResult(outcome=CognitiveStepOutcome.SUCCESS, reason="ok", payload={"x": 1})
        r2 = StepResult(outcome=CognitiveStepOutcome.SUCCESS, reason="ok", payload={"x": 1})

        assert r1.canonical_hash == r2.canonical_hash

    def test_hash_differs_when_outcome_changes(self):
        r1 = StepResult(outcome=CognitiveStepOutcome.SUCCESS, reason="ok")
        r2 = StepResult(outcome=CognitiveStepOutcome.FAILURE, reason="ok")

        assert r1.canonical_hash != r2.canonical_hash

    def test_hash_differs_when_reason_changes(self):
        r1 = StepResult(outcome=CognitiveStepOutcome.SUCCESS, reason="a")
        r2 = StepResult(outcome=CognitiveStepOutcome.SUCCESS, reason="b")

        assert r1.canonical_hash != r2.canonical_hash

    def test_hash_differs_when_payload_changes(self):
        r1 = StepResult(outcome=CognitiveStepOutcome.SUCCESS, reason="ok", payload={"x": 1})
        r2 = StepResult(outcome=CognitiveStepOutcome.SUCCESS, reason="ok", payload={"x": 2})

        assert r1.canonical_hash != r2.canonical_hash

    def test_hash_is_stable_across_trace_change(self):
        # trace is intentionally excluded from identity hash
        r1 = StepResult(outcome=CognitiveStepOutcome.SUCCESS, reason="ok", trace={})
        r2 = StepResult(outcome=CognitiveStepOutcome.SUCCESS, reason="ok", trace={"step": "1"})

        assert r1.canonical_hash == r2.canonical_hash


# ── StepResult validation ─────────────────────────────────────────────────────

class TestStepResultValidation:
    def test_non_string_reason_raises(self):
        with pytest.raises(AssertionError):
            StepResult(outcome=CognitiveStepOutcome.SUCCESS, reason=42)  # type: ignore

    def test_impure_payload_object_raises(self):
        with pytest.raises(ValidationError):
            StepResult(outcome=CognitiveStepOutcome.SUCCESS, reason="ok", payload={"key": object()})

    def test_tuple_value_in_payload_raises(self):
        with pytest.raises(ValidationError):
            StepResult(outcome=CognitiveStepOutcome.SUCCESS, reason="ok", payload={"key": (1, 2)})

    def test_nested_impure_payload_raises(self):
        with pytest.raises(ValidationError):
            StepResult(outcome=CognitiveStepOutcome.SUCCESS, reason="ok", payload={"outer": {"inner": set()}})

    def test_pure_nested_payload_is_accepted(self):
        result = StepResult(
            outcome=CognitiveStepOutcome.SUCCESS,
            reason="ok",
            payload={"outer": {"inner": [1, 2, "three"]}},
        )

        assert result.payload["outer"]["inner"] == [1, 2, "three"]