"""
Governance invariant tests.

Covers:
- Governance.canonicalise(): normalisation + aliasing + external validator
- Governance.validate(): structural constraints
- GovernanceError: base exception hierarchy
"""
import pytest

from src.governance.schema import Governance
from src.governance.errors import GovernanceError


# ── Helpers ───────────────────────────────────────────────────────────────────

def _gov():
    return Governance()


# ── GovernanceError ───────────────────────────────────────────────────────────

class TestGovernanceError:
    def test_is_exception_subclass(self):
        assert issubclass(GovernanceError, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(GovernanceError, match="boom"):
            raise GovernanceError("boom")


# ── Governance.validate() ─────────────────────────────────────────────────────

class TestGovernanceValidate:
    def test_valid_action_passes(self):
        _gov().validate({"tool": "echo", "args": {}})  # no exception

    def test_non_dict_raises_value_error(self):
        with pytest.raises(ValueError, match="Action must be a dict"):
            _gov().validate("not a dict")

    def test_missing_tool_key_raises(self):
        with pytest.raises(ValueError, match="Missing required key: tool"):
            _gov().validate({"args": {}})

    def test_missing_args_key_raises(self):
        with pytest.raises(ValueError, match="Missing required key: args"):
            _gov().validate({"tool": "echo"})

    def test_non_string_tool_raises(self):
        with pytest.raises(ValueError, match="Action 'tool' must be a string"):
            _gov().validate({"tool": 42, "args": {}})

    def test_both_required_keys_missing_reports_tool_first(self):
        # REQUIRED_KEYS is ["tool", "args"] — first missing key is reported
        with pytest.raises(ValueError, match="Missing required key: tool"):
            _gov().validate({})


# ── Governance.canonicalise() ─────────────────────────────────────────────────

class TestGovernanceCanonicalize:
    def test_valid_action_returns_canonical_form(self):
        result = _gov().canonicalise({"tool": "echo", "args": {"msg": "hi"}})

        assert result == {"tool": "echo", "args": {"msg": "hi"}}

    def test_action_key_is_alias_for_tool(self):
        result = _gov().canonicalise({"action": "echo", "args": {}})

        assert result["tool"] == "echo"

    def test_single_element_list_tool_is_unpacked(self):
        result = _gov().canonicalise({"tool": ["echo"], "args": {}})

        assert result["tool"] == "echo"

    def test_multi_element_list_tool_raises(self):
        with pytest.raises(ValueError, match="Action 'tool' must be a string"):
            _gov().canonicalise({"tool": ["echo", "add"], "args": {}})

    def test_missing_tool_and_action_raises(self):
        with pytest.raises(ValueError, match="Action 'tool' must be a string"):
            _gov().canonicalise({"args": {"x": 1}})

    def test_non_dict_input_raises(self):
        with pytest.raises(ValueError, match="LLM output must be a dict"):
            _gov().canonicalise("not a dict")

    def test_non_dict_input_list_raises(self):
        with pytest.raises(ValueError, match="LLM output must be a dict"):
            _gov().canonicalise([{"tool": "echo"}])

    def test_missing_args_are_inferred_from_remaining_fields(self):
        result = _gov().canonicalise({"tool": "echo", "msg": "hello"})

        assert result["args"] == {"msg": "hello"}
        assert "msg" not in result

    def test_non_dict_args_are_wrapped(self):
        result = _gov().canonicalise({"tool": "echo", "args": "raw_string"})

        assert result["args"] == {"value": "raw_string"}

    def test_external_validator_is_called(self):
        calls = []

        class FakeValidator:
            def validate(self, action):
                calls.append(action)

        gov = Governance(validator=FakeValidator())
        gov.canonicalise({"tool": "echo", "args": {}})

        assert len(calls) == 1
        assert calls[0]["tool"] == "echo"

    def test_external_validator_rejection_propagates(self):
        class RejectingValidator:
            def validate(self, action):
                raise ValueError("rejected by external validator")

        gov = Governance(validator=RejectingValidator())

        with pytest.raises(ValueError, match="rejected by external validator"):
            gov.canonicalise({"tool": "echo", "args": {}})

    def test_output_always_contains_tool_and_args(self):
        result = _gov().canonicalise({"tool": "do_thing", "args": {"k": "v"}})

        assert "tool" in result
        assert "args" in result

    def test_action_alias_not_present_in_output(self):
        result = _gov().canonicalise({"action": "echo", "args": {}})

        # canonical form uses "tool", not "action"
        assert "tool" in result
        assert "action" not in result