# Stratum 3
# AgentRuntime: minimal agent loop implementation for 2.3.6.
# Uses core_step and isdone from stratum 1.

from typing import Union
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from src.core.state.state import ConversationState
from src.core.state.core_step_executor import core_step
from src.core.state.outcome import StepOutcome
from src.core.state.config import AgentConfig
from src.core.state.isdone import isdone
from src.core.state.trace import StepTrace
from src.core.llm.transport import LLMTransport
from src.core.types.result import CoreResult
from src.execution.safe_failure import SafeFailure


def _result_summary(result: Union[CoreResult, SafeFailure, None]) -> str: # sanity check to ensure we see output even if the agent loop hangs

    if result is None:
        return ""
    if isinstance(result, SafeFailure):
        return f"{result.error_type}: {result.message}"
    if result.is_error:
        return result.error or ""
    if result.is_text:
        return result.text or ""
    if result.is_tool:
        return f"{result.tool_name}: {result.tool_output}"
    return ""


class AgentRuntime:
    """
    Controls the agent loop with step limits, timeouts, and safety substrate.
    """

    def __init__(self, transport: LLMTransport, config: AgentConfig):
        self.transport = transport
        self.config = config

    def step(self, prompt: str) -> CoreResult:
        state = ConversationState(input=prompt)
        result, _, _ = core_step(state, self.transport, self.config)
        return result

    def run(self, prompt: str) -> Union[CoreResult, SafeFailure]:
        state = ConversationState(input=prompt)
        outcome = StepOutcome.NOOP
        result = None
        timeout = self.config.loop_policy.per_step_timeout
        max_wall_time = self.config.loop_policy.max_wall_time
        loop_start = time.monotonic()

        while not isdone(state, outcome, self.config):
            if max_wall_time is not None:
                elapsed = time.monotonic() - loop_start
                if elapsed > max_wall_time:
                    outcome = StepOutcome.FATAL
                    state.last_error = "Loop exceeded max wall time"
                    break

            if timeout is not None:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(core_step, state, self.transport, self.config)
                    try:
                        result, new_state, outcome = future.result(timeout=timeout)
                        if isinstance(new_state, ConversationState):
                            state = new_state
                        state.step_count += 1
                        state.trace.append(
                            StepTrace(
                                step=state.step_count,
                                outcome=outcome,
                                summary=_result_summary(result),
                                error=state.last_error,
                            )
                        )
                        if isinstance(result, SafeFailure):
                            return result
                    except TimeoutError:
                        outcome = StepOutcome.FATAL
                        state.last_error = "Step timed out"
                        break
            else:
                result, new_state, outcome = core_step(state, self.transport, self.config)
                if isinstance(new_state, ConversationState):
                    state = new_state
                state.step_count += 1
                state.trace.append(
                    StepTrace(
                        step=state.step_count,
                        outcome=outcome,
                        summary=_result_summary(result),
                        error=state.last_error,
                    )
                )
                if isinstance(result, SafeFailure):
                    return result

        if isinstance(result, SafeFailure):
            return result
        if state.last_error and (result is None or not result.is_error):
            return CoreResult.from_error(RuntimeError(state.last_error))

        return result or CoreResult.from_error(
            RuntimeError("Agent reached max_steps without result")
        )
