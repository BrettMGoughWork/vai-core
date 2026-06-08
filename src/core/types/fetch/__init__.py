"""
Fetch Types — Request/response shapes and error taxonomy for the fetch subsystem.

These types represent all data crossing the S0/S1 fetch boundary. They are pure
data containers with no fetch logic, safe to extend in later phases (3.11 hardened
modes, 3.12 fallback chain).
"""

from .errors import (
    FetchError,
    TimeoutError,
    HTTPError,
    ParseError,
    ConnectionError,
    classify_exception,
)
from .request import FetchRequest
from .response import FetchResponse

__all__ = [
    "FetchError",
    "TimeoutError",
    "HTTPError",
    "ParseError",
    "ConnectionError",
    "classify_exception",
    "FetchRequest",
    "FetchResponse",
]
