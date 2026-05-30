# Stratum 3
# CoreStepExecutor: executes a single step of the core agent loop with safety substrate.

from typing import Tuple, Union

from src.core.state.state import ConversationState
from src.core.llm.types import LLMCallable
from src.core.state.config import AgentConfig
from src.primitives.runtime.registry import SkillRegistry
from src.governance.tool_selection import select_tool
from src.core.types.result import CoreResult
from src.core.state.step_outcome import classify_step, StepOutcome

# Safety substrate imports
from src.execution.panic_guard import with_panic_guard
from src.execution.self_healing import perform_self_heal, SelfHealingController
from src.execution.retry.llm_retry_wrapper import call_with_retry
from src.execution.retry.tool_retry_wrapper import execute_with_retry
from src.execution.safe_failure import make_safe_failure, SafeFailure
from src.execution.retry.circuit_breaker import CircuitBreaker
from src.execution.degraded_mode import DegradedModeController
from src.execution.poison_job_detector import PoisonJobDetector
from src.core.types.errors.ToolError import ToolError

class CoreStepExecutor:
    """
    Executes a single agent step of the core agent loop with safety substrate.
    Handles safety substrate, retries, degraded mode, and failure classification.
    """

    def __init__(
        self,
        llm_client: LLMCallable,
        config: AgentConfig,
        circuit_breaker: CircuitBreaker | None = None,
        degraded_mode: DegradedModeController | None = None,
        self_healing: SelfHealingController | None = None,
        poison_job_detector: PoisonJobDetector | None = None,
    ):
        self.llm_client = llm_client
        self.config = config
        self.circuit_breaker = circuit_breaker or CircuitBreaker(failure_threshold=3, cooldown=5.0)
        self.degraded_mode = degraded_mode or DegradedModeController(threshold=5)
        self.self_healing = self_healing or SelfHealingController(failure_threshold=3)
        self.poison_job_detector = poison_job_detector or PoisonJobDetector(failure_threshold=5)

    def run(self, state: ConversationState) -> Tuple[Union[CoreResult, SafeFailure], ConversationState, StepOutcome]:
        """Run one step of the core agent loop with safety substrate."""
        if self.self_healing.should_self_heal():
            return perform_self_heal(state), state, StepOutcome.FATAL

        job_id = str(state.metadata.get("job_id") or state.input)
        if self.poison_job_detector.is_poison(job_id):
            poison_error = ToolError(
                type="ToolError",
                message="Poison job detected",
                details={"job_id": job_id},
                timestamp="",
                recoverable=False,
            )
            return make_safe_failure(poison_error, {"job_id": job_id, "poison_job": True}), state, StepOutcome.FATAL

        tool = None
        try:
            prompt = state.as_prompt()
            degraded_active = self.degraded_mode.is_active()
            tools = [] if degraded_active else SkillRegistry.all_specs_for_agent(self.config)
            request = {
                "prompt": prompt,
                "tools": tools,
                "model": self.config.model,
            }
            llm_resp = call_with_retry(self.llm_client, request)

            if not llm_resp.tool_name:
                result = CoreResult.from_text(llm_resp.text or "")
                state.append_llm(result.text)
                state.last_result = result
                tool = None
            else:
                if degraded_active:
                    degraded_error = ToolError(
                        type="ToolError",
                        message="Tool execution disabled in degraded mode",
                        details={},
                        timestamp="",
                        recoverable=False,
                    )
                    return make_safe_failure(degraded_error, {"degraded_mode": True}), state, StepOutcome.FATAL
                tool = select_tool(
                    tool_name=llm_resp.tool_name,
                    allowed_tools=self.config.allowed_tools,
                    allowed_categories=self.config.allowed_categories,
                    allowed_side_effects=self.config.allowed_side_effects,
                    registry=SkillRegistry,
                )

                if self.circuit_breaker.is_open(tool.name):
                    circuit_breaker_error = ToolError(
                        type="ToolError",
                        message="Circuit breaker open",
                        details={"tool": tool.name},
                        timestamp="",
                        recoverable=False,
                    )
                    return make_safe_failure(circuit_breaker_error, {"tool": tool.name}), state, StepOutcome.FATAL

                result = execute_with_retry(tool, llm_resp.tool_args or {})
                if not isinstance(result, CoreResult):
                    result = CoreResult.from_tool(tool.name, result)

            state.last_result = result

            if not result.is_error:
                self.self_healing.record_success()
                self.degraded_mode.record_success()
                self.poison_job_detector.record_success(job_id)
                if tool is not None:
                    self.circuit_breaker.record_success(tool.name)
                    state.append_tool(tool.name, result.tool_output)
            else:
                self.self_healing.record_failure()
                self.degraded_mode.record_failure()
                self.poison_job_detector.record_failure(job_id)
                if tool is not None:
                    self.circuit_breaker.record_failure(tool.name)
                    state.append_error(tool.name, result.error)

            outcome = classify_step(result)

            return result, state, outcome
        except Exception as error:
            self.self_healing.record_failure()
            self.degraded_mode.record_failure()
            self.poison_job_detector.record_failure(job_id)
            if tool is not None and isinstance(error, ToolError):
                self.circuit_breaker.record_failure(tool.name)
            metadata = {"panic": True}
            if tool is not None:
                metadata["tool"] = tool.name
            return make_safe_failure(error, metadata), state, StepOutcome.FATAL


@with_panic_guard
def core_step(
    state: ConversationState,
    transport: LLMCallable,
    config: AgentConfig,
) -> Tuple[CoreResult, ConversationState, StepOutcome]:
    """Execute a single step of the core agent loop (backward-compatible function)."""
    executor = CoreStepExecutor(transport, config)
    return executor.run(state)
