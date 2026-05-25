from dataclasses import dataclass
from typing import Any, Dict, Optional, Callable

from src.primitives.runtime.toolspec import ToolSpec
from src.primitives.runtime.registry import SkillRegistry
from src.primitives.runtime.categories import SkillCategory
from src.primitives.runtime.side_effects import SideEffect
from src.primitives.runtime.schema import generate_schema_from_handler
from src.primitives.runtime.validator import validate_structural, ValidationError
from src.primitives.runtime.semantic import validate_semantic, SemanticValidationError
from src.primitives.runtime.canonical import canonicalize_args

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

        # canonicalisation
        clean = canonicalize_args(self.spec.schema, kwargs)

        # structural validation
        validate_structural(self.spec.schema, clean)

        # semantic validation
        validate_semantic(self.spec.schema, clean)
        
        return self.spec.run(**clean)

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