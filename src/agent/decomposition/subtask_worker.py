"""SubtaskWorker — WorkExecutor for decomposition subtask jobs.

Each subtask job carries a ``ChannelMessage`` payload with:

* ``payload.input["subtask_description"]`` — instructions for the agent
* ``payload.input["target_agent_id"]`` — which agent to invoke (optional)
* ``payload.input["target_skill_id"]`` — which skill to run (optional)
* ``payload.input["arguments"]`` — keyword arguments for the agent/skill

The worker routes each subtask to either a target agent (via the Supervisor's
create→activate→run lifecycle) or a target skill (via the inline executor).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class SubtaskWorker:
    """WorkExecutor for decomposition subtask jobs.

    Routes each subtask to a target agent (create + activate + run to
    completion) or a target skill/primitive (inline execution).

    Args:
        run_temp_agent:
            Callable that creates, activates, and runs a temporary agent
            to completion, returning a result dict with at least an
            ``"output"`` key.  Signature::

                (agent_id: str, prompt: str) -> dict[str, Any]

        inline_tool_executor:
            Optional callable for inline tool/primitive execution.
            Signature: ``(dict) -> dict | None``.
    """

    def __init__(
        self,
        run_temp_agent: Callable[[str, str], dict[str, Any]],
        inline_tool_executor: Callable[[dict], dict | None] | None = None,
    ) -> None:
        self._run_temp_agent = run_temp_agent
        self._inline_tool_executor = inline_tool_executor

    def __call__(
        self,
        payload: Any,
        execution_context: Any = None,
        resume_token: Any = None,
        **kwargs: Any,
    ) -> dict:
        """Process a subtask job.

        Extracts the subtask description and target from *payload*,
        dispatches to the appropriate handler, and returns a result dict.

        Returns:
            A dict with at least an ``"output"`` key.
        """
        # --- Normalise payload ----------------------------------------------
        # Lazy-import to avoid circular / missing-dependency issues.
        try:
            from src.gateway.normalization import ChannelMessage

            _channel_type = ChannelMessage
        except ImportError:
            _channel_type = type(None)

        if isinstance(payload, _channel_type):
            inp = payload.input or {}
        elif isinstance(payload, dict):
            inp = payload.get("input", payload)
        else:
            return {
                "output": f"Unexpected payload type: {type(payload).__name__}",
                "status": "error",
                "done": True,
            }

        subtask_description: str = inp.get("subtask_description", "")
        target_agent_id: str | None = inp.get("target_agent_id")
        target_skill_id: str | None = inp.get("target_skill_id")
        arguments: dict = inp.get("arguments", {})

        if not subtask_description:
            return {
                "output": "No subtask_description provided — nothing to do.",
                "status": "error",
                "done": True,
            }

        # --- Route to agent --------------------------------------------------
        if target_agent_id:
            return self._run_temp_agent(target_agent_id, subtask_description)

        # --- Route to skill / primitive -------------------------------------
        if target_skill_id and self._inline_tool_executor is not None:
            tool_input: dict[str, Any] = {
                "tool_name": target_skill_id,
                "arguments": {**arguments, "instruction": subtask_description},
            }
            result = self._inline_tool_executor(tool_input)
            if result is None:
                return {
                    "output": f"Skill {target_skill_id} returned no result.",
                    "status": "error",
                    "done": True,
                }
            return {
                "output": result.get("output", str(result)),
                "status": "success",
                "done": True,
            }

        # --- No valid target -------------------------------------------------
        return {
            "output": (
                "Neither target_agent_id nor target_skill_id provided — "
                "cannot route subtask."
            ),
            "status": "error",
            "done": True,
        }
