"""
MockLLM — deterministic ChatProvider for Stratum-2 planning pipeline tests.

Implements the ChatProvider protocol so it is injectable wherever a real provider is used.
Updating MOCK_PLAN_RESPONSE changes the golden plan path for all downstream tests and traces.

To swap to a live LLM, replace MockLLM() with any ChatProvider at the injection point:
    SubgoalPlanner(llm=llm_factory.create("openai", model="gpt-4"), model="gpt-4")
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

# Hard-coded golden plan.  Update this dict to change the golden plan path.
MOCK_PLAN_RESPONSE: Dict[str, Any] = {
    "plan": {
        "subgoal": "verify-architecture",
        "arguments": {"value": "hello from mock"},
        "steps": [
            {
                "id": "s1",
                "description": "Validate architecture.json",
                "capability": "echo"
            },
            {
                "id": "s2",
                "description": "Verify loop termination conditions",
                "capability": "echo"
            }
        ]
    }
}

# Deterministic broken plan for testing validation-failure paths.
# Missing "subgoal" causes KeyError in SubgoalPlanner, exercising the failure branch.
_HALLUCINATION_RESPONSE: Dict[str, Any] = {
    "plan": {
        "steps": [{"id": "bad-step"}]  # missing: subgoal; step also missing description/capability
    }
}


class MockLLM:
    """
    Deterministic ChatProvider for testing the Stratum-2 planning pipeline.

    Returns MOCK_PLAN_RESPONSE as JSON in the message content.
    Response shape matches the OpenAI chat completion schema expected by SubgoalPlanner.

    simulate_hallucination=True returns a structurally broken plan (missing required
    fields) to exercise validation failure paths deterministically.
    """

    def __init__(self, simulate_hallucination: bool = False) -> None:
        self._simulate_hallucination = simulate_hallucination

    def chat(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return a deterministic OpenAI-shaped chat completion response."""
        payload = _HALLUCINATION_RESPONSE if self._simulate_hallucination else MOCK_PLAN_RESPONSE
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(payload),
                        "tool_calls": None,
                    }
                }
            ]
        }
