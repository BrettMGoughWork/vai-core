import json
import hashlib

class Cache:
    """
    MVP: in-memory cache for canonical actions.
    Pure performance layer. Never affects correctness.
    """

    def __init__(self):
        self._store = {}

    def fingerprint(self, raw_action: dict) -> str:
        """
        Produce a stable fingerprint for the raw LLM output.
        Sorting keys ensures determinism.
        """
        data = json.dumps(raw_action, sort_keys=True)
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    def get(self, key: str):
        return self._store.get(key)

    def set(self, key: str, value: dict):
        self._store[key] = value