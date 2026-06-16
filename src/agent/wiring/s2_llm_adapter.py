"""
S2 LLM Adapter — wraps S1Executor into ``Callable[[str, str], str]``
=====================================================================

The S2 planner (``AgentPlanner`` / ``SubgoalPlanner``) expects an
``llm_complete`` callback with the signature
``Callable[[str, str], str]`` — given a system prompt and a user
message, return raw text.

The S5→S1 protocol (``S1Executor.complete()``) returns a structured
``CoreLLMResponse`` instead of raw text.

This adapter bridges the gap by:

1. Calling ``S1Executor.complete(system_prompt + user_message)``
2. Extracting ``.text`` from the returned ``CoreLLMResponse``
3. Returning it as plain text

Usage
-----
    executor: S1Executor = …
    llm_complete = make_llm_complete(executor)
    planner = AgentPlanner(llm_complete=llm_complete)
"""

from __future__ import annotations

from collections.abc import Callable

from src.agent.interfaces.s1_executor import S1Executor


def make_llm_complete(executor: S1Executor) -> Callable[[str, str], str]:
    """Wrap an ``S1Executor`` into the ``llm_complete`` shape S2 expects.

    The returned callable concatenates system + user prompts and extracts
    ``.text`` from the structured response.
    """

    def _complete(system: str, user: str) -> str:
        prompt = f"{system}\n\n{user}" if system else user
        response = executor.complete(prompt)
        return response.text if response.text is not None else ""

    return _complete
