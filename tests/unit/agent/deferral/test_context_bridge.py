"""Tests for the context bridge."""

from src.agent.deferral.context_bridge import ContextBridge, build_delegate_prompt


class TestBuildDelegatePrompt:
    """Prompt construction for delegate agents."""

    def test_minimal_prompt(self):
        result = ContextBridge.build_delegate_prompt(
            delegator_id="support",
            delegator_name="Support Agent",
            user_message="I need billing help",
            deferral_prompt="Please help with billing",
        )
        assert "Support Agent" in result
        assert "support" in result
        assert "I need billing help" in result
        assert "Please help with billing" in result

    def test_prompt_includes_delegator_header(self):
        result = ContextBridge.build_delegate_prompt(
            delegator_id="a1",
            delegator_name="Alpha",
            user_message="do X",
            deferral_prompt="do Y",
        )
        assert "[Delegated from Alpha (a1)]" in result

    def test_prompt_includes_request_section(self):
        result = ContextBridge.build_delegate_prompt(
            delegator_id="a1",
            delegator_name="A",
            user_message="help",
            deferral_prompt="audit the code",
        )
        assert "Request: audit the code" in result

    def test_prompt_includes_original_user_request(self):
        result = ContextBridge.build_delegate_prompt(
            delegator_id="a1",
            delegator_name="A",
            user_message="help me with billing",
            deferral_prompt="handle this",
        )
        assert "Original user request: help me with billing" in result

    def test_conversation_history_included(self):
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "I have a question"},
        ]
        result = ContextBridge.build_delegate_prompt(
            delegator_id="a1",
            delegator_name="A",
            user_message="latest",
            deferral_prompt="answer it",
            conversation_history=history,
        )
        assert "Original conversation context:" in result
        assert "Hello" in result
        assert "Hi there" in result

    def test_conversation_history_truncated_to_6_turns(self):
        history = [
            {"role": "user", "content": f"msg{i}"}
            for i in range(10)
        ]
        result = ContextBridge.build_delegate_prompt(
            delegator_id="a1",
            delegator_name="A",
            user_message="latest",
            deferral_prompt="handle",
            conversation_history=history,
        )
        # Only the last 6 should appear
        for i in range(4):
            assert f"msg{i}" not in result
        for i in range(6, 10):
            assert f"msg{i}" in result

    def test_long_messages_truncated(self):
        long_content = "x" * 600
        history = [{"role": "user", "content": long_content}]
        result = ContextBridge.build_delegate_prompt(
            delegator_id="a1",
            delegator_name="A",
            user_message="latest",
            deferral_prompt="handle",
            conversation_history=history,
        )
        assert "x" * 500 in result
        assert "x" * 510 not in result  # beyond truncation
        assert "..." in result

    def test_no_conversation_history(self):
        result = ContextBridge.build_delegate_prompt(
            delegator_id="a1",
            delegator_name="A",
            user_message="hi",
            deferral_prompt="help",
            conversation_history=None,
        )
        assert "Original conversation context:" not in result


class TestBuildDelegateResultContext:
    """Response injection back into delegator."""

    def test_success_result(self):
        result = ContextBridge.build_delegate_result_context(
            delegate_id="billing",
            delegate_name="Billing Agent",
            response_text="The invoice has been paid.",
            success=True,
        )
        assert "Billing Agent" in result
        assert "billing" in result
        assert "completed successfully" in result
        assert "The invoice has been paid." in result

    def test_failure_result(self):
        result = ContextBridge.build_delegate_result_context(
            delegate_id="billing",
            delegate_name="Billing Agent",
            response_text="Failed to process.",
            success=False,
        )
        assert "failed" in result
        assert "Failed to process." in result

    def test_truncation(self):
        long_response = "y" * 2500
        result = ContextBridge.build_delegate_result_context(
            delegate_id="a",
            delegate_name="A",
            response_text=long_response,
            success=True,
        )
        assert "... [response truncated]" in result
        assert "y" * 2000 in result
        assert "y" * 2100 not in result


class TestConvenienceFunction:
    def test_build_delegate_prompt_convenience(self):
        result = build_delegate_prompt(
            delegator_id="x",
            delegator_name="X",
            user_message="help",
            deferral_prompt="do it",
        )
        assert "X" in result
        assert "help" in result
