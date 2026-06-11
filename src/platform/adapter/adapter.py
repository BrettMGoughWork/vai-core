"""S4 → S1/S2/S3 adapter boundary — Stratum-4 runtime.

Two pure functions that define the thin transformation layer between
S4 and the cognitive strata.  No orchestration, no worker logic, no
control plane — just typed input → typed output.
"""

from __future__ import annotations

from typing import Any

from src.platform.transport.normalization import ChannelMessage


def s2_to_s1_adapter(payload: ChannelMessage) -> dict[str, Any]:
    """Transform a normalized channel message into an S1 request.

    S4 receives a ``ChannelMessage`` from the transport layer.  This function
    is the S4→S1 boundary: it produces the stable dict shape that the
    runtime stratum (S1) expects.

    Returns:
        A dict with ``type``, ``input``, and ``metadata`` keys.
    """
    return {
        "type": "s1_request",
        "input": payload.input,
        "metadata": payload.metadata,
    }


def s1_to_s2_adapter(raw_output: dict[str, Any]) -> dict[str, Any]:
    """Transform raw LLM/tool output into an S2-compatible result.

    S1 returns raw execution output.  This function is the S1→S4→S2
    boundary: it produces the stable dict shape that the strategy
    stratum (S2) understands.

    Args:
        raw_output: The raw output from S1 execution.

    Returns:
        A dict with ``type`` and ``output`` keys.
    """
    return {
        "type": "s2_result",
        "output": raw_output,
    }
