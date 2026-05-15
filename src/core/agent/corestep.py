from typing import Tuple

from src.core.agent.state import ConversationState
from src.core.llm.transport import LLMTransport
from src.core.agent.config import AgentConfig
from src.core.skills.registry import SkillRegistry
from src.governance.tool_selection import select_tool
from src.execution.engine import execute_tool
from src.core.types.result import CoreResult
from src.core.agent.outcome import classify_step, StepOutcome

def core_step(
    state: ConversationState,
    transport: LLMTransport,
    config: AgentConfig,
) -> Tuple[CoreResult, ConversationState, StepOutcome]:

    # 1. Build prompt from state
    prompt = state.as_prompt()

    # 2. Filter tools for this agent
    tools = SkillRegistry.all_specs_for_agent(config)

    # 3. LLM call
    llm_resp = transport.call(
        prompt=prompt,
        tools=tools,
        model=config.model,
    )

    # 4. No tool → final text
    if not llm_resp.tool_name:
        result = CoreResult.from_text(llm_resp.text or "")
        state.append_llm(result.text)
        state.last_result = result
        return result, state, classify_step(result)

    # 5. Governance
    spec = select_tool(
        tool_name=llm_resp.tool_name,
        allowed_tools=config.allowed_tools,
        allowed_categories=config.allowed_categories,
        allowed_side_effects=config.allowed_side_effects,
        registry=SkillRegistry,
    )

    # 6. Execute tool
    result = execute_tool(spec, llm_resp.tool_args or {})

    state.last_result = result

    if result.is_error:
        state.append_error(spec.name, result.error)
    else:
        state.append_tool(spec.name, result.tool_output)

    outcome = classify_step(result)

    return result, state, outcome
