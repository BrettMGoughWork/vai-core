"""S5.4 — Agent → Platform Job Interface.

Translates ``CognitiveLoopResult`` action intents (produced by
``run_cognitive_loop()``) into Platform jobs via the ``submit_job()``
boundary function.

S5.4 is a **pure translation adapter**.  It:

* consumes a ``CognitiveLoopResult`` from S5.3
* translates each ``ActionIntent`` into a ``ChannelMessage``
* calls ``submit_job(channel_message)`` for intents that require execution
* collects results in a ``JobDispatchResult``

S5.4 does **not**:

* execute tools
* call LLMs
* call skills
* call ``Queue.push()`` directly
* bypass the Platform stratum
* embed cognitive logic
"""

from __future__ import annotations  # lazy annotations for circular-safety

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.agent.activation import ActivatedAgentContext
from src.agent.contracts import (
    ACTION_AGENT_STEP_INTENT,
    ACTION_CALL_TOOL_INTENT,
    ACTION_REQUEST_S4_JOB_INTENT,
    ActionIntent,
)
from src.platform.transport.normalization import ChannelMessage

if TYPE_CHECKING:
    from src.agent.cognitive_loop import CognitiveLoopResult


# ── Types ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class JobDispatchResult:
    """Result of dispatching action intents to the Platform layer.

    Attributes:
        dispatched_jobs:  Mapping of ``job_id`` → original ``ActionIntent``
                          for every successfully submitted job.
        terminal_intents: Intents that did **not** require a job (e.g.
                          ``ACTION_AGENT_STEP_INTENT``).
        errors:           (intent_type, message) pairs for intents that
                          could not be dispatched.
    """
    dispatched_jobs: dict[str, ActionIntent] = field(default_factory=dict)
    terminal_intents: list[ActionIntent] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)


# ── Dispatch ──────────────────────────────────────────────────────────────


def _translate_intent_to_channel_message(
    intent: ActionIntent,
    context: ActivatedAgentContext,
) -> ChannelMessage:
    """Translate an ``ActionIntent`` into a ``ChannelMessage``.

    The channel is taken from the activation context so that downstream
    workers know which ingress path triggered this work.  The original
    intent is serialised into the message body under ``"action_intent"``.
    """
    channel_id = context.envelope.activation_context.get("channel", "system")
    return ChannelMessage(
        channel=channel_id,
        input={
            "action_intent": dataclasses.asdict(intent),
        },
        metadata={
            "source": f"agent/{context.context.agent_metadata.identity.agent_id}",
        },
    )


def dispatch_action_intents(
    result: CognitiveLoopResult,
    context: ActivatedAgentContext,
    *,
    submit_job_callable: Callable[[ChannelMessage], str] | None = None,
) -> JobDispatchResult:
    """Translate and dispatch action intents to the Platform stratum.

    Args:
        result:   Output from ``run_cognitive_loop()`` — the current
                  batch of action intents to process.
        context:  Activation context used to enrich the channel messages
                  that wrap each intent.
        submit_job_callable:
            A callable that takes a ``ChannelMessage`` and returns a
            ``job_id`` string.  This is the Platform-stratum boundary
            function — typically ``submit_job`` with a ``Queue`` already
            bound via ``functools.partial``.

            If ``None``, the canonical ``submit_job`` from
            ``src.platform.interfaces`` is used (requires a ``Queue``
            to be wired externally — prefer the bound-callable pattern).

    Returns:
        A ``JobDispatchResult`` summarising what was dispatched and what
        (if anything) failed.
    """
    if result.errors:
        return JobDispatchResult(
            errors=[("cognitive_loop", str(e)) for e in result.errors],
        )

    dispatched: dict[str, ActionIntent] = {}
    terminal: list[ActionIntent] = []
    errors: list[tuple[str, str]] = []

    submitter = submit_job_callable

    for intent in result.action_intents:
        if intent.type == ACTION_AGENT_STEP_INTENT:
            # No job required — terminal / continuation intent.
            terminal.append(intent)
            continue

        if intent.type in (ACTION_CALL_TOOL_INTENT, ACTION_REQUEST_S4_JOB_INTENT):
            try:
                channel_message = _translate_intent_to_channel_message(intent, context)
                if submitter is not None:
                    job_id = submitter(channel_message)
                else:
                    # Fallback — caller must provide a Queue externally.
                    error_msg = (
                        "No submit_job_callable provided.  Cannot dispatch "
                        f"{intent.type} without a Platform Queue."
                    )
                    errors.append((intent.type, error_msg))
                    continue

                dispatched[job_id] = intent
            except Exception as exc:
                errors.append((intent.type, str(exc)))
        else:
            errors.append(
                (intent.type, f"Unsupported intent type: {intent.type}")
            )

    return JobDispatchResult(
        dispatched_jobs=dispatched,
        terminal_intents=terminal,
        errors=errors,
    )
