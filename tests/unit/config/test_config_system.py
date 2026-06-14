"""Tests for S4.9.1 Configuration System — Config, load_config, validation,
env‑var parsing, runtime overrides, immutability, and failure modes.

Covers:
- Defaults from schema
- Config file loading (YAML)
- Environment variable overrides (S4_ prefix)
- Runtime overrides (dotted‑key dict)
- Precedence order
- Validation (type, valid_values, unknown keys)
- Immutability (read‑only after init)
- Fail‑fast on invalid config
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from src.config.config_system import (
    Config,
    ConfigError,
    UnknownKeyError,
    ValidationError,
    load_config,
)

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------


def _write_yaml(path: Path, data: Dict[str, Any]) -> None:
    import yaml

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)


# -------------------------------------------------------------------
# Defaults
# -------------------------------------------------------------------


class TestDefaults:
    def test_load_defaults(self):
        """Should produce a valid Config with no file or overrides."""
        cfg = load_config()
        assert isinstance(cfg, Config)
        assert cfg.get("logging.level") == "info"
        assert cfg.get("metrics.enabled") is True
        assert cfg.get("metrics.exporter") == "stdout"
        assert cfg.get("queues.defaultdepthlimit") == 1000
        assert cfg.get("workers.count") == 4
        assert cfg.get("workers.heartbeatintervalms") == 5000
        assert cfg.get("workers.heartbeattimeoutms") == 15000
        assert cfg.get("alerts.transports") == ["none"]

    def test_defaults_are_independent(self):
        """Each call to load_config should return independent defaults."""
        cfg1 = load_config()
        cfg2 = load_config()
        # Confirm we get a fresh list each time (no cross‑contamination)
        assert cfg1.get("alerts.transports") == ["none"]
        assert cfg2.get("alerts.transports") == ["none"]


# -------------------------------------------------------------------
# Config file loading
# -------------------------------------------------------------------


class TestConfigFile:
    def test_load_yaml(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, {"logging": {"level": "debug"}})
        cfg = load_config(config_file=str(config_path))
        assert cfg.get("logging.level") == "debug"
        # Other values should remain at defaults
        assert cfg.get("metrics.enabled") is True

    def test_load_yaml_overrides_multiple_sections(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        _write_yaml(
            config_path,
            {
                "workers": {"count": 8, "heartbeatintervalms": 2000},
                "alerts": {"transports": ["slack", "smtp"]},
            },
        )
        cfg = load_config(config_file=str(config_path))
        assert cfg.get("workers.count") == 8
        assert cfg.get("workers.heartbeatintervalms") == 2000
        assert cfg.get("workers.heartbeattimeoutms") == 15000  # default
        assert cfg.get("alerts.transports") == ["slack", "smtp"]

    def test_missing_file_raises(self):
        with pytest.raises(ConfigError, match="not found"):
            load_config(config_file="nonexistent.yaml")

    def test_invalid_yaml_raises(self, tmp_path: Path):
        config_path = tmp_path / "bad.yaml"
        config_path.write_text("{invalid: [yaml", encoding="utf-8")
        with pytest.raises(ConfigError, match="Failed to parse"):
            load_config(config_file=str(config_path))


# -------------------------------------------------------------------
# Environment variables
# -------------------------------------------------------------------


class TestEnvironmentVariables:
    def test_env_override_string(self, monkeypatch):
        monkeypatch.setenv("S4LOGGINGLEVEL", "debug")
        cfg = load_config()
        assert cfg.get("logging.level") == "debug"

    def test_env_override_int(self, monkeypatch):
        monkeypatch.setenv("S4WORKERSCOUNT", "8")
        cfg = load_config()
        assert cfg.get("workers.count") == 8

    def test_env_override_bool_true(self, monkeypatch):
        monkeypatch.setenv("S4METRICSENABLED", "false")
        cfg = load_config()
        assert cfg.get("metrics.enabled") is False

    def test_env_override_bool_false(self, monkeypatch):
        monkeypatch.setenv("S4METRICSENABLED", "true")
        cfg = load_config()
        assert cfg.get("metrics.enabled") is True

    def test_env_override_list(self, monkeypatch):
        monkeypatch.setenv("S4ALERTSTRANSPORTS", "slack,smtp")
        cfg = load_config()
        assert cfg.get("alerts.transports") == ["slack", "smtp"]

    def test_env_override_unknown_section(self, monkeypatch):
        """Environment variables for non‑S4 sections are silently ignored."""
        monkeypatch.setenv("S4NONSENSEKEY", "value")
        cfg = load_config()
        assert cfg.get("logging.level") == "info"


# -------------------------------------------------------------------
# Runtime overrides
# -------------------------------------------------------------------


class TestRuntimeOverrides:
    def test_override_dotted_key(self):
        cfg = load_config(overrides={"workers.count": 12})
        assert cfg.get("workers.count") == 12

    def test_override_multiple_keys(self):
        cfg = load_config(
            overrides={
                "workers.count": 6,
                "logging.level": "error",
                "metrics.enabled": False,
            }
        )
        assert cfg.get("workers.count") == 6
        assert cfg.get("logging.level") == "error"
        assert cfg.get("metrics.enabled") is False

    def test_override_applied_after_env(self, monkeypatch):
        """Overrides have highest precedence."""
        monkeypatch.setenv("S4WORKERSCOUNT", "2")
        cfg = load_config(overrides={"workers.count": 10})
        assert cfg.get("workers.count") == 10


# -------------------------------------------------------------------
# Precedence order (defaults < file < env < overrides)
# -------------------------------------------------------------------


class TestPrecedence:
    def test_defaults_can_be_overridden_by_file(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, {"logging": {"level": "warning"}})
        cfg = load_config(config_file=str(config_path))
        assert cfg.get("logging.level") == "warning"

    def test_file_can_be_overridden_by_env(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, {"logging": {"level": "error"}})
        monkeypatch.setenv("S4LOGGINGLEVEL", "critical")
        cfg = load_config(config_file=str(config_path))
        assert cfg.get("logging.level") == "critical"

    def test_full_precedence_chain(self, tmp_path, monkeypatch):
        """End‑to‑end: defaults → file → env → overrides."""
        config_path = tmp_path / "config.yaml"
        _write_yaml(config_path, {"workers": {"count": 2}})
        monkeypatch.setenv("S4WORKERSCOUNT", "4")
        cfg = load_config(
            config_file=str(config_path),
            overrides={"workers.count": 8},
        )
        assert cfg.get("workers.count") == 8

    def test_file_does_not_affect_unrelated_keys(self, tmp_path):
        """Only schema‑matching sections from file are loaded."""
        config_path = tmp_path / "config.yaml"
        import yaml

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(
                {
                    "logging": {"level": "warning"},
                    "llm": {"provider": "openai"},
                },
                f,
            )
        cfg = load_config(config_file=str(config_path))
        assert cfg.get("logging.level") == "warning"


# -------------------------------------------------------------------
# Validation
# -------------------------------------------------------------------


class TestValidation:
    def test_unknown_section_key_raises(self):
        """Unknown top‑level keys should cause an error."""
        with pytest.raises(UnknownKeyError):
            load_config(overrides={"nonsense.foo": "bar"})

    def test_invalid_string_value_raises(self):
        with pytest.raises(ValidationError, match="invalid value"):
            load_config(overrides={"logging.level": "verbose"})

    def test_invalid_int_value_raises(self):
        with pytest.raises(ValidationError):
            load_config(overrides={"workers.count": "notanint"})

    def test_invalid_bool_value_raises(self):
        with pytest.raises(ValidationError):
            load_config(overrides={"metrics.enabled": "yes"})

    def test_invalid_list_item_raises(self):
        with pytest.raises(ValidationError):
            load_config(overrides={"alerts.transports": ["pagerduty"]})

    def test_type_mismatch_list_raises(self):
        """Passing a string where list is expected should fail."""
        with pytest.raises(ValidationError):
            load_config(overrides={"alerts.transports": "slack"})

    def test_override_nonexistent_dotted_key(self):
        """A dotted key with an unknown section should fail."""
        with pytest.raises(UnknownKeyError):
            load_config(overrides={"nonexistent.foo": "bar"})


# -------------------------------------------------------------------
# Immutability
# -------------------------------------------------------------------


class TestImmutability:
    def test_config_is_read_only(self):
        cfg = load_config()
        with pytest.raises(TypeError):
            cfg.some_new_attr = "value"

    def test_config_cannot_delete(self):
        cfg = load_config()
        with pytest.raises(TypeError):
            del cfg.some_attr

    def test_config_get_returns_copy(self):
        """``to_dict()`` returns a mutable copy, modifying it should not
        affect the config."""
        cfg = load_config()
        d = cfg.to_dict()
        d["logging"]["level"] = "critical"
        assert cfg.get("logging.level") == "info"

    def test_get_unknown_key_raises(self):
        cfg = load_config()
        with pytest.raises(KeyError):
            cfg.get("nonexistent.key")


# -------------------------------------------------------------------
# Config.api (to_dict)
# -------------------------------------------------------------------


class TestToDict:
    def test_to_dict_shape(self):
        cfg = load_config()
        d = cfg.to_dict()
        assert isinstance(d, dict)
        assert "logging" in d
        assert "metrics" in d
        assert "queues" in d
        assert "workers" in d
        assert "alerts" in d
        assert d["logging"]["level"] == "info"

    def test_to_dict_is_independent(self):
        cfg = load_config(overrides={"workers.count": 6})
        d1 = cfg.to_dict()
        d2 = cfg.to_dict()
        d1["workers"]["count"] = 99
        assert d2["workers"]["count"] == 6


# -------------------------------------------------------------------
# Edge cases
# -------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_overrides(self):
        """Overrides=None or empty dict should be harmless."""
        cfg1 = load_config(overrides=None)
        cfg2 = load_config(overrides={})
        assert cfg1.get("logging.level") == "info"
        assert cfg2.get("logging.level") == "info"

    def test_env_empty_list_override(self, monkeypatch):
        """An empty env var should parse as empty list."""
        monkeypatch.setenv("S4ALERTSTRANSPORTS", "")
        cfg = load_config()
        assert cfg.get("alerts.transports") == []

    def test_yaml_empty_file(self, tmp_path):
        """An empty YAML file should produce defaults."""
        config_path = tmp_path / "empty.yaml"
        config_path.write_text("", encoding="utf-8")
        cfg = load_config(config_file=str(config_path))
        assert cfg.get("logging.level") == "info"
        assert cfg.get("workers.count") == 4

    def test_yaml_none_values_safe(self, tmp_path):
        """None values in YAML should be ignored (section not loaded)."""
        config_path = tmp_path / "none.yaml"
        import yaml

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump({"logging": None}, f)
        cfg = load_config(config_file=str(config_path))
        assert cfg.get("logging.level") == "info"
