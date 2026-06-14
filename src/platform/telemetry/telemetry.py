"""
Deprecated — superseded by ``src.platform.observability.metrics``.

The ``emit_metric()`` module in ``observability.metrics`` replaces this
legacy in-memory Telemetry class.  Use ``emit_metric(name, value, labels)``
for all structured metric events instead of the old counter/timer API.
"""

from src.platform.observability.metrics import emit_metric  # noqa: F401