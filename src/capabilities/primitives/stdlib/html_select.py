"""stdlib.html.select — Select elements from HTML using a CSS selector (Phase 3.18.2)."""

from __future__ import annotations

from bs4 import BeautifulSoup
from soupsieve.util import SelectorSyntaxError

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class HtmlSelectPrimitive(PrimitiveBase):
    """Select elements from HTML using a CSS selector."""

    name = "stdlib.html.select"
    description = "Select elements from HTML using a CSS selector"
    primitive_type = PrimitiveType.PYTHON
    input_schema = {
        "type": "object",
        "properties": {
            "html": {
                "type": "string",
                "description": "HTML text to query",
            },
            "selector": {
                "type": "string",
                "description": "CSS selector (e.g. 'div.content', '.class-name', '#id')",
            },
        },
        "required": ["html", "selector"],
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
        if "html" not in args:
            raise ValueError("args must contain 'html' key")
        html = args["html"]
        if not isinstance(html, str):
            raise ValueError(f"'html' must be a string, got {type(html).__name__}")
        if not html:
            raise ValueError("'html' must not be empty")
        if "selector" not in args:
            raise ValueError("args must contain 'selector' key")
        selector = args["selector"]
        if not isinstance(selector, str):
            raise ValueError(
                f"'selector' must be a string, got {type(selector).__name__}"
            )
        if not selector:
            raise ValueError("'selector' must not be empty")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        html = args["html"]
        selector = args["selector"]
        try:
            soup = BeautifulSoup(html, "lxml")
            results = soup.select(selector)
        except ValueError as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"ValueError: {exc}",
            )
        except SelectorSyntaxError as exc:
            # catches bad CSS selectors passed to .select()
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"SelectorSyntaxError: {exc}",
            )
        return PrimitiveResult(
            status="success",
            data={"matches": [str(element) for element in results]},
        )
