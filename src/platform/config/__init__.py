"""S4.9.1 — Configuration System for Stratum-4.

Loads, validates, and exposes read-only configuration to all S4 components.
Supports defaults → config file → environment variables → runtime overrides.

Backward-compat re-export from ``src.config`` — the canonical location.
"""

from __future__ import annotations

from src.config.config_system import ConfigValidationError, S4Config, load_config

__all__ = ["S4Config", "ConfigValidationError", "load_config"]
