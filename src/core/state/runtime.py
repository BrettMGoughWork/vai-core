from __future__ import annotations

from typing import Protocol, Union, Tuple
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from src.core.state.state import ConversationState
from src.core.state.core_step_executor import core_step
from src.core.state.step_outcome import StepOutcome
from src.core.state.config import AgentConfig
from src.core.state.isdone import isdone
from src.core.state.trace import StepTrace
from src.core.types.result import CoreResult
from src.execution.safe_failure import SafeFailure

# IMPORTANT: CoreConfig + AgentConfig
from src.core.state.config import CoreConfig, AgentConfig

class StepExecutor(Protocol):
    def execute(
        self,
        step: object,
        state: ConversationState,
        agent_config: AgentConfig,
    ) -> Tuple[Union[CoreResult, SafeFailure, None], ConversationState, StepOutcome]:
        ...


def _result_summary(result: Union[CoreResult, SafeFailure, None]) -> str:
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
    Uses a dispatcher to choose the next step and an executor to run it.
    """

    def __init__(
        self,
        dispatcher: StepDispatcher,
        executor: StepExecutor,
        config: CoreConfig, # <-- MUST be CoreConfig
    ) -> None:
        self.dispatcher = dispatcher
        self.executor = executor
        self.config = config

    def step(self, prompt: str) -> CoreResult:
        state = ConversationState(input=prompt)
        step = self.dispatcher.dispatch(state)

        # executor receives ONLY the agent config
        result, _, _ = self.executor.execute(step, state, self.config.agent)

        if isinstance(result, SafeFailure):
            return CoreResult.from_error(RuntimeError(result.message))

        return result or CoreResult.from_error(RuntimeError("No result from single step"))

    def run(self, prompt: str) -> Union[CoreResult, SafeFailure]:
        state = ConversationState(input=prompt)
        outcome = StepOutcome.NOOP
        result: Union[CoreResult, SafeFailure, None] = None

        agent_cfg = self.config.agent
        loop_policy = agent_cfg.loop_policy

        timeout = loop_policy.per_step_timeout
        max_wall_time = loop_policy.max_wall_time
        loop_start = time.monotonic()

        while not isdone(state, outcome, agent_cfg):
            if max_wall_time is not None:
                elapsed = time.monotonic() - loop_start
                if elapsed > max_wall_time:
                    outcome = StepOutcome.FATAL
                    state.last_error = "Loop exceeded max wall time"
                    break

            step = self.dispatcher.dispatch(state)

            if timeout is not None:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        self.executor.execute,
                        step,
                        state,
                        agent_cfg,
                    )
                    try:
                        result, new_state, outcome = future.result(timeout=timeout)
                    except TimeoutError:
                        outcome = StepOutcome.FATAL
                        state.last_error = "Step timed out"
                        break
            else:
                result, new_state, outcome = self.executor.execute(
                    step,
                    state,
                    agent_cfg,
                )

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