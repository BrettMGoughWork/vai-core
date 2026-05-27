from __future__ import annotations
from pathlib import Path
from typing import Any

from src.core.config.loader import Config
from .transport import LLMTransport
from .llm_factory import factory

def create_llm_transport(llm_alias: str = None) -> LLMTransport:
    """Create LLMTransport using llms.yaml configuration."""
    
    # Load the YAML config
    llms_path = Path(__file__).resolve().parents[3] / "config" / "llms.yaml"
    
    if not llms_path.exists():
        raise FileNotFoundError(f"llms.yaml not found at {llms_path}")

    default_alias, llm_configs = _load_llm_configs(llms_path)
    
    alias = llm_alias or default_alias
    config = llm_configs.get(alias)

    if not config:
        raise ValueError(f"No LLM config found for alias '{alias}'. Available: {list(llm_configs.keys())}")

    provider = config.get("provider")
    model = config.get("model")

    if not provider or not model:
        raise ValueError(f"LLM config for '{alias}' is missing provider or model")

    # Create provider via factory
    client = factory.create(
        provider_name=provider,
        model=model,
        **{k: v for k, v in config.items() if k not in ("provider", "model", "description")}
    )

    return LLMTransport(client)


def _load_llm_configs(path: Path) -> tuple[str, dict]:
    """Properly parse the llms.yaml structure."""
    content = path.read_text(encoding="utf-8")
    default_alias = "deepseek-chat"
    llm_configs = {}

    current_alias = None

    for line in content.splitlines():
        line = line.rstrip()
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        if line.startswith("default:"):
            default_alias = line.split(":", 1)[1].strip().strip('"')
            continue

        # New alias section
        if stripped.endswith(":") and not stripped.startswith(" "):
            current_alias = stripped[:-1]
            llm_configs[current_alias] = {}
            continue

        # Key-value inside alias
        if current_alias and ":" in stripped:
            key, value = [x.strip() for x in stripped.split(":", 1)]
            # Clean quotes
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            # Try to convert numbers
            if value.replace('.', '', 1).isdigit():
                value = float(value) if '.' in value else int(value)
            llm_configs[current_alias][key] = value

    return default_alias, llm_configs