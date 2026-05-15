import json
import os
from pathlib import Path

_DEFAULT_CONFIG = (Path(__file__).resolve().parents[3] / "config" / "default.json")
# parents[0]=config dir, [1]=core, [2]=src, [3]=repo root

class Config:
    """
    MVP: load JSON config + allow environment overrides.
    Read-only, deterministic.
    """

    def __init__(self, path=None):
        path = path or _DEFAULT_CONFIG
        with open(path, "r") as f:
            self._data = json.load(f)

        # Optional: environment overrides
        model_override = os.environ.get("VAI_LLM_MODEL")
        if model_override:
            self._data["llm"]["model"] = model_override

    def get(self, *keys, default=None):
        """
        Access nested config values:
        config.get("llm", "model")
        """
        node = self._data
        for k in keys:
            if k not in node:
                return default
            node = node[k]
        return node