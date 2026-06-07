"""Unit tests for CoreStep safety substrate integration."""

from unittest.mock import MagicMock, patch

from src.core.state.config import AgentConfig
from src.core.state.core_step_executor import CoreStepExecutor
from src.core.state.step_outcome import StepOutcome
from src.core.state.state import ConversationState
from src.core.llm.types import CoreLLMResponse
from src.core.types.capabilities import SkillCategory, SideEffect
from src.core.types.result import CoreResult
from src.execution.degraded_mode import DegradedModeController
from src.execution.retry.circuit_breaker import CircuitBreaker
from src.execution.self_healing import SelfHealingController


def _make_config() -> AgentConfig:
    return AgentConfig(
        model="test-model",
        allowed_tools=["echo"],
        allowed_categories=[SkillCategory.GENERAL],
        allowed_side_effects=[SideEffect.NONE],
        max_steps=1,
    )


@patch("src.core.state.core_step_executor.SkillRegistry.all_specs_for_agent")
@patch("src.core.state.core_step_executor.call_with_retry")
def test_core_step_executor_records_success_on_text_response(mock_call_with_retry, mock_all_specs_for_agent):
    """Test that executor records success when LLM returns text."""
    mock_all_specs_for_agent.return_value = []
    mock_call_with_retry.return_value = CoreLLMResponse(text="hello")
    
    state = ConversationState(input="start")
    executor = CoreStepExecutor(MagicMock(), _make_config())
    
    result, new_state, outcome = executor.run(state)
    
    assert result.text == "hello"
    assert executor.self_healing.failure_count == 0
    assert executor.degraded_mode.failure_count == 0


@patch("src.core.state.core_step_executor.SkillRegistry.all_specs_for_agent")
@patch("src.core.state.core_step_executor.call_with_retry")
def test_core_step_executor_records_success_on_tool_execution(mock_call_with_retry, mock_all_specs_for_agent):
    """Test that executor records success when tool executes successfully."""
    mock_all_specs_for_agent.return_value = [MagicMock()]
    mock_call_with_retry.return_value = CoreLLMResponse(tool_name="echo", tool_args={"text": "hi"})
    
    state = ConversationState(input="start")
    executor = CoreStepExecutor(MagicMock(), _make_config())
    
    with patch("src.core.state.core_step_executor.select_tool") as mock_select_tool, \
         patch("src.core.state.core_step_executor.execute_with_retry") as mock_execute:
        spec = MagicMock()
        spec.name = "echo"
        mock_select_tool.return_value = spec
        mock_execute.return_value = CoreResult.from_tool("echo", "ok")
        
        result, new_state, outcome = executor.run(state)
        
        assert result.tool_output == "ok"
        assert executor.self_healing.failure_count == 0
        assert executor.degraded_mode.failure_count == 0
        assert executor.circuit_breaker.failures.get("echo", 0) == 0


@patch("src.core.state.core_step_executor.SkillRegistry.all_specs_for_agent")
@patch("src.core.state.core_step_executor.call_with_retry")
def test_core_step_executor_records_failure_on_llm_error(mock_call_with_retry, mock_all_specs_for_agent):
    """Test that executor records failure when LLM call fails."""
    mock_all_specs_for_agent.return_value = []
    mock_call_with_retry.side_effect = Exception("LLM error")
    
    state = ConversationState(input="start")
    executor = CoreStepExecutor(MagicMock(), _make_config())
    
    result, new_state, outcome = executor.run(state)
    
    # Should return SafeFailure
    assert hasattr(result, 'error_type')
    assert executor.self_healing.failure_count == 1
    assert executor.degraded_mode.failure_count == 1


@patch("src.core.state.core_step_executor.SkillRegistry.all_specs_for_agent")
@patch("src.core.state.core_step_executor.call_with_retry")
def test_core_step_executor_records_failure_on_tool_error(mock_call_with_retry, mock_all_specs_for_agent):
    """Test that executor records failure and circuit breaker when tool fails."""
    mock_all_specs_for_agent.return_value = [MagicMock()]
    mock_call_with_retry.return_value = CoreLLMResponse(tool_name="echo", tool_args={"text": "hi"})
    
    state = ConversationState(input="start")
    executor = CoreStepExecutor(MagicMock(), _make_config())
    with patch("src.core.state.core_step_executor.select_tool") as mock_select_tool, \
         patch("src.core.state.core_step_executor.execute_with_retry") as mock_execute:
        spec = MagicMock()
        spec.name = "echo"
        mock_select_tool.return_value = spec
        mock_execute.return_value = CoreResult.from_error(RuntimeError("tool failed"))
        
        result, new_state, outcome = executor.run(state)
        
        assert result.is_error
        assert executor.self_healing.failure_count == 1
        assert executor.degraded_mode.failure_count == 1
        assert executor.circuit_breaker.failures.get("echo", 0) == 1


@patch("src.core.state.core_step_executor.SkillRegistry.all_specs_for_agent")
@patch("src.core.state.core_step_executor.call_with_retry")
def test_core_step_executor_checks_self_healing(mock_call_with_retry, mock_all_specs_for_agent):
    """Test that executor checks self-healing threshold before processing."""
    mock_all_specs_for_agent.return_value = []
    
    state = ConversationState(input="start")
    state.reset = MagicMock()  # Mock the reset method
    executor = CoreStepExecutor(MagicMock(), _make_config())
    executor.self_healing.failure_count = 3  # Trigger self-healing
    
    result, new_state, outcome = executor.run(state)
    
    # Should return SafeFailure from self-heal, not call LLM
    assert hasattr(result, 'error_type')
    mock_call_with_retry.assert_not_called()


@patch("src.core.state.core_step_executor.SkillRegistry.all_specs_for_agent")
@patch("src.core.state.core_step_executor.call_with_retry")
def test_core_step_executor_checks_circuit_breaker(mock_call_with_retry, mock_all_specs_for_agent):
    """Test that executor respects circuit breaker for tools."""
    mock_all_specs_for_agent.return_value = [MagicMock()]
    mock_call_with_retry.return_value = CoreLLMResponse(tool_name="echo", tool_args={"text": "hi"})
    
    state = ConversationState(input="start")
    executor = CoreStepExecutor(MagicMock(), _make_config())
    
    with patch("src.core.state.core_step_executor.select_tool") as mock_select_tool:
        spec = MagicMock()
        spec.name = "echo"
        mock_select_tool.return_value = spec
        
        # Open the circuit breaker
        executor.circuit_breaker.open("echo")
        
        result, new_state, outcome = executor.run(state)
        
        # Should return SafeFailure about circuit breaker
        assert hasattr(result, 'error_type')
        # Should not call execute_with_retry
        assert result.metadata.get("tool") == "echo"


@patch("src.core.state.core_step_executor.SkillRegistry.all_specs_for_agent")
@patch("src.core.state.core_step_executor.call_with_retry")
def test_core_step_executor_accumulates_failures(mock_call_with_retry, mock_all_specs_for_agent):
    """Test that executor accumulates failures correctly."""
    mock_all_specs_for_agent.return_value = [MagicMock()]
    mock_call_with_retry.return_value = CoreLLMResponse(tool_name="echo", tool_args={"text": "hi"})
    
    state = ConversationState(input="start")
    executor = CoreStepExecutor(MagicMock(), _make_config())
    
    with patch("src.core.state.core_step_executor.select_tool") as mock_select_tool, \
         patch("src.core.state.core_step_executor.execute_with_retry") as mock_execute:
        spec = MagicMock()
        spec.name = "echo"
        mock_select_tool.return_value = spec
        mock_execute.return_value = CoreResult.from_error(RuntimeError("boom"))
        
        # Run 3 times to trigger self-healing
        for i in range(3):
            executor.run(state)
        
        assert executor.self_healing.failure_count == 3
        assert executor.self_healing.should_self_heal()


@patch("src.core.state.core_step_executor.SkillRegistry.all_specs_for_agent")
@patch("src.core.state.core_step_executor.call_with_retry")
def test_core_step_executor_with_custom_controllers(mock_call_with_retry, mock_all_specs_for_agent):
    """Test that executor respects custom safety controllers."""
    mock_all_specs_for_agent.return_value = []
    mock_call_with_retry.return_value = CoreLLMResponse(text="hello")
    
    state = ConversationState(input="start")
    custom_healing = SelfHealingController(failure_threshold=2)
    custom_degraded = DegradedModeController(threshold=3)
    custom_breaker = CircuitBreaker(failure_threshold=2, cooldown=1.0)
    
    executor = CoreStepExecutor(
        MagicMock(),
        _make_config(),
        circuit_breaker=custom_breaker,
        degraded_mode=custom_degraded,
        self_healing=custom_healing,
    )
    
    result, new_state, outcome = executor.run(state)
    
    assert executor.self_healing is custom_healing
    assert executor.degraded_mode is custom_degraded
    assert executor.circuit_breaker is custom_breaker


@patch("src.core.state.core_step_executor.classify_step")
@patch("src.core.state.core_step_executor.SkillRegistry.all_specs_for_agent")
@patch("src.core.state.core_step_executor.call_with_retry")
def test_core_step_executor_panic_guard_catches_unexpected_errors(mock_call_with_retry, mock_all_specs_for_agent, mock_classify_step):
    """Test that panic guard catches unexpected exceptions from outside try/except blocks."""
    mock_all_specs_for_agent.return_value = []
    mock_call_with_retry.return_value = CoreLLMResponse(text="hello")
    # Raise an unexpected error when classifying step
    mock_classify_step.side_effect = RuntimeError("unexpected error")
    
    state = ConversationState(input="start")
    executor = CoreStepExecutor(MagicMock(), _make_config())
    
    result, new_state, outcome = executor.run(state)
    
    # Should return SafeFailure with panic metadata
    assert hasattr(result, 'error_type')
    assert result.metadata.get("panic") is True


@patch("src.core.state.core_step_executor.execute_with_retry")
@patch("src.core.state.core_step_executor.SkillRegistry.all_specs_for_agent")
@patch("src.core.state.core_step_executor.call_with_retry")
def test_degraded_mode_active_disables_tool_execution(mock_call_with_retry, mock_all_specs_for_agent, mock_execute_with_retry):
    """When degraded mode is active, tool execution is blocked safely."""
    mock_all_specs_for_agent.return_value = [MagicMock()]
    mock_call_with_retry.return_value = CoreLLMResponse(tool_name="echo", tool_args={"text": "hi"})

    state = ConversationState(input="start")
    degraded = DegradedModeController(threshold=1)
    degraded.record_failure()
    executor = CoreStepExecutor(MagicMock(), _make_config(), degraded_mode=degraded)

    result, new_state, outcome = executor.run(state)

    assert hasattr(result, "error_type")
    assert result.metadata.get("degraded_mode") is True
    assert outcome == StepOutcome.FATAL
    mock_execute_with_retry.assert_not_called()
