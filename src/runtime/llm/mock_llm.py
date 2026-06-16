"""
MockLLM — deterministic ChatProvider for Stratum-2 planning pipeline tests.

Implements the ChatProvider protocol so it is injectable wherever a real provider is used.
Updating MOCK_PLAN_RESPONSE changes the golden plan path for all downstream tests and traces.

To swap to a live LLM, wrap a ChatProvider in an ``llm_complete`` callable:
    def llm_complete(sys: str, usr: str) -> str:
        raw = provider.chat(model="gpt-4", messages=[
            {"role": "system", "content": sys},
            {"role": "user", "content": usr},
        ])
        return raw["choices"][0]["message"]["content"]
    SubgoalPlanner(llm_complete=llm_complete)
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

# Hard-coded golden plan.  Update this dict to change the golden plan path.
MOCK_PLAN_RESPONSE: Dict[str, Any] = {
    "plan": {
        "subgoal": "verify-architecture",
        "arguments": {},
        "steps": [
            {
                "id": "s1",
                "description": "Validate architecture.json",
                "capability": "stdlib.echo",
                "inputs": {"value": "hello from mock step 1"}
            },
            {
                "id": "s2",
                "description": "Verify loop termination conditions",
                "capability": "stdlib.echo",
                "inputs": {"value": "hello from mock step 2"}
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

    def make_complete(self) -> Callable[[str, str], str]:
        """Return an ``llm_complete``-compatible callable wrapping this mock.

        The returned callable has the signature
        ``(system_prompt: str, user_message: str) -> str`` expected by
        ``SubgoalPlanner`` and ``AgentPlanner``.

        Usage::

            planner = SubgoalPlanner(
                llm_complete=MockLLM().make_complete(),
            )
        """
        from collections.abc import Callable as _Callable

        def _complete(_sys: str, _usr: str) -> str:
            raw = self.chat(
                model="mock",
                messages=[
                    {"role": "system", "content": _sys},
                    {"role": "user", "content": _usr},
                ],
            )
            return raw["choices"][0]["message"]["content"]

        return _complete
