"""
Phase 5.7 — Lightweight in-process Event Bus

A stand-in for S4's event substrate. This allows the workflow layer to
develop and test the Trigger Router independently of S4.

The contract mirrors what S4b's event substrate will eventually provide:
    - subscribe(event_type, handler)
    - publish(event)

When S4b is available, this will be replaced by a connection to the real
event substrate. The public API is designed to be a drop-in replacement.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Dict, List

from src.agent.workflow.trigger_router import WorkflowEvent

logger = logging.getLogger(__name__)

# Handler signature: callable accepting a single WorkflowEvent.
EventHandler = Callable[[WorkflowEvent], Any]


class EventBus:
    """In-process publish / subscribe event bus.

    Usage::

        bus = EventBus()
        bus.subscribe("workflow.start", my_handler)
        bus.publish(WorkflowEvent(event_type="workflow.start", ...))
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[EventHandler]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register *handler* to be called when *event_type* is published.

        Handlers are called in registration order.  Multiple subscriptions
        to the same (event_type, handler) pair are allowed.
        """
        self._subscribers.setdefault(event_type, []).append(handler)
        logger.debug("EventBus: subscribed handler for %r", event_type)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Remove *handler* from *event_type*'s subscriber list."""
        handlers = self._subscribers.get(event_type)
        if handlers:
            try:
                handlers.remove(handler)
            except ValueError:
                pass
            logger.debug("EventBus: unsubscribed handler for %r", event_type)

    def publish(
        self,
        event_type: str,
        payload: Dict[str, Any] | None = None,
        correlation_id: str | None = None,
        event: WorkflowEvent | None = None,
    ) -> None:
        """Publish an event to all subscribers.

        Args:
            event_type:     Event type string (e.g. ``"workflow.start"``).
            payload:        Event payload (merged with ``event`` if both given).
            correlation_id: Optional trace ID.
            event:          Pre-constructed ``WorkflowEvent``.  If provided,
                            ``event_type`` and ``payload`` are ignored.
        """
        if event is not None:
            resolved = event
        else:
            resolved = WorkflowEvent(
                event_type=event_type,
                payload=payload or {},
                correlation_id=correlation_id or uuid.uuid4().hex,
                timestamp=time.time(),
            )

        handlers = self._subscribers.get(resolved.event_type, [])
        if not handlers:
            logger.debug("EventBus: no subscribers for %r", resolved.event_type)
            return

        for handler in handlers:
            try:
                handler(resolved)
            except Exception:
                logger.exception(
                    "EventBus: handler failed for %r (correlation_id=%s)",
                    resolved.event_type,
                    resolved.correlation_id,
                )

    def clear(self) -> None:
        """Remove all subscribers."""
        self._subscribers.clear()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def subscriber_count(self) -> int:
        """Total number of handler registrations across all event types."""
        return sum(len(h) for h in self._subscribers.values())
