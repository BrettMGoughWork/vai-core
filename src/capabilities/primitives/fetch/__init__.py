"""
Fetch subsystem — unified fetch primitive with multi-mode fallback.

The ``stdlib.fetch`` primitive is the ONLY fetch tool exposed to the LLM.
Individual strategies (http_simple, http_hardened, http_headless_browser,
http_stealth) are hidden internal implementation detail.

Loader::

    count = load_all_primitives(registry)
"""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

from src.capabilities.primitives.base import PrimitiveBase

if TYPE_CHECKING:
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry

from .domain_policy import (
    DomainPolicy,
    interpret_domain_policy,
)
from .errors import (
    FetchError,
    TimeoutError,
    HTTPError,
    ParseError,
    ConnectionError,
    classify_exception,
)
from .fallback_router import (
    FallbackDestination,
    FallbackSelection,
    select_fallback,
)
from .mode_selector import (
    FetchMode,
    ModeHistory,
    ModeSelection,
    select_initial_mode,
)
from .request import FetchRequest
from .response import FetchResponse
from .signal_extraction import (
    FetchSignals,
    extract_signals,
)
from .fetch_primitive import FetchPrimitive
from .fetch_url import (
    FetchResult,
    fetch_url,
)
from .sanitisation import sanitise_response
from .signal_fallback import (
    FallbackDecision,
    SignalFallbackDestination,
    choose_next_mode,
    hydrate_next_request,
)

__all__ = [
    "DomainPolicy",
    "interpret_domain_policy",
    "FetchError",
    "TimeoutError",
    "HTTPError",
    "ParseError",
    "ConnectionError",
    "classify_exception",
    "FallbackDestination",
    "FallbackSelection",
    "select_fallback",
    "FetchMode",
    "ModeHistory",
    "ModeSelection",
    "select_initial_mode",
    "FetchRequest",
    "FetchResponse",
    "FetchSignals",
    "extract_signals",
    "FallbackDecision",
    "SignalFallbackDestination",
    "choose_next_mode",
    "hydrate_next_request",
    "FetchResult",
    "fetch_url",
    "sanitise_response",
    "FetchPrimitive",
    "load_all_primitives",
]

# ------------------------------------------------------------------
# Primitive auto-discovery loader
# ------------------------------------------------------------------

_FETCH_DIR = Path(__file__).resolve().parent

# Modules whose imports are expected to fail when optional deps are absent.
_OPTIONAL_FETCH_MODULES: set[str] = set()


def load_all_primitives(
    registry: PrimitiveRegistry,
) -> int:
    """Auto-discover the unified FetchPrimitive and register it.

    Scans ``src/capabilities/primitives/fetch/`` for ``*Primitive`` classes
    and registers them.  The individual HTTP strategy primitives live under
    ``stdlib/`` and are NOT scanned here — only the orchestrator wrapper
    (``FetchPrimitive``) is exposed.

    Returns the count of successfully registered primitives.
    """
    count = 0

    for py_file in sorted(_FETCH_DIR.glob("*.py")):
        if py_file.name.startswith("_") or py_file.name == "__init__.py":
            continue

        module_name = f"src.capabilities.primitives.fetch.{py_file.stem}"

        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue

        for attr_name in dir(module):
            if not attr_name.endswith("Primitive"):
                continue
            cls = getattr(module, attr_name)
            if not isinstance(cls, type) or not issubclass(cls, PrimitiveBase):
                continue
            if cls is PrimitiveBase:
                continue

            try:
                instance = cls()
                registry.register(instance.name, instance)
                count += 1
            except Exception:
                continue

    return count
