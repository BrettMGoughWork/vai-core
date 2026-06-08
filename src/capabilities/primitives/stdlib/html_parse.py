"""stdlib.html.parse — Parse HTML text into a navigable BeautifulSoup object (as dict) (Phase 3.18.2)."""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType


class HtmlParsePrimitive(PrimitiveBase):
    """Parse HTML text into a navigable BeautifulSoup object (as dict)."""

    name = "stdlib.html.parse"
    description = "Parse HTML text into a navigable BeautifulSoup object (as dict)"
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
        if "text" not in args:
            raise ValueError("args must contain 'text' key")
        text = args["text"]
        if not isinstance(text, str):
            raise ValueError(f"'text' must be a string, got {type(text).__name__}")
        if not text:
            raise ValueError("'text' must not be empty")

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        self.validate_args(args)
        text = args["text"]
        try:
            soup = BeautifulSoup(text, "lxml")
        except ValueError as exc:
            return PrimitiveResult(
                status="error",
                data=None,
                error=f"ValueError: {exc}",
            )
        return PrimitiveResult(
            status="success",
            data={
                "html": soup.prettify(),
                "text": soup.get_text(),
            },
        )
