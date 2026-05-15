"""
End-to-end test for the core runtime loop.

The LLM is replaced with a stub so no API key is required.
The test verifies that a user request flows through the full stack
(policy → LLM → governance → cache → executor) and returns the
correct result.
"""

import pytest
from unittest.mock import MagicMock

from src.core.loop import CoreLoop
from src.governance.schema import Governance
from src.execution.executor import Executor
from src.skills.registry import SkillRegistry
from src.caching.cache import Cache
from src.tools.schema import ToolSchemaGenerator
from src.tools.validator import ToolValidator
from src.policy.policy import Policy


def _make_stub_llm(tool: str, args: dict):
    """Return a fake LLM that always responds with a fixed action."""
    llm = MagicMock()
    llm.complete.return_value = {"tool": tool, "args": args}
    return llm


def _build_runtime(stub_llm):
    registry = SkillRegistry()
    registry.load()

    schema = ToolSchemaGenerator(registry).generate()
    validator = ToolValidator(schema)

    governance = Governance(validator=validator)
    executor = Executor(registry)
    policy = Policy(
        allowed_tools={"echo", "add"},
        max_args_size=2000,
        max_tool_name=64,
    )
    cache = Cache()

    return CoreLoop(
        llm=stub_llm,
        governance=governance,
        executor=executor,
        policy=policy,
        cache=cache,
        logger=None,
        telemetry=None,
    )


class TestEndToEnd:
    def test_add_returns_correct_sum(self):
        """Full stack: 'add 5 and 7' resolves to 12.0."""
        llm = _make_stub_llm("add", {"a": 5.0, "b": 7.0})
        runtime = _build_runtime(llm)

        result = runtime.run("add 5 and 7")

        assert result["tool"] == "add"
        assert result["result"] == 12.0

    def test_echo_returns_input_text(self):
        """Full stack: echo skill returns the original text."""
        llm = _make_stub_llm("echo", {"text": "hello world"})
        runtime = _build_runtime(llm)

        result = runtime.run("say hello world")

        assert result["tool"] == "echo"
        assert result["result"] == "hello world"

    def test_cache_hit_on_identical_request(self):
        """Same LLM output twice should hit cache on second call."""
        from src.telemetry.telemetry import Telemetry

        llm = _make_stub_llm("add", {"a": 1.0, "b": 2.0})
        registry = SkillRegistry()
        registry.load()

        schema = ToolSchemaGenerator(registry).generate()
        validator = ToolValidator(schema)
        governance = Governance(validator=validator)
        executor = Executor(registry)
        policy = Policy(allowed_tools={"echo", "add"}, max_args_size=2000, max_tool_name=64)
        cache = Cache()
        telemetry = Telemetry()

        runtime = CoreLoop(
            llm=llm,
            governance=governance,
            executor=executor,
            policy=policy,
            cache=cache,
            telemetry=telemetry,
        )

        runtime.run("add 1 and 2")
        runtime.run("add 1 and 2")

        assert telemetry.counters.get("cache_hits", 0) >= 1

    def test_disallowed_tool_raises(self):
        """Policy must reject tools not in the allowlist."""
        llm = _make_stub_llm("delete_everything", {"path": "/"})
        runtime = _build_runtime(llm)

        with pytest.raises(ValueError, match="not permitted by policy"):
            runtime.run("delete everything")
