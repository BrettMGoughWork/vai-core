"""create_project_structure primitive — creates the project folder structure for a DevSquad sprint."""

from __future__ import annotations

from src.domain.primitives import PrimitiveBase, PrimitiveResult, PrimitiveType
from src.tools.create_project_structure import execute as _create_project_structure


class CreateProjectStructurePrimitive(PrimitiveBase):
    """Create the project directory structure for a DevSquad sprint.

    Wraps ``src.tools.create_project_structure`` so it can be resolved
    both as an inline primitive and via S4B dispatch.
    """

    name = "stdlib.create_project_structure"
    description = (
        "Create the project directory structure for a DevSquad sprint. "
        "Accepts 'project_id' (str, required) and optional 'title' (str)."
    )
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "description": "Unique project identifier",
            },
            "title": {
                "type": "string",
                "description": "Optional human-readable project title",
            },
        },
        "required": ["project_id"],
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
        if "project_id" not in args:
            raise ValueError("args must contain 'project_id' key")
        if not isinstance(args["project_id"], str):
            raise ValueError(
                f"'project_id' must be a string, got {type(args['project_id']).__name__}"
            )

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)

        result = _create_project_structure(
            project_id=args["project_id"],
            title=args.get("title", ""),
        )

        if result.get("status") == "success":
            return PrimitiveResult(
                status="success",
                data={
                    "project_id": result["project_id"],
                    "project_dir": result["project_dir"],
                },
            )
        else:
            return PrimitiveResult(
                status="error",
                data=None,
                error=result.get("error", "CreateProjectStructureError: unknown error"),
            )
