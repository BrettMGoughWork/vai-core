"""Pytest fixtures for observability tests.

Enables verbose mode so that emit_metric / log / emit_trace actually
dispatch to registered sinks during unit tests.
"""

from __future__ import annotations

import pytest

from src.platform.observability import logging as _obs_logging
from src.platform.observability import metrics as _obs_metrics
from src.platform.observability import tracing as _obs_tracing


@pytest.fixture(autouse=True)
def _enable_observability_verbose() -> None:
    """Ensure metric / log / trace emission works during unit tests."""
    _obs_metrics.set_verbose(True)
    _obs_logging.set_verbose(True)
    _obs_tracing.set_verbose(True)
    yield
    # No teardown needed — each test class manages its own sink state via
    # clear_sinks / register_sink / clear_log_sinks / etc.
