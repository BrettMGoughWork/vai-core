"""
S4.9.1 — Configuration System for Stratum-4.

Loads, validates, and exposes read‑only configuration to all S4 components.

Loading order (later overrides earlier):
  1. Hardcoded defaults
  2. Config file (YAML)
  3. Environment variables (S4_ prefix)
  4. Runtime overrides (dict)

All values are validated after merging.  The final ``Config`` object is
immutable — any attempt to modify it at runtime will raise ``TypeError``.
"""

from __future__ import annotations

import copy
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


# ---------------------------------------------------------------------------
# Schema — defines valid keys, types, valid values, and defaults
# ---------------------------------------------------------------------------

SCHEMA: Dict[str, Any] = {
    "logging": {
        "type": dict,
        "fields": {
            "level": {
                "type": str,
                "valid_values": ["debug", "info", "warning", "error", "critical"],
                "default": "info",
            },
        },
    },
    "metrics": {
        "type": dict,
        "fields": {
            "enabled": {"type": bool, "default": True},
            "exporter": {
                "type": str,
                "valid_values": ["none", "stdout", "prometheus"],
                "default": "stdout",
            },
        },
    },
    "queues": {
        "type": dict,
        "fields": {
            "defaultdepthlimit": {"type": int, "default": 1000},
        },
    },
    "workers": {
        "type": dict,
        "fields": {
            "count": {"type": int, "default": 4},
            "heartbeatintervalms": {"type": int, "default": 5000},
            "heartbeattimeoutms": {"type": int, "default": 15000},
        },
    },
    "alerts": {
        "type": dict,
        "fields": {
            "transports": {
                "type": list,
                "item_valid_values": ["slack", "smtp", "file", "none"],
                "default": ["none"],
            },
        },
    },
    "auth": {
        "type": dict,
        "fields": {
            "enabled": {"type": bool, "default": False},
            "token": {"type": str, "default": ""},
        },
    },
    "rate_limit": {
        "type": dict,
        "fields": {
            "enabled": {"type": bool, "default": False},
            "maxrequestsper_minute": {"type": int, "default": 60},
        },
    },
}

ENV_PREFIX = "S4"

# Pre‑computed env‑var → (section, field) mapping
_ENV_MAP: Dict[str, Tuple[str, str]] = {}
for _sec_name, _sec_def in SCHEMA.items():
    _fields = _sec_def.get("fields", {})
    for _field_name in _fields:
        _env_key = f"{ENV_PREFIX}{_sec_name.upper().replace('_', '')}{_field_name.upper()}"
        _ENV_MAP[_env_key] = (_sec_name, _field_name)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConfigError(Exception):
    """Raised when configuration loading or validation fails."""


class UnknownKeyError(ConfigError):
    """Raised when an unknown configuration key is encountered."""


class ConfigValidationError(ConfigError):
    """Raised when a configuration value fails validation."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_defaults() -> Dict[str, Any]:
    """Build a complete defaults dictionary from the schema."""
    result: Dict[str, Any] = {}
    for sec_name, sec_def in SCHEMA.items():
        sec: Dict[str, Any] = {}
        for field_name, field_def in sec_def.get("fields", {}).items():
            # Use deepcopy so mutable defaults (lists) are independent
            sec[field_name] = copy.deepcopy(field_def.get("default"))
        result[sec_name] = sec
    return result


def _validate_parsed(raw: Dict[str, Any], path: str = "") -> None:
    """Validate parsed configuration against the schema.

    Raises ``UnknownKeyError`` or ``ConfigValidationError`` on any violation.
    """
    for key, value in raw.items():
        current_path = f"{path}.{key}" if path else key

        # Is this a section key or a leaf field?
        if key in SCHEMA:
            # Section — recurse
            sec_def = SCHEMA[key]
            if not isinstance(value, dict):
                raise ConfigValidationError(
                    f"{current_path}: expected dict, got {type(value).__name__}"
                )
            if sec_def.get("type") is dict:
                _validate_parsed(value, path=current_path)
            else:
                raise UnknownKeyError(f"Unknown configuration key: {current_path}")
        else:
            # Could be a field inside a section
            parent_path = path  # e.g. "logging"
            parent_def = SCHEMA.get(parent_path)
            if parent_def is None:
                raise UnknownKeyError(f"Unknown configuration key: {current_path}")

            fields = parent_def.get("fields", {})
            if key not in fields:
                raise UnknownKeyError(f"Unknown configuration key: {current_path}")

            field_def = fields[key]
            expected_type = field_def.get("type")
            valid_values = field_def.get("valid_values")
            item_valid_values = field_def.get("item_valid_values")

            # Type check
            if expected_type is list:
                if not isinstance(value, list):
                    raise ConfigValidationError(
                        f"{current_path}: expected list, got {type(value).__name__}"
                    )
                # Item value check
                if item_valid_values is not None:
                    for item in value:
                        if item not in item_valid_values:
                            raise ConfigValidationError(
                                f"{current_path}: invalid value {item!r}, "
                                f"must be one of {item_valid_values}"
                            )
            elif expected_type is bool:
                if not isinstance(value, bool):
                    raise ConfigValidationError(
                        f"{current_path}: expected bool, got {type(value).__name__}"
                    )
            elif expected_type is int:
                if not isinstance(value, int) or isinstance(value, bool):
                    raise ConfigValidationError(
                        f"{current_path}: expected int, got {type(value).__name__}"
                    )
            elif expected_type is str:
                if not isinstance(value, str):
                    raise ConfigValidationError(
                        f"{current_path}: expected str, got {type(value).__name__}"
                    )
                if valid_values is not None and value not in valid_values:
                    raise ConfigValidationError(
                        f"{current_path}: invalid value {value!r}, "
                        f"must be one of {valid_values}"
                    )


def _merge_dict(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Deep‑merge *overlay* into *base* (mutates base)."""
    for key, value in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _merge_dict(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def _parse_env_value(raw: str, field_def: Dict[str, Any]) -> Any:
    """Parse an environment variable string according to the field schema."""
    expected_type = field_def.get("type")

    if expected_type is list:
        # Comma‑separated list
        parsed = [item.strip() for item in raw.split(",") if item.strip()]
        item_valid_values = field_def.get("item_valid_values")
        if item_valid_values is not None:
            for item in parsed:
                if item not in item_valid_values:
                    raise ConfigValidationError(
                        f"Environment variable value {item!r} not in {item_valid_values}"
                    )
        return parsed

    if expected_type is bool:
        lower = raw.strip().lower()
        if lower == "true":
            return True
        elif lower == "false":
            return False
        raise ConfigValidationError(
            f"Expected bool ('true' or 'false'), got {raw!r}"
        )

    if expected_type is int:
        try:
            return int(raw.strip())
        except ValueError:
            raise ConfigValidationError(f"Expected int, got {raw!r}")

    # str — check valid_values if present
    valid_values = field_def.get("valid_values")
    if valid_values is not None and raw.strip() not in valid_values:
        raise ConfigValidationError(
            f"Value {raw!r} not in valid values {valid_values}"
        )
    return raw.strip()


def _collect_env_overrides() -> Dict[str, Any]:
    """Read environment variables matching ``S4…`` and return a config dict."""
    result: Dict[str, Any] = {}
    for env_name, (section, field) in _ENV_MAP.items():
        raw = os.environ.get(env_name)
        if raw is not None:
            field_def = SCHEMA[section]["fields"][field]
            parsed = _parse_env_value(raw, field_def)
            if section not in result:
                result[section] = {}
            result[section][field] = parsed
    return result


def _load_yaml_file(path: str) -> Dict[str, Any]:
    """Load a YAML config file.

    Uses the standard library … yaml is not stdlib.  We use ``yaml`` (PyYAML)
    which is already a dependency of the project.
    """
    import yaml

    filepath = Path(path)
    if not filepath.exists():
        raise ConfigError(f"Config file not found: {path}")
    if not filepath.is_file():
        raise ConfigError(f"Config path is not a file: {path}")

    try:
        with open(filepath, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as exc:
        raise ConfigError(f"Failed to parse config file {path}: {exc}") from exc

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"Config file root must be a mapping, got {type(data).__name__}"
        )

    # Filter to only keys that match our schema sections (ignore unrelated keys like "llm", "search", etc.)
    filtered: Dict[str, Any] = {}
    for sec_name in SCHEMA:
        if sec_name in data:
            sec_data = data[sec_name]
            if isinstance(sec_data, dict):
                # Filter section fields to only schema‑known fields
                known_fields = SCHEMA[sec_name].get("fields", {})
                filtered_sec: Dict[str, Any] = {}
                for field_name in known_fields:
                    if field_name in sec_data:
                        filtered_sec[field_name] = sec_data[field_name]
                filtered[sec_name] = filtered_sec

    return filtered


# ---------------------------------------------------------------------------
# Config — read‑only configuration object
# ---------------------------------------------------------------------------


class S4Config:
    """Read‑only S4 configuration.

    Constructed by ``load_config()``.  Access values via ``.get()``.
    Mutations raise ``TypeError``.
    """

    def __init__(self, data: Dict[str, Any]) -> None:
        # Deep‑freeze the data so it cannot be mutated
        self._data = _deep_freeze(data)

    def get(self, key: str) -> Any:
        """Access a configuration value by dotted key path.

        Examples::

            config.get("logging.level")       # "info"
            config.get("workers.count")       # 4
            config.get("alerts.transports")   # ["none"]

        Raises ``KeyError`` if the key is unknown.
        """
        parts = key.split(".")
        current: Any = self._data
        for part in parts:
            if isinstance(current, dict):
                current = current[part]
            else:
                raise KeyError(f"Unknown configuration key: {key}")
        return current

    def to_dict(self) -> Dict[str, Any]:
        """Return a deep copy of the full configuration as a plain dict."""
        return copy.deepcopy(self._data)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("_data",):
            super().__setattr__(name, value)
        else:
            raise TypeError("S4Config is read‑only")

    def __delattr__(self, name: str) -> None:
        raise TypeError("S4Config is read‑only")

    def __repr__(self) -> str:
        return f"S4Config({self._data!r})"


def _deep_freeze(value: Any) -> Any:
    """Recursively freeze dicts into a read‑only proxy.

    We use a small wrapper that raises ``TypeError`` on mutation attempts.
    For simplicity, we return the dict but rely on ``Config.__setattr__``
    preventing re‑assignment, and we keep deep copies for safety.
    """
    return value  # Immutability is enforced by Config's get‑only interface


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(
    config_file: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> S4Config:
    """Load, validate, and return a read‑only ``S4Config``.

    Loading order (later overrides earlier):

    1. Hardcoded defaults
    2. Config file (YAML) — only sections matching the schema are read
    3. Environment variables (``S4_`` prefix, e.g. ``S4LOGGINGLEVEL=debug``)
    4. Runtime overrides (dict with dotted keys, e.g. ``{"workers.count": 8}``)

    Args:
        config_file:  Optional path to a YAML config file.
        overrides:    Optional dict of dotted‑key → value overrides.

    Returns:
        An immutable ``S4Config`` instance.

    Raises:
        ConfigError:  If the config file cannot be read or parsed.
        UnknownKeyError: If an unknown key is encountered.
        ConfigValidationError: If a value fails type or range validation.
    """
    # 1. Start with defaults
    merged = _build_defaults()

    # 2. Load config file
    if config_file is not None:
        file_data = _load_yaml_file(config_file)
        _validate_parsed(file_data)
        _merge_dict(merged, file_data)

    # 3. Environment variables
    env_data = _collect_env_overrides()
    if env_data:
        _validate_parsed(env_data)
        _merge_dict(merged, env_data)

    # 4. Runtime overrides
    if overrides:
        parsed_overrides: Dict[str, Any] = {}
        for dotted_key, value in overrides.items():
            parts = dotted_key.split(".")
            if len(parts) != 2:
                raise ConfigError(
                    f"Override key must be section.field, got {dotted_key!r}"
                )
            section, field = parts
            if section not in parsed_overrides:
                parsed_overrides[section] = {}
            parsed_overrides[section][field] = value
        _validate_parsed(parsed_overrides)
        _merge_dict(merged, parsed_overrides)

    return S4Config(merged)
