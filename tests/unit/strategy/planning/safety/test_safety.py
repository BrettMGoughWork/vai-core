"""
Safety layer tests.

Covers:
- validate_pure_structure(): JSON-purity enforcement (types, paths, nesting)
- enforce_cognitive_purity(): Stratum-2 output guard (forbidden keys, impure types)
- LoopPolicy: deterministic loop constraint model
- LoopPolicyEnforcer: enforcement of LoopPolicy constraints
"""
import pytest

from src.strategy.planning.safety.purity_validation import validate_pure_structure
from src.strategy.planning.safety.purity_enforcer import enforce_cognitive_purity
from src.strategy.planning.safety.loop_policy import LoopPolicy
from src.strategy.planning.safety.loop_policy_enforcer import LoopPolicyEnforcer
from src.strategy.types.errors.ValidationError import ValidationError


# ── validate_pure_structure ───────────────────────────────────────────────────

class TestValidatePureStructure:
    # Valid cases
    def test_string_is_valid(self):
        validate_pure_structure("hello")

    def test_int_is_valid(self):
        validate_pure_structure(42)

    def test_float_is_valid(self):
        validate_pure_structure(3.14)

    def test_bool_is_valid(self):
        validate_pure_structure(True)

    def test_none_is_valid(self):
        validate_pure_structure(None)

    def test_empty_dict_is_valid(self):
        validate_pure_structure({})

    def test_empty_list_is_valid(self):
        validate_pure_structure([])

    def test_nested_dict_with_scalar_values_is_valid(self):
        validate_pure_structure({"a": 1, "b": "x", "c": None})

    def test_list_of_scalars_is_valid(self):
        validate_pure_structure([1, "two", True, None])

    def test_deeply_nested_structure_is_valid(self):
        validate_pure_structure({"a": {"b": {"c": [1, 2, {"d": "e"}]}}})

    # Invalid cases
    def test_tuple_raises_type_error(self):
        with pytest.raises(TypeError, match="Impure value"):
            validate_pure_structure((1, 2))

    def test_set_raises_type_error(self):
        with pytest.raises(TypeError, match="Impure value"):
            validate_pure_structure({1, 2, 3})

    def test_bytes_raises_type_error(self):
        with pytest.raises(TypeError, match="Impure value"):
            validate_pure_structure(b"bytes")

    def test_callable_raises_type_error(self):
        with pytest.raises(TypeError, match="Impure value"):
            validate_pure_structure(lambda: None)

    def test_custom_object_raises_type_error(self):
        class Foo:
            pass
        with pytest.raises(TypeError, match="Impure value"):
            validate_pure_structure(Foo())

    def test_non_string_dict_key_raises_type_error(self):
        with pytest.raises(TypeError, match="Non.string key"):
            validate_pure_structure({1: "value"})

    def test_error_message_includes_root_for_top_level(self):
        with pytest.raises(TypeError, match="<root>"):
            validate_pure_structure((1, 2))

    def test_error_message_includes_path_for_nested_value(self):
        with pytest.raises(TypeError, match=r"\.bad"):
            validate_pure_structure({"bad": (1, 2)})

    def test_error_message_includes_index_for_list_item(self):
        with pytest.raises(TypeError, match=r"\[1\]"):
            validate_pure_structure([1, (2, 3)])


# ── enforce_cognitive_purity ──────────────────────────────────────────────────

class TestEnforceCognitivePurity:
    def test_clean_dict_passes_and_is_returned(self):
        obj = {"type": "classification", "outcome": "success", "reason": "done"}
        result = enforce_cognitive_purity(obj)
        assert result == obj

    def test_empty_dict_passes(self):
        result = enforce_cognitive_purity({})
        assert result == {}

    def test_nested_clean_dict_passes(self):
        result = enforce_cognitive_purity({"a": {"b": [1, 2, 3]}})
        assert result["a"]["b"] == [1, 2, 3]

    # JSON-purity violations
    def test_set_value_raises_validation_error(self):
        with pytest.raises(ValidationError, match="not JSON.pure"):
            enforce_cognitive_purity({"data": {1, 2, 3}})

    def test_bytes_value_raises_validation_error(self):
        with pytest.raises(ValidationError, match="not JSON.pure"):
            enforce_cognitive_purity({"data": b"raw"})

    # Forbidden tool keys
    def test_tool_key_raises_validation_error(self):
        with pytest.raises(ValidationError, match="Forbidden key 'tool'"):
            enforce_cognitive_purity({"tool": "echo"})

    def test_tool_name_key_raises_validation_error(self):
        with pytest.raises(ValidationError, match="Forbidden key 'tool_name'"):
            enforce_cognitive_purity({"tool_name": "echo"})

    def test_tool_calls_key_raises_validation_error(self):
        with pytest.raises(ValidationError, match="Forbidden key 'tool_calls'"):
            enforce_cognitive_purity({"tool_calls": []})

    def test_arguments_key_raises_validation_error(self):
        with pytest.raises(ValidationError, match="Forbidden key 'arguments'"):
            enforce_cognitive_purity({"arguments": {}})

    # Forbidden LLM keys
    def test_model_key_raises_validation_error(self):
        with pytest.raises(ValidationError, match="Forbidden key 'model'"):
            enforce_cognitive_purity({"model": "gpt-4"})

    def test_temperature_key_raises_validation_error(self):
        with pytest.raises(ValidationError, match="Forbidden key 'temperature'"):
            enforce_cognitive_purity({"temperature": 0.7})

    def test_prompt_key_raises_validation_error(self):
        with pytest.raises(ValidationError, match="Forbidden key 'prompt'"):
            enforce_cognitive_purity({"prompt": "do something"})

    # Forbidden side-effect keys
    def test_timestamp_key_raises_validation_error(self):
        with pytest.raises(ValidationError, match="Forbidden key 'timestamp'"):
            enforce_cognitive_purity({"timestamp": 12345})

    def test_env_key_raises_validation_error(self):
        with pytest.raises(ValidationError, match="Forbidden key 'env'"):
            enforce_cognitive_purity({"env": "production"})

    def test_file_path_key_raises_validation_error(self):
        with pytest.raises(ValidationError, match="Forbidden key 'file_path'"):
            enforce_cognitive_purity({"file_path": "/tmp/x"})

    def test_nested_forbidden_key_raises_validation_error(self):
        with pytest.raises(ValidationError, match="Forbidden key 'tool'"):
            enforce_cognitive_purity({"output": {"tool": "echo"}})


# ── LoopPolicy ───────────────────────────────────────────────────────────────

class TestLoopPolicy:
    def test_default_max_steps_is_50(self):
        policy = LoopPolicy()
        assert policy.max_steps == 50

    def test_default_max_retries_is_3(self):
        policy = LoopPolicy()
        assert policy.max_retries == 3

    def test_default_max_duration_is_none(self):
        policy = LoopPolicy()
        assert policy.max_duration is None

    def test_allows_step_below_max(self):
        policy = LoopPolicy(max_steps=10)
        assert policy.allows_step(9) is True

    def test_allows_step_at_max_returns_false(self):
        policy = LoopPolicy(max_steps=10)
        assert policy.allows_step(10) is False

    def test_allows_step_above_max_returns_false(self):
        policy = LoopPolicy(max_steps=10)
        assert policy.allows_step(11) is False

    def test_allows_retry_below_max(self):
        policy = LoopPolicy(max_retries=3)
        assert policy.allows_retry(2) is True

    def test_allows_retry_at_max_returns_false(self):
        policy = LoopPolicy(max_retries=3)
        assert policy.allows_retry(3) is False

    def test_allows_duration_with_no_limit_always_true(self):
        policy = LoopPolicy(max_duration=None)
        assert policy.allows_duration(999_999) is True

    def test_allows_duration_below_limit(self):
        policy = LoopPolicy(max_duration=100)
        assert policy.allows_duration(99) is True

    def test_allows_duration_at_limit_returns_false(self):
        policy = LoopPolicy(max_duration=100)
        assert policy.allows_duration(100) is False

    def test_is_frozen(self):
        policy = LoopPolicy()
        with pytest.raises(Exception):
            policy.max_steps = 1  # noqa: frozen dataclass


# ── LoopPolicyEnforcer ────────────────────────────────────────────────────────

class TestLoopPolicyEnforcer:
    def _enforcer(self, max_steps=10, max_retries=3, max_duration=None):
        return LoopPolicyEnforcer(
            policy=LoopPolicy(max_steps=max_steps, max_retries=max_retries, max_duration=max_duration)
        )

    def test_check_step_limit_passes_when_not_exceeded(self):
        self._enforcer(max_steps=10).check_step_limit(9)  # no exception

    def test_check_step_limit_raises_when_exceeded(self):
        with pytest.raises(ValidationError, match="max_steps exceeded \\(10\\)"):
            self._enforcer(max_steps=10).check_step_limit(10)

    def test_check_retry_limit_passes_when_not_exceeded(self):
        self._enforcer(max_retries=3).check_retry_limit(2)  # no exception

    def test_check_retry_limit_raises_when_exceeded(self):
        with pytest.raises(ValidationError, match="max_retries exceeded \\(3\\)"):
            self._enforcer(max_retries=3).check_retry_limit(3)

    def test_check_duration_limit_passes_when_no_limit(self):
        self._enforcer(max_duration=None).check_duration_limit(999)  # no exception

    def test_check_duration_limit_passes_when_below_limit(self):
        self._enforcer(max_duration=100).check_duration_limit(99)  # no exception

    def test_check_duration_limit_raises_when_exceeded(self):
        with pytest.raises(ValidationError, match="max_duration exceeded \\(100\\)"):
            self._enforcer(max_duration=100).check_duration_limit(100)

    def test_error_message_includes_exact_count(self):
        with pytest.raises(ValidationError, match="max_steps exceeded \\(42\\)"):
            self._enforcer(max_steps=5).check_step_limit(42)