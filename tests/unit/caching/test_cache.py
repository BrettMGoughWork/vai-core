"""
Contract tests for src.caching.cache.Cache.

Validates fingerprint stability, determinism, key-ordering invariance,
and basic get/set round-trip contract.
"""
import pytest

from src.caching.cache import Cache


class TestCacheFingerprint:
    def test_same_input_produces_same_fingerprint(self):
        cache = Cache()
        action = {"tool": "echo", "args": {"text": "hello"}}

        assert cache.fingerprint(action) == cache.fingerprint(action)

    def test_different_inputs_produce_different_fingerprints(self):
        cache = Cache()
        a = cache.fingerprint({"tool": "echo", "args": {"text": "hello"}})
        b = cache.fingerprint({"tool": "echo", "args": {"text": "goodbye"}})

        assert a != b

    def test_key_ordering_does_not_affect_fingerprint(self):
        cache = Cache()
        ordered = {"a": 1, "b": 2, "c": 3}
        reversed_order = {"c": 3, "b": 2, "a": 1}

        assert cache.fingerprint(ordered) == cache.fingerprint(reversed_order)

    def test_fingerprint_is_hex_string(self):
        fp = Cache().fingerprint({"key": "value"})
        int(fp, 16)  # raises ValueError if not valid hex

    def test_fingerprint_length_is_64_chars(self):
        fp = Cache().fingerprint({"key": "value"})
        assert len(fp) == 64  # SHA-256 hex digest

    def test_fingerprint_is_stable_across_instances(self):
        action = {"tool": "add", "args": {"a": 1, "b": 2}}
        assert Cache().fingerprint(action) == Cache().fingerprint(action)


class TestCacheGetSet:
    def test_get_returns_none_for_unknown_key(self):
        assert Cache().get("nonexistent-key") is None

    def test_set_then_get_returns_value(self):
        cache = Cache()
        cache.set("key1", {"result": "ok"})

        assert cache.get("key1") == {"result": "ok"}

    def test_overwrite_key_updates_value(self):
        cache = Cache()
        cache.set("k", {"v": 1})
        cache.set("k", {"v": 2})

        assert cache.get("k") == {"v": 2}

    def test_multiple_keys_stored_independently(self):
        cache = Cache()
        cache.set("a", {"x": 1})
        cache.set("b", {"x": 2})

        assert cache.get("a") == {"x": 1}
        assert cache.get("b") == {"x": 2}

    def test_fingerprint_round_trip(self):
        cache = Cache()
        action = {"tool": "echo", "args": {"text": "test"}}
        key = cache.fingerprint(action)
        cache.set(key, action)

        assert cache.get(key) == action

    def test_instances_do_not_share_state(self):
        c1 = Cache()
        c2 = Cache()
        c1.set("shared-key", {"owner": "c1"})

        assert c2.get("shared-key") is None
