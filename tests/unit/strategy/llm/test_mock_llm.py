"""Tests for src.runtime.llm.mock_llm — MockLLM determinism and ChatProvider compliance."""
from __future__ import annotations

import json

import pytest

from src.runtime.llm.mock_llm import MockLLM, MOCK_PLAN_RESPONSE, _HALLUCINATION_RESPONSE


class TestMockLLMOutputShape:

    def _call(self, llm: MockLLM) -> dict:
        return llm.chat(
            model="mock",
            messages=[{"role": "user", "content": "test"}],
        )

    def test_returns_openai_shaped_response(self):
        response = self._call(MockLLM())
        assert "choices" in response
        assert len(response["choices"]) == 1
        msg = response["choices"][0]["message"]
        assert msg["role"] == "assistant"
        assert msg["tool_calls"] is None
        assert isinstance(msg["content"], str)

    def test_content_is_valid_json(self):
        response = self._call(MockLLM())
        content = response["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        assert isinstance(parsed, dict)

    def test_content_matches_mock_plan_response(self):
        response = self._call(MockLLM())
        content = json.loads(response["choices"][0]["message"]["content"])
        assert content == MOCK_PLAN_RESPONSE

    def test_simulate_hallucination_returns_broken_plan(self):
        response = self._call(MockLLM(simulate_hallucination=True))
        content = json.loads(response["choices"][0]["message"]["content"])
        assert content == _HALLUCINATION_RESPONSE
        # Broken plan deliberately missing "subgoal" — causes KeyError in SubgoalPlanner
        assert "subgoal" not in content["plan"]

    def test_model_name_does_not_affect_output(self):
        r1 = MockLLM().chat(model="mock", messages=[])
        r2 = MockLLM().chat(model="gpt-4", messages=[])
        assert r1 == r2

    def test_output_is_deterministic_across_calls(self):
        llm = MockLLM()
        r1 = self._call(llm)
        r2 = self._call(llm)
        assert r1 == r2


class TestMockLLMChatProviderProtocol:
    """Verify MockLLM satisfies the ChatProvider structural protocol."""

    def test_chat_method_exists(self):
        assert callable(getattr(MockLLM(), "chat", None))

    def test_chat_accepts_required_keyword_args(self):
        # ChatProvider.chat() requires model, messages, tools, tool_choice,
        # temperature, max_tokens — all keyword-only.
        llm = MockLLM()
        result = llm.chat(
            model="mock",
            messages=[],
            tools=None,
            tool_choice=None,
            temperature=0.0,
            max_tokens=100,
        )
        assert "choices" in result

    def test_registered_in_llm_factory(self):
        from src.runtime.llm.llm_factory import PROVIDER_CLIENTS
        assert "mock" in PROVIDER_CLIENTS
        assert PROVIDER_CLIENTS["mock"] is MockLLM


class TestMockPlanResponseStructure:

    def test_required_plan_fields_present(self):
        assert "plan" in MOCK_PLAN_RESPONSE
        plan = MOCK_PLAN_RESPONSE["plan"]
        for field in ("subgoal", "steps"):
            assert field in plan, f"Missing field: {field!r}"

    def test_segments_have_required_fields(self):
        plan = MOCK_PLAN_RESPONSE["plan"]
        for step in plan["steps"]:
            for field in ("id", "description", "capability"):
                assert field in step, f"Step missing field: {field!r}"