from src.core.agent.outcome import StepOutcome, classify_step
from src.core.types.result import CoreResult


def test_classify_step_fatal_for_errors():
    result = CoreResult.from_error(RuntimeError("boom"))
    assert classify_step(result) == StepOutcome.FATAL


def test_classify_step_success_for_text():
    result = CoreResult.from_text("done")
    assert classify_step(result) == StepOutcome.SUCCESS


def test_classify_step_recoverable_for_tool_output():
    result = CoreResult.from_tool("echo", "ok")
    assert classify_step(result) == StepOutcome.RECOVERABLE


def test_classify_step_noop_for_tool_without_output():
    result = CoreResult.from_tool("echo", None)
    assert classify_step(result) == StepOutcome.NOOP
