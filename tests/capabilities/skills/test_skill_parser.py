"""
Tests for .skill.md parser (Phase 3.3.1).

Covers: valid front-matter extraction, missing/invalid YAML,
missing required fields, unknown primitive references, and
directory scanning.
"""

from __future__ import annotations

import pytest

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveType, PrimitiveResult
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.skills.skill_parser import parse_skill_file, parse_skill_directory


# ---------------------------------------------------------------------------
# Fake primitive
# ---------------------------------------------------------------------------

class FakePrimitive(PrimitiveBase):
    """Minimal concrete primitive for parser testing."""

    def __init__(
        self,
        *,
        name: str,
        description: str = "",
        primitive_type: PrimitiveType = PrimitiveType.PYTHON,
    ) -> None:
        super().__init__(name=name, description=description, primitive_type=primitive_type)

    def validate_args(self, _args: dict) -> None:
        return

    def execute(self, _args: dict, _context: dict) -> PrimitiveResult:
        return PrimitiveResult(status="success", data=None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry():
    """A registry pre-populated with known primitives."""
    reg = PrimitiveRegistry()
    for name in ("file.read", "file.write", "http.get"):
        reg.register(name, FakePrimitive(name=name, description=f"Mock {name}"))
    return reg


# ---------------------------------------------------------------------------
# parse_skill_file tests
# ---------------------------------------------------------------------------

class TestParseSkillFile:
    """Tests for parse_skill_file."""

    def test_valid_skill_file_parsed(self, tmp_path, registry):
        """A valid .skill.md with correct YAML front-matter succeeds."""
        path = tmp_path / "echo.skill.md"
        path.write_text("""---
name: echo
description: Echoes input text
inputs:
  type: object
  properties:
    text:
      type: string
  required:
    - text
outputs:
  type: object
  properties:
    result:
      type: string
primitives:
  - file.read
steps:
  - call: file.read
    args: { path: "/tmp/echo.txt" }
---
# Echo Skill

This skill reads a file and returns its content.
""")
        result = parse_skill_file(str(path), registry)
        assert result["name"] == "echo"
        assert result["description"] == "Echoes input text"
        assert isinstance(result["inputs"], dict)
        assert isinstance(result["outputs"], dict)
        assert len(result["primitives"]) == 1
        assert isinstance(result["primitives"][0], PrimitiveBase)

    def test_missing_front_matter_raises(self, tmp_path, registry):
        """Missing --- delimiters raises ValueError."""
        path = tmp_path / "bad.skill.md"
        path.write_text("name: echo\n")
        with pytest.raises(ValueError, match="missing opening --- delimiter"):
            parse_skill_file(str(path), registry)

    def test_malformed_yaml_raises(self, tmp_path, registry):
        """Malformed YAML inside front-matter raises ValueError."""
        path = tmp_path / "bad.skill.md"
        path.write_text("""---
: : : invalid yaml
---
""")
        with pytest.raises(ValueError, match="invalid skill manifest"):
            parse_skill_file(str(path), registry)

    def test_missing_required_field_raises(self, tmp_path, registry):
        """Missing 'name' field raises ValueError."""
        path = tmp_path / "bad.skill.md"
        path.write_text("""---
description: No name here
inputs: {}
outputs: {}
primitives: []
---
""")
        with pytest.raises(ValueError, match="missing required key"):
            parse_skill_file(str(path), registry)

    def test_unknown_primitive_raises(self, tmp_path, registry):
        """A primitive not in the registry raises ValueError."""
        path = tmp_path / "bad.skill.md"
        path.write_text("""---
name: ghost
description: Uses unknown primitive
inputs: {}
outputs: {}
primitives:
  - does.not.exist
steps: []
---
""")
        with pytest.raises(ValueError, match="unknown primitive"):
            parse_skill_file(str(path), registry)

    def test_yaml_not_a_dict_raises(self, tmp_path, registry):
        """YAML that parses to a non-dict raises ValueError."""
        path = tmp_path / "bad.skill.md"
        path.write_text("""---
- list item
- another
---
""")
        with pytest.raises(ValueError, match="must be a mapping"):
            parse_skill_file(str(path), registry)

    def test_primitive_names_must_be_strings(self, tmp_path, registry):
        """Primitive list items must be strings."""
        path = tmp_path / "bad.skill.md"
        path.write_text("""---
name: test
description: test
inputs: {}
outputs: {}
primitives:
  - 42
steps: []
---
""")
        with pytest.raises(ValueError, match="must be str"):
            parse_skill_file(str(path), registry)


# ---------------------------------------------------------------------------
# parse_skill_directory tests
# ---------------------------------------------------------------------------

class TestParseSkillDirectory:
    """Tests for parse_skill_directory."""

    def test_parses_all_skill_files(self, tmp_path, registry):
        """Scans a directory and parses valid .skill.md files."""
        (tmp_path / "a.skill.md").write_text("""---
name: alpha
description: First skill
inputs: {}
outputs: {}
primitives: []
steps: []
---
""")
        (tmp_path / "b.skill.md").write_text("""---
name: beta
description: Second skill
inputs: {}
outputs: {}
primitives: []
steps: []
---
""")
        # Non-.skill.md file should be ignored.
        (tmp_path / "readme.txt").write_text("ignore me")

        results = parse_skill_directory(str(tmp_path), registry)
        assert len(results) == 2
        names = {r["name"] for r in results}
        assert names == {"alpha", "beta"}

    def test_skips_invalid_files(self, tmp_path, registry):
        """Invalid .skill.md files are silently skipped."""
        (tmp_path / "bad.skill.md").write_text("no front matter")
        (tmp_path / "good.skill.md").write_text("""---
name: good
description: Valid
inputs: {}
outputs: {}
primitives: []
steps: []
---
""")
        results = parse_skill_directory(str(tmp_path), registry)
        assert len(results) == 1
        assert results[0]["name"] == "good"

    def test_nonexistent_directory_returns_empty(self, registry):
        """A non-existent directory returns an empty list."""
        results = parse_skill_directory("/nonexistent/path/12345", registry)
        assert results == []

    def test_ignores_subdirectories(self, tmp_path, registry):
        """Subdirectories are not recursed into."""
        subdir = tmp_path / "sub"
        subdir.mkdir()
        (subdir / "nested.skill.md").write_text("""---
name: nested
description: In subdirectory
inputs: {}
outputs: {}
primitives: []
steps: []
---
""")
        results = parse_skill_directory(str(tmp_path), registry)
        assert len(results) == 0
