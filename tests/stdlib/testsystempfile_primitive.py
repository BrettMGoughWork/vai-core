"""Tests for stdlib.sys.tempfile primitive (Phase 3.18.8)."""

from __future__ import annotations

import os

import pytest

from src.capabilities.primitives.stdlib.sys_tempfile import SysTempFilePrimitive


@pytest.fixture
def sys_tempfile() -> SysTempFilePrimitive:
    return SysTempFilePrimitive()


class TestSysTempFilePrimitive:
    """Tests for SysTempFilePrimitive.validate_args and execute."""

    def test_create_tempfile(self, sys_tempfile: SysTempFilePrimitive) -> None:
        result = sys_tempfile.execute({}, {})
        try:
            assert result.status == "success"
            assert os.path.exists(result.data["path"])
            assert result.data["exists"] is True
            assert result.data["size_bytes"] == 0
        finally:
            os.unlink(result.data["path"])

    def test_create_with_content(self, sys_tempfile: SysTempFilePrimitive) -> None:
        result = sys_tempfile.execute({"content": "hello world"}, {})
        try:
            assert result.data["size_bytes"] == 11
            with open(result.data["path"]) as f:
                assert f.read() == "hello world"
        finally:
            os.unlink(result.data["path"])

    def test_create_with_suffix(self, sys_tempfile: SysTempFilePrimitive) -> None:
        result = sys_tempfile.execute({"suffix": ".txt"}, {})
        try:
            assert result.data["path"].endswith(".txt")
        finally:
            os.unlink(result.data["path"])

    def test_create_with_prefix(self, sys_tempfile: SysTempFilePrimitive) -> None:
        result = sys_tempfile.execute({"prefix": "mytest_"}, {})
        try:
            assert "mytest_" in os.path.basename(result.data["path"])
        finally:
            os.unlink(result.data["path"])

    def test_create_with_directory(self, sys_tempfile: SysTempFilePrimitive) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            result = sys_tempfile.execute({"directory": tmpdir}, {})
            try:
                assert os.path.dirname(result.data["path"]) == os.path.abspath(tmpdir)
            finally:
                os.unlink(result.data["path"])

    def test_suffix_not_string_raises_value_error(self, sys_tempfile: SysTempFilePrimitive) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            sys_tempfile.validate_args({"suffix": 42})

    def test_content_not_string_raises_value_error(self, sys_tempfile: SysTempFilePrimitive) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            sys_tempfile.validate_args({"content": 123})
