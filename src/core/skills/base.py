from dataclasses import dataclass
from typing import Any, Dict, Optional, Callable

from .toolspec import ToolSpec
from .registry import SkillRegistry
from .categories import SkillCategory
from .side_effects import SideEffect
from .schema import generate_schema_from_handler
from .validator import validate_structural, ValidationError

@dataclass
class BaseSkill:
    """
    Base class for all skills. Wraps a ToolSpec and provides:
    - schema generation
    - argument validation
    - registry integration
    - execution wrapper
    """

    name: str
    description: str
    handler: Callable[..., Any]
    schema: Optional[Dict[str, Any]] = None
    category: SkillCategory = SkillCategory.GENERAL
    side_effects: SideEffect = SideEffect.NONE
    enabled: bool = True

    def __post_init__(self):
        # If no schema provided, infer a trivial one
        if self.schema is None:
            self.schema = self._infer_schema_from_handler()

        # Create the ToolSpec
        self.spec = ToolSpec(
            name=self.name,
            description=self.description,
            schema=self.schema,
            handler=self.handler,
            category=self.category,
            side_effects=self.side_effects,
            enabled=self.enabled,
        )

        # Register with the global skill registry
        SkillRegistry.register(self)

    # ---------------------------------------------------------
    # Schema inference (minimal for now — expanded later)
    # ---------------------------------------------------------
    def _infer_schema_from_handler(self) -> Dict[str, Any]:
        """
        Infer a JSON schema from the handler's type hints.
        """
        return generate_schema_from_handler(self.handler)

    # ---------------------------------------------------------
    # Execution wrapper
    # ---------------------------------------------------------
    def run(self, **kwargs) -> Any:
        """
        Validate arguments and execute the handler.
        """
        validate_structural(self.spec.schema, kwargs)
        return self.spec.run(**kwargs)

    # ---------------------------------------------------------
    # What the LLM sees
    # ---------------------------------------------------------
    def to_llm_spec(self) -> Dict[str, Any]:
        """
        Convert to the JSON structure the LLM expects.
        """
        return {
            "name": self.spec.name,
            "description": self.spec.description,
            "parameters": self.spec.schema,
        }