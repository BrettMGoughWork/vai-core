"""stdlib.skill.author — Author a new capability skill (Phase 3.17.5).

Exposes ``SkillAuthor.author_skill()`` as a discoverable primitive so the
LLM agent knows it can create new skills at runtime.

Uses lazy pipeline wiring — call ``set_author_pipeline()`` at bootstrap
to inject the ``SkillAuthor`` instance into this module.  The primitive
itself is no-arg constructable for stdlib auto-discovery.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType

if TYPE_CHECKING:
    from src.capabilities.skills.author import SkillAuthor
from src.strategy.types.validation import deadcode_ignore


# ── Lazy pipeline wiring ──────────────────────────────────────────────────
# Set by bootstrap code before any execution.  This lets the primitive be
# no-arg constructed during stdlib auto-discovery while still having access
# to the full SkillAuthor pipeline (which requires PrimitiveRegistry,
# CapabilitySkillRegistry, and SkillSafetyValidator).

_author_instance: SkillAuthor | None = None


def set_author_pipeline(author: SkillAuthor) -> None:
    """Inject the ``SkillAuthor`` pipeline instance for runtime use.

    Must be called once at bootstrap, after all registries are wired up
    but before any agent planning/execution begins.
    """
    global _author_instance
    _author_instance = author


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class SkillAuthorPrimitive(PrimitiveBase):
    """Expose ``SkillAuthor.author_skill()`` to the agent as a primitive.

    The agent invokes this via the ``skill.author`` skill, passing raw
    ``.skill.md`` text.  The skill enters the quarantine workflow by
    default — human governance must approve before it becomes active.
    """

    name = "stdlib.skill.author"
    description = (
        "Author a new capability skill from raw .skill.md text. "
        "The skill is quarantined by default and requires human approval."
    )
    primitive_type = PrimitiveType.PYTHON

    def __init__(self) -> None:
        super().__init__(
            name=self.name,
            description=self.description,
            primitive_type=self.primitive_type,
        )

    def validate_args(self, args: dict) -> None:
        if not isinstance(args, dict):
            raise ValueError(f"args must be a dict, got {type(args).__name__}")
        if "skill_text" not in args:
            raise ValueError("args must contain 'skill_text' key")
        if not isinstance(args["skill_text"], str):
            raise ValueError("args['skill_text'] must be a string")
        if not args["skill_text"].strip():
            raise ValueError("args['skill_text'] must not be empty")
        # Optional args type-checks
        if "plugin_name" in args and not isinstance(args["plugin_name"], str):
            raise ValueError("args['plugin_name'] must be a string")
        if "quarantine" in args and not isinstance(args["quarantine"], bool):
            raise ValueError("args['quarantine'] must be a boolean")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        """Parse, validate, sandbox, and quarantine an agent-authored skill.

        Delegates to the lazily-wired ``SkillAuthor`` pipeline.  Raises
        ``RuntimeError`` if ``set_author_pipeline()`` has not been called.
        """
        self.validate_args(args)

        global _author_instance
        if _author_instance is None:
            return PrimitiveResult(
                status="error",
                error="SkillAuthor pipeline not wired — call set_author_pipeline() at bootstrap",
            )

        try:
            skill = _author_instance.author_skill(
                raw_text=args["skill_text"],
                plugin_name=args.get("plugin_name", "agent"),
                plugin_version=args.get("plugin_version", "0.1.0"),
                quarantine=args.get("quarantine", True),
            )

            return PrimitiveResult(
                status="success",
                data={
                    "name": skill.manifest.name,
                    "description": skill.manifest.description,
                    "status": "quarantined" if args.get("quarantine", True) else "registered",
                },
            )
        except ValueError as exc:
            return PrimitiveResult(
                status="error",
                error=str(exc),
            )
