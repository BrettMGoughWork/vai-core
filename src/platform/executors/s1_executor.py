"""S1-based executor for the S4 Worker.

Moved out of ``worker.py`` during the R.4 refactor so that the Worker
is a generic durable execution engine that does not know about S1, S2,
or S3.  This adapter preserves the old dispatch logic for callers that
need real S1 processing (CLI app, web app, testing harness).

Usage::

    from src.platform.executors.s1_executor import s1_executor

    worker = Worker(executor=s1_executor, queue=queue, control_plane=cp)
"""

from __future__ import annotations

from typing import Any

from src.platform.adapter.adapter import s1_to_s2_adapter, s2_to_s1_adapter
from src.platform.transport.normalization import ChannelMessage
from src.runtime.llm.client import call_s1_backend
from src.runtime.llm.s1_real_client import ENABLE_REAL_LLM
from src.domain.interfaces.contract import PromptRequest, S1Error


def _dispatch_to_s1(
    payload: ChannelMessage,
    s1_request: dict[str, Any],
    enable_real_llm: bool = False,
) -> dict[str, Any]:
    """Dispatch a job payload to the S1 cognitive stratum.

    Builds a :class:`PromptRequest` from the channel message and sends it
    through ``call_s1_backend()`` (simulation or real_llm backend).
    """
    # Extract the user's input text from the normalized payload structure.
    # ChannelMessage.input is a dict with fields like
    # {"input": "<user text>", "metadata": {...}}.
    raw_input: dict[str, Any] = payload.input
    user_text: str = ""
    if isinstance(raw_input, dict):
        user_text = raw_input.get("input", "")
        if not isinstance(user_text, str):
            user_text = str(user_text)

    request = PromptRequest(
        prompt={"instruction": user_text},
        memory={},
        plan_context={},
        tool_context=[
            {
                "name": "chat",
                "description": "Respond to the user's message",
                "schema": {
                    "type": "object",
                    "properties": {"response": {"type": "string"}},
                },
            },
        ],
    )

    backend = "real_llm" if enable_real_llm else "simulation"
    result = call_s1_backend(request, backend=backend)

    if isinstance(result, S1Error):
        return {
            "error": result.message,
            "error_type": result.type,
            "s1_request": s1_request.get("input", {}),
        }

    return {
        "s1_output": result.output,
        "s1_request": s1_request.get("input", {}),
    }


def s1_executor(
    payload: ChannelMessage,
    execution_context: dict | None = None,
    resume_token: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Execute one cognitive cycle through the S1 adapter pipeline.

    Converts the S4 payload to an S1 request via the S2→S1 adapter,
    executes against the cognitive strata via S1 dispatch (simulation
    or real LLM), normalises the raw output via the S1→S2 adapter,
    and wraps the result in a multi-cycle envelope.

    The return dict retains the original structure (``result.output.s1_output``)
    for backward compatibility, while also providing the top-level ``output``
    key that the simplified ``Worker._route_response`` expects.

    Args:
        payload:          The job payload (a ``ChannelMessage``).
        execution_context: Opaque cognitive context (unused in stub).
        resume_token:     Opaque cycle identifier (passthrough).
        **kwargs:         Ignored extra args from ToolRetryWrapper
                          (attempt, job_id, failure_count).

    Returns:
        A dict with at least ``output`` (channel routing) and the full
        legacy envelope (``done``, ``cognitive_state``, ``memory``,
        ``result``) for backward compat.
    """
    s1_request = s2_to_s1_adapter(payload, resume_token=resume_token)
    raw_output = _dispatch_to_s1(
        payload, s1_request, enable_real_llm=ENABLE_REAL_LLM,
    )
    s2_result = s1_to_s2_adapter(raw_output)

    # Extract a human-readable response for the top-level ``output`` key.
    # The S2 result has structure: {"type": "s2_result", "output": {"s1_output": {...}}}
    response_text = ""
    if isinstance(s2_result, dict):
        s1_output = s2_result.get("output", {}).get("s1_output", {})
        if isinstance(s1_output, dict):
            response_text = s1_output.get("reflection", "") or ""
            if not response_text:
                for val in s1_output.values():
                    if isinstance(val, str) and val.strip():
                        response_text = val
                        break
        elif isinstance(s1_output, str):
            response_text = s1_output

    return {
        "output": response_text,
        "done": True,
        "cognitive_state": {},
        "memory": {},
        "result": s2_result,
    }
