"""Tests for stdlib.sys.uuid primitive (Phase 3.18.8)."""

from __future__ import annotations

import uuid

import pytest

from src.capabilities.primitives.stdlib.sys_uuid import SysUUIDPrimitive


@pytest.fixture
def sys_uuid() -> SysUUIDPrimitive:
    return SysUUIDPrimitive()


class TestSysUUIDPrimitive:
    """Tests for SysUUIDPrimitive.validate_args and execute."""

    def test_uuid4_default(self, sys_uuid: SysUUIDPrimitive) -> None:
        result = sys_uuid.execute({}, {})
        assert result.status == "success"
        uid = uuid.UUID(result.data["uuid"])
        assert uid.version == 4

    def test_uuid4_hex(self, sys_uuid: SysUUIDPrimitive) -> None:
        result = sys_uuid.execute({"format": "hex"}, {})
        assert len(result.data["uuid"]) == 32
        assert "-" not in result.data["uuid"]

    def test_uuid4_urn(self, sys_uuid: SysUUIDPrimitive) -> None:
        result = sys_uuid.execute({"format": "urn"}, {})
        assert result.data["uuid"].startswith("urn:uuid:")

    def test_uuid1(self, sys_uuid: SysUUIDPrimitive) -> None:
        result = sys_uuid.execute({"version": 1}, {})
        uid = uuid.UUID(result.data["uuid"])
        assert uid.version == 1

    def test_uuid3(self, sys_uuid: SysUUIDPrimitive) -> None:
        ns = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"  # DNS namespace
        result = sys_uuid.execute(
            {"version": 3, "namespace": ns, "name": "example.com"}, {}
        )
        uid = uuid.UUID(result.data["uuid"])
        assert uid.version == 3

    def test_uuid5(self, sys_uuid: SysUUIDPrimitive) -> None:
        ns = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
        result = sys_uuid.execute(
            {"version": 5, "namespace": ns, "name": "example.com"}, {}
        )
        uid = uuid.UUID(result.data["uuid"])
        assert uid.version == 5

    def test_uuids_are_unique(self, sys_uuid: SysUUIDPrimitive) -> None:
        uids = set()
        for _ in range(10):
            result = sys_uuid.execute({}, {})
            uids.add(result.data["uuid"])
        assert len(uids) == 10

    def test_invalid_version_raises_value_error(self, sys_uuid: SysUUIDPrimitive) -> None:
        with pytest.raises(ValueError, match="must be 1, 3, 4, or 5"):
            sys_uuid.validate_args({"version": 2})

    def test_invalid_format_raises_value_error(self, sys_uuid: SysUUIDPrimitive) -> None:
        with pytest.raises(ValueError, match="must be 'standard'"):
            sys_uuid.validate_args({"format": "invalid"})

    def test_missing_namespace_for_v3_raises_value_error(self, sys_uuid: SysUUIDPrimitive) -> None:
        with pytest.raises(ValueError, match="must contain 'namespace'"):
            sys_uuid.validate_args({"version": 3, "name": "test"})
