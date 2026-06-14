"""S4.9.1 — Configuration System for Stratum-4.

Loads, validates, and exposes read-only configuration to all S4 components.
Supports defaults → config file → environment variables → runtime overrides.
"""

from __future__ import annotations

from src.platform.config.config_system import S4Config, load_config

__all__ = ["S4Config", "load_config"]
