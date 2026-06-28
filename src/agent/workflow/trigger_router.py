"""
Phase 5.7 — Workflow Trigger Router

The trigger router is the "glue" between S4's event substrate and S5's workflow
engine. It subscribes to workflow-relevant events, filters them, and maps them
to workflow instances.

The router does NOT own transport — it receives events via the event bus and
calls the engine. The caller (Supervisor) owns the execution loop.

Events
------
    workflow.start             Start a new workflow instance
    workflow.resume            Resume a paused workflow (caller must provide state)
    workflow.timeout           Mark a running workflow as timed out
    workflow.scheduled_trigger Cron / timer / schedule start
    workflow.external_input    External input for a paused workflow
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from src.agent.workflow.engine import WorkflowEngine, WorkflowExecutionState
from src.agent.workflow.registry import WorkflowRegistry

if TYPE_CHECKING:
    from src.agent.workflow.event_bus import EventBus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkflowEvent:
    """A workflow-relevant event arriving from S4's event substrate.

    Attributes:
        event_type:     Event type (e.g. ``"workflow.start"``,
                        ``"workflow.resume"``, ``"workflow.scheduled_trigger"``).
        payload:        Event payload — merged into the workflow context.
        correlation_id: Correlation / trace ID for observability.
        timestamp:      Unix timestamp of the event.
    """

    event_type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""
    timestamp: float = 0.0


# ---------------------------------------------------------------------------
# Trigger Router
# ---------------------------------------------------------------------------


class TriggerRouter:
    """Maps workflow-relevant events to workflow instances.

    The router is the ingress for all S5-triggering events.  It uses the
    registry to find workflow definitions whose ``trigger_on`` list matches
    the incoming event type, then calls the engine to start a new instance.

    Resume events are handled via ``resume_workflow()`` — the caller must
    deserialise the ``WorkflowExecutionState`` before passing it in.
    """

    def __init__(
        self,
        registry: WorkflowRegistry,
        engine: WorkflowEngine,
    ) -> None:
        self._registry = registry
        self._engine = engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle_event(self, event: WorkflowEvent) -> Optional[str]:
        """Handle a single workflow event.

        For start-type events (``workflow.start``,
        ``workflow.scheduled_trigger``): find all workflow definitions
        whose ``trigger_on`` includes ``event.event_type`` and start a
        new instance for each match.

        For other event types the method returns ``None`` — the caller
        should handle them via ``resume_workflow()`` or ignore.

        Args:
            event: The incoming event.

        Returns:
            The last ``execution_id`` created, or ``None`` if no workflow
            matched or the event type is not a start type.
        """
        if event.event_type not in _START_EVENT_TYPES:
            logger.debug(
                "TriggerRouter: non-start event %r (type=%s) — skipping",
                event.correlation_id,
                event.event_type,
            )
            return None

        matches = self._registry.find_by_trigger(event.event_type)
        if not matches:
            logger.info(
                "TriggerRouter: no workflow matches for event type %r "
                "(correlation_id=%s)",
                event.event_type,
                event.correlation_id,
            )
            return None

        last_id: Optional[str] = None
        for defn in matches:
            context = dict(event.payload)
            if event.correlation_id:
                context.setdefault("correlation_id", event.correlation_id)
            try:
                state = self._engine.start_workflow(
                    defn.workflow_id,
                    context=context,
                )
                last_id = state.execution_id
                logger.info(
                    "TriggerRouter: started workflow %r (execution=%s) "
                    "from event %s",
                    defn.workflow_id,
                    state.execution_id,
                    event.correlation_id,
                )
            except Exception:
                logger.exception(
                    "TriggerRouter: failed to start workflow %r from event %s",
                    defn.workflow_id,
                    event.correlation_id,
                )

        return last_id

    def resume_workflow(
        self,
        state: WorkflowExecutionState,
        user_input: str,
        correlation_id: str = "",
    ) -> WorkflowExecutionState:
        """Resume a paused workflow with user input.

        This is a convenience wrapper around ``engine.resume_with_input()``.
        The caller is responsible for deserialising the state from wherever
        it was stored (e.g. ``supervisor_metadata["workflow_state"]``).

        Args:
            state:         The persisted workflow execution state.
            user_input:    The user's input to inject.
            correlation_id: Optional trace ID for logging.

        Returns:
            The updated workflow execution state (the caller must persist
            it for the next cycle).
        """
        if correlation_id:
            state.context.setdefault("correlation_id", correlation_id)
        new_state, outcome = self._engine.resume_with_input(state, user_input)
        logger.info(
            "TriggerRouter: resumed workflow %s (execution=%s) → %s",
            new_state.workflow_id,
            new_state.execution_id,
            outcome.type,
        )
        return new_state

    # ------------------------------------------------------------------
    # Subscription helper
    # ------------------------------------------------------------------

    def subscribe_to(
        self,
        event_types: List[str],
        event_bus: "EventBus",
    ) -> None:
        """Register the router's ``handle_event`` on *event_bus*.

        For each event type in *event_types*, subscribes
        ``self.handle_event`` as a handler.  Must be called after the
        registry is fully populated.

        Args:
            event_types: Event types to subscribe to.
            event_bus:   The in-process event bus instance.
        """
        for et in event_types:
            event_bus.subscribe(et, self.handle_event)
            logger.debug("TriggerRouter: subscribed to %r", et)

    def subscribe_all(self, event_bus: "EventBus") -> None:
        """Subscribe to every trigger type known by the registry.

        Scans all registered workflow definitions and subscribes to their
        ``trigger_on`` values.
        """
        seen: set[str] = set()
        for defn in self._registry.list():
            for trigger in defn.trigger_on:
                if trigger not in seen:
                    seen.add(trigger)
                    event_bus.subscribe(trigger, self.handle_event)
        logger.debug(
            "TriggerRouter: subscribed to %d unique event types",
            len(seen),
        )


# Event types that trigger *new* workflow instances (as opposed to resume).
# Includes both generic workflow events and DevSquad pipeline events.
# Each DevSquad event maps to a workflow definition via its ``trigger_on`` field
# in the workflow YAML config.  The registry's ``find_by_trigger()`` auto-discovers
# the mapping at runtime.
_DEVSQUAD_EVENT_TYPES: frozenset[str] = frozenset({
    "sprint.init",
    "prd.completed",
    "solution.completed",
    "delivery_plan.completed",
    "implementation.completed",
    "task_block.completed",
    "review.completed",
    "sprint.completed",
    "sprint.rejected",
    "workflow.external_input",
})

_START_EVENT_TYPES: frozenset[str] = frozenset({
    "workflow.start",
    "workflow.scheduled_trigger",
}) | _DEVSQUAD_EVENT_TYPES
