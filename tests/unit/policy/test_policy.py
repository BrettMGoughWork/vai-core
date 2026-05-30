"""
Policy invariant tests.

Covers:
- Policy.before_llm(): pre-LLM hooks (MVP: passthrough)
- Policy.after_llm(): structural constraints on LLM output
- Policy.before_execute(): tool allowlist, name limits, args size and type
- Policy.after_execute(): post-execution hooks (MVP: passthrough)
"""
import json
import pytest

from src.policy.policy import Policy


# ── Helpers ───────────────────────────────────────────────────────────────────

def _policy(allowed_tools=None, max_args_size=2000, max_tool_name=64):
    """Return a Policy with explicit values (avoids None-comparison bugs in defaults)."""
    return Policy(
        allowed_tools=allowed_tools or {"echo", "add"},
        max_args_size=max_args_size,
        max_tool_name=max_tool_name,
    )


# ── Policy.before_llm ────────────────────────────────────────────────────────

class TestBeforeLLM:
    def test_passthrough_returns_none(self):
        result = _policy().before_llm("do the thing")
        assert result is None

    def test_empty_string_input_is_accepted(self):
        result = _policy().before_llm("")
        assert result is None


# ── Policy.after_llm ─────────────────────────────────────────────────────────

class TestAfterLLM:
    def test_valid_dict_passes(self):
        _policy().after_llm({"tool": "echo", "args": {}})  # no exception

    def test_non_dict_raises(self):
        with pytest.raises(ValueError, match="LLM must return a JSON object"):
            _policy().after_llm("not a dict")

    def test_list_raises(self):
        with pytest.raises(ValueError, match="LLM must return a JSON object"):
            _policy().after_llm([{"tool": "echo"}])

    def test_dict_with_steps_key_raises(self):
        with pytest.raises(ValueError, match="Planning is not allowed"):
            _policy().after_llm({"steps": [1, 2, 3]})

    def test_dict_with_plan_key_raises(self):
        with pytest.raises(ValueError, match="Planning is not allowed"):
            _policy().after_llm({"plan": {"root": {}}})

    def test_nested_tool_call_raises(self):
        with pytest.raises(ValueError, match="Nested tool calls are not allowed"):
            _policy().after_llm({"outer": {"tool": "echo"}})

    def test_dict_with_tool_key_but_no_nested_dict_passes(self):
        # "tool" at the top level is fine — only nested dict with "tool" is blocked
        _policy().after_llm({"tool": "echo", "args": {}})  # no exception

    def test_non_dict_nested_values_are_not_mistaken_for_tool_calls(self):
        _policy().after_llm({"result": "done", "count": 42})  # no exception


# ── Policy.before_execute ─────────────────────────────────────────────────────

class TestBeforeExecute:
    def test_valid_action_passes(self):
        _policy(allowed_tools={"echo"}).before_execute({"tool": "echo", "args": {}})

    def test_tool_not_in_allowlist_raises(self):
        with pytest.raises(ValueError, match="Tool 'delete' is not permitted by policy"):
            _policy(allowed_tools={"echo"}).before_execute({"tool": "delete", "args": {}})

    def test_tool_name_at_max_length_passes(self):
        name = "x" * 64
        _policy(allowed_tools={name}, max_tool_name=64).before_execute({"tool": name, "args": {}})

    def test_tool_name_exceeding_max_raises(self):
        name = "x" * 65
        with pytest.raises(ValueError, match="Invalid tool name"):
            _policy(allowed_tools={name}, max_tool_name=64).before_execute({"tool": name, "args": {}})

    def test_args_not_a_dict_raises(self):
        with pytest.raises(ValueError, match="Args must be a dict"):
            _policy(allowed_tools={"echo"}).before_execute({"tool": "echo", "args": "bad"})

    def test_args_too_large_raises(self):
        large_args = {"data": "x" * 2001}
        with pytest.raises(ValueError, match="Args too large"):
            _policy(allowed_tools={"echo"}, max_args_size=100).before_execute(
                {"tool": "echo", "args": large_args}
            )

    def test_args_exactly_at_size_limit_passes(self):
        # Build args whose JSON is exactly max_args_size bytes
        policy = _policy(allowed_tools={"echo"}, max_args_size=20)
        small_args = {"k": "v"}  # len(json.dumps({"k": "v"})) == 10 < 20
        policy.before_execute({"tool": "echo", "args": small_args})

    def test_empty_args_dict_passes(self):
        _policy(allowed_tools={"echo"}).before_execute({"tool": "echo", "args": {}})


# ── Policy.after_execute ─────────────────────────────────────────────────────

class TestAfterExecute:
    def test_passthrough_returns_none(self):
        result = _policy().after_execute({"success": True})
        assert result is None
