from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, TypeVar

T = TypeVar("T", bound=Any)

@dataclass(frozen=True)
class DeadCodeIgnore:
    """Metadata attached to ignored symbols for the dead-code analyser."""
    reason: str = ""
    ticket: str = ""          # e.g. "ENG-1234"
    until: str = ""           # e.g. "2026-12-31" (string keeps it dependency-free)

def deadcode_ignore(
    obj: Optional[T] = None,
    *,
    reason: str = "",
    ticket: str = "",
    until: str = "",
) -> Any:
    """
    Mark a function or class as intentionally ignored by the dead-code analyser.

    - Does *not* change runtime behaviour.
    - Attaches __deadcode_ignore__ metadata for tooling to consume.
    """
    def _decorate(target: T) -> T:
        setattr(target, "__deadcode_ignore__", DeadCodeIgnore(reason=reason, ticket=ticket, until=until))
        return target

    # Support both @deadcode_ignore and @deadcode_ignore(...)
    return _decorate(obj) if obj is not None else _decorate