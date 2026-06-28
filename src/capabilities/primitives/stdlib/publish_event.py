"""publish_event primitive — publishes an event via the runtime EventBus."""

from __future__ import annotations

from typing import Any

from src.domain.primitives import PrimitiveBase, PrimitiveResult, PrimitiveType


class PublishEventPrimitive(PrimitiveBase):
    """Publish an event to the in-process EventBus.

    Used by DevSquad workflow steps (and any other workflow) to emit
    completion and progress events that trigger downstream workflows.
    """

    name = "stdlib.publish_event"
    description = (
        "Publish an event to the in-process EventBus. "
        "Accepts 'event_type' (str) and optional 'payload' (dict) and "
        "'correlation_id' (str)."
    )
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "event_type": {
                "type": "string",
                "description": "Event type string (e.g. 'prd.completed')",
            },
            "payload": {
                "type": "object",
                "description": "Optional event payload dict",
            },
            "correlation_id": {
                "type": "string",
                "description": "Optional correlation/tracking ID",
            },
        },
        "required": ["event_type"],
    }

    def __init__(self) -> None:
        super().__init__(
            name=self.name,
            description=self.description,
            primitive_type=self.primitive_type,
        )

    def validate_args(self, args: dict) -> None:
        if not isinstance(args, dict):
            raise ValueError(f"args must be a dict, got {type(args).__name__}")
        if "event_type" not in args:
            raise ValueError("args must contain 'event_type' key")
        if not isinstance(args["event_type"], str):
            raise ValueError(
                f"'event_type' must be a string, got {type(args['event_type']).__name__}"
            )

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)

        # Lazy import to avoid circular dependency at module level.
        from src.agent.composition_root import get_event_bus

        try:
            bus = get_event_bus()
            bus.publish(
                event_type=args["event_type"],
                payload=args.get("payload"),
                correlation_id=args.get("correlation_id"),
            )
            return PrimitiveResult(
                status="success",
                data={
                    "published": args["event_type"],
                    "correlation_id": args.get("correlation_id"),
                },
            )
        except Exception as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"PublishEventError: {exc}",
            )
