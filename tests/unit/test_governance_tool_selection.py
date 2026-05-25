import pytest
from unittest.mock import MagicMock

from src.governance.tool_selection import select_tool
from src.governance.errors import GovernanceError
from src.primitives.runtime.toolspec import ToolSpec
from src.primitives.runtime.categories import SkillCategory
from src.primitives.runtime.side_effects import SideEffect


def _make_spec(name, category=SkillCategory.GENERAL, side_effects=SideEffect.NONE, enabled=True):
    """Helper to create a ToolSpec."""
    return ToolSpec(
        name=name,
        description=f"Test skill: {name}",
        schema={"type": "object", "properties": {}},
        handler=lambda: None,
        category=category,
        side_effects=side_effects,
        enabled=enabled,
    )


def test_select_tool_succeeds_when_all_constraints_met():
    """Tool selection succeeds when tool exists, is allowed, and meets all constraints."""
    spec = _make_spec("echo", SkillCategory.GENERAL, SideEffect.NONE)
    
    mock_registry = MagicMock()
    mock_registry.get_spec.return_value = spec

    result = select_tool(
        tool_name="echo",
        allowed_tools=["echo", "add"],
        allowed_categories=[SkillCategory.GENERAL, SkillCategory.MATH],
        allowed_side_effects=[SideEffect.NONE, SideEffect.READ],
        registry=mock_registry,
    )

    assert result.name == "echo"
    mock_registry.get_spec.assert_called_once_with("echo")


def test_select_tool_raises_when_tool_does_not_exist():
    """Raises GovernanceError when tool is not in registry."""
    mock_registry = MagicMock()
    mock_registry.get_spec.return_value = None

    with pytest.raises(GovernanceError, match="does not exist"):
        select_tool(
            tool_name="nonexistent",
            allowed_tools=["echo"],
            allowed_categories=[SkillCategory.GENERAL],
            allowed_side_effects=[SideEffect.NONE],
            registry=mock_registry,
        )


def test_select_tool_raises_when_tool_not_in_allowlist():
    """Raises GovernanceError when tool is not in the allowed list."""
    spec = _make_spec("delete", SkillCategory.DANGEROUS, SideEffect.WRITE)
    
    mock_registry = MagicMock()
    mock_registry.get_spec.return_value = spec

    with pytest.raises(GovernanceError, match="is not allowed"):
        select_tool(
            tool_name="delete",
            allowed_tools=["echo", "add"],  # delete not in allowlist
            allowed_categories=[SkillCategory.GENERAL, SkillCategory.MATH],
            allowed_side_effects=[SideEffect.NONE],
            registry=mock_registry,
        )


def test_select_tool_raises_when_category_not_allowed():
    """Raises GovernanceError when tool category is not in allowed categories."""
    spec = _make_spec("rm", SkillCategory.DANGEROUS, SideEffect.WRITE)
    
    mock_registry = MagicMock()
    mock_registry.get_spec.return_value = spec

    with pytest.raises(GovernanceError, match="category.*not permitted"):
        select_tool(
            tool_name="rm",
            allowed_tools=["rm"],  # allowed in list
            allowed_categories=[SkillCategory.GENERAL, SkillCategory.MATH],  # DANGEROUS not allowed
            allowed_side_effects=[SideEffect.WRITE],
            registry=mock_registry,
        )


def test_select_tool_raises_when_side_effects_not_allowed():
    """Raises GovernanceError when tool side-effects are not permitted."""
    spec = _make_spec("delete", SkillCategory.GENERAL, SideEffect.WRITE)
    
    mock_registry = MagicMock()
    mock_registry.get_spec.return_value = spec

    with pytest.raises(GovernanceError, match="side-effects.*not permitted"):
        select_tool(
            tool_name="delete",
            allowed_tools=["delete"],
            allowed_categories=[SkillCategory.GENERAL],
            allowed_side_effects=[SideEffect.NONE, SideEffect.READ],  # WRITE not allowed
            registry=mock_registry,
        )


def test_select_tool_raises_when_tool_disabled():
    """Raises GovernanceError when tool is disabled."""
    spec = _make_spec("broken", SkillCategory.GENERAL, SideEffect.NONE, enabled=False)
    
    mock_registry = MagicMock()
    mock_registry.get_spec.return_value = spec

    with pytest.raises(GovernanceError, match="is disabled"):
        select_tool(
            tool_name="broken",
            allowed_tools=["broken"],
            allowed_categories=[SkillCategory.GENERAL],
            allowed_side_effects=[SideEffect.NONE],
            registry=mock_registry,
        )


def test_select_tool_validates_in_order():
    """Validations happen in the correct order: existence, allowlist, category, side-effects, enabled."""
    spec = _make_spec("test", SkillCategory.GENERAL, SideEffect.NONE)
    mock_registry = MagicMock()
    mock_registry.get_spec.return_value = spec

    # If tool doesn't exist, should fail early (before checking allowlist)
    mock_registry.get_spec.return_value = None
    with pytest.raises(GovernanceError, match="does not exist"):
        select_tool(
            tool_name="missing",
            allowed_tools=[],  # empty allowlist
            allowed_categories=[],
            allowed_side_effects=[],
            registry=mock_registry,
        )


def test_select_tool_accepts_multiple_allowed_categories():
    """Tool selection succeeds when tool category is one of several allowed."""
    spec = _make_spec("math_add", SkillCategory.MATH, SideEffect.NONE)
    
    mock_registry = MagicMock()
    mock_registry.get_spec.return_value = spec

    result = select_tool(
        tool_name="math_add",
        allowed_tools=["math_add"],
        allowed_categories=[SkillCategory.GENERAL, SkillCategory.MATH, SkillCategory.TEXT],
        allowed_side_effects=[SideEffect.NONE],
        registry=mock_registry,
    )

    assert result.name == "math_add"
    assert result.category == SkillCategory.MATH


def test_select_tool_accepts_multiple_allowed_side_effects():
    """Tool selection succeeds when tool side-effects are one of several allowed."""
    spec = _make_spec("read_file", SkillCategory.GENERAL, SideEffect.READ)
    
    mock_registry = MagicMock()
    mock_registry.get_spec.return_value = spec

    result = select_tool(
        tool_name="read_file",
        allowed_tools=["read_file"],
        allowed_categories=[SkillCategory.GENERAL],
        allowed_side_effects=[SideEffect.NONE, SideEffect.READ, SideEffect.WRITE],
        registry=mock_registry,
    )

    assert result.name == "read_file"
    assert result.side_effects == SideEffect.READ
