"""
Contract tests for src/tools — ToolValidator, ToolSchemaGenerator, ToolPromptBuilder.

These are the tool-layer adapters that sit between LLM output and skill execution.
Tests validate schema generation, prompt construction, and action validation contracts.
"""
import pytest

from src.tools.schema import ToolSchemaGenerator
from src.tools.prompt_builder import ToolPromptBuilder
from src.tools.validator import ToolValidator


# ── Fakes ─────────────────────────────────────────────────────────────────────

class FakeRegistry:
    """Minimal fake of the skill registry — exposes only _skills dict."""
    def __init__(self, skills):
        self._skills = skills


def _make_func(name, doc, **params):
    """Build a minimal callable with the right signature for schema generation."""
    annotations = {p: t for p, t in params.items()}
    annotations["return"] = str

    def func(**kwargs):
        return name

    func.__name__ = name
    func.__doc__ = doc
    func.__annotations__ = annotations
    import inspect
    func.__signature__ = inspect.Signature(
        [inspect.Parameter(p, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=t) for p, t in params.items()]
    )
    return func


# ── ToolSchemaGenerator ───────────────────────────────────────────────────────

class TestToolSchemaGenerator:
    def test_generates_string_arg_type(self):
        func = _make_func("echo", "Echo text", text=str)
        registry = FakeRegistry({"echo": func})
        gen = ToolSchemaGenerator(registry)

        schema = gen.generate()

        assert schema["echo"]["args"]["text"]["type"] == "string"

    def test_generates_number_type_for_int(self):
        func = _make_func("count", "Count", n=int)
        registry = FakeRegistry({"count": func})

        schema = ToolSchemaGenerator(registry).generate()

        assert schema["count"]["args"]["n"]["type"] == "number"

    def test_generates_number_type_for_float(self):
        func = _make_func("scale", "Scale", factor=float)
        registry = FakeRegistry({"scale": func})

        schema = ToolSchemaGenerator(registry).generate()

        assert schema["scale"]["args"]["factor"]["type"] == "number"

    def test_uses_docstring_as_description(self):
        func = _make_func("tool", "This is the description")
        registry = FakeRegistry({"tool": func})

        schema = ToolSchemaGenerator(registry).generate()

        assert schema["tool"]["description"] == "This is the description"

    def test_no_params_produces_empty_args(self):
        func = _make_func("noop", "Do nothing")
        registry = FakeRegistry({"noop": func})

        schema = ToolSchemaGenerator(registry).generate()

        assert schema["noop"]["args"] == {}

    def test_multiple_tools_all_appear_in_schema(self):
        registry = FakeRegistry({
            "a": _make_func("a", "Tool A"),
            "b": _make_func("b", "Tool B"),
        })

        schema = ToolSchemaGenerator(registry).generate()

        assert set(schema.keys()) == {"a", "b"}

    def test_unknown_type_annotated_as_any(self):
        func = _make_func("thing", "A thing", x=list)
        registry = FakeRegistry({"thing": func})

        schema = ToolSchemaGenerator(registry).generate()

        assert schema["thing"]["args"]["x"]["type"] == "any"


# ── ToolPromptBuilder ─────────────────────────────────────────────────────────

class TestToolPromptBuilder:
    _SCHEMA = {
        "echo": {"description": "Echo text back", "args": {"text": {"type": "string"}}},
        "add": {"description": "Add two numbers", "args": {"a": {"type": "number"}, "b": {"type": "number"}}},
    }

    def test_prompt_contains_tool_names(self):
        prompt = ToolPromptBuilder.build_schema_prompt(self._SCHEMA)
        assert "echo" in prompt
        assert "add" in prompt

    def test_prompt_contains_tool_descriptions(self):
        prompt = ToolPromptBuilder.build_schema_prompt(self._SCHEMA)
        assert "Echo text back" in prompt
        assert "Add two numbers" in prompt

    def test_prompt_contains_arg_names(self):
        prompt = ToolPromptBuilder.build_schema_prompt(self._SCHEMA)
        assert "text" in prompt
        assert " a" in prompt or "\na" in prompt

    def test_prompt_contains_arg_types(self):
        prompt = ToolPromptBuilder.build_schema_prompt(self._SCHEMA)
        assert "string" in prompt
        assert "number" in prompt

    def test_prompt_forbids_plain_text(self):
        prompt = ToolPromptBuilder.build_schema_prompt(self._SCHEMA)
        assert "plain text" in prompt.lower() or "never return plain text" in prompt.lower()

    def test_prompt_instructs_json_only(self):
        prompt = ToolPromptBuilder.build_schema_prompt(self._SCHEMA)
        assert "JSON" in prompt

    def test_empty_schema_produces_valid_prompt(self):
        prompt = ToolPromptBuilder.build_schema_prompt({})
        # Should not raise and should contain the header structure
        assert "tool" in prompt.lower()

    def test_prompt_is_a_string(self):
        assert isinstance(ToolPromptBuilder.build_schema_prompt(self._SCHEMA), str)


# ── ToolValidator ─────────────────────────────────────────────────────────────

class TestToolValidator:
    _SCHEMA = {
        "echo": {
            "description": "Echo",
            "args": {"text": {"type": "string"}},
        },
        "add": {
            "description": "Add",
            "args": {"a": {"type": "number"}, "b": {"type": "number"}},
        },
    }

    @pytest.fixture
    def validator(self):
        return ToolValidator(self._SCHEMA)

    def test_valid_string_action_passes(self, validator):
        validator.validate({"tool": "echo", "args": {"text": "hello"}})

    def test_valid_number_action_passes(self, validator):
        validator.validate({"tool": "add", "args": {"a": 1, "b": 2.5}})

    def test_unknown_tool_raises_value_error(self, validator):
        with pytest.raises(ValueError, match="Unknown tool"):
            validator.validate({"tool": "nonexistent", "args": {}})

    def test_missing_required_arg_raises_value_error(self, validator):
        with pytest.raises(ValueError, match="Missing required arg"):
            validator.validate({"tool": "echo", "args": {}})

    def test_unknown_arg_raises_value_error(self, validator):
        with pytest.raises(ValueError, match="Unknown arg"):
            validator.validate({"tool": "echo", "args": {"text": "hi", "extra": "oops"}})

    def test_wrong_type_string_raises_value_error(self, validator):
        with pytest.raises(ValueError, match="must be a string"):
            validator.validate({"tool": "echo", "args": {"text": 123}})

    def test_wrong_type_number_raises_value_error(self, validator):
        with pytest.raises(ValueError, match="must be a number"):
            validator.validate({"tool": "add", "args": {"a": "one", "b": 2}})

    def test_integer_is_accepted_as_number(self, validator):
        # int is a valid number type
        validator.validate({"tool": "add", "args": {"a": 1, "b": 2}})

    def test_missing_tool_key_raises_value_error(self, validator):
        with pytest.raises(ValueError, match="Unknown tool"):
            validator.validate({"args": {"text": "hi"}})
