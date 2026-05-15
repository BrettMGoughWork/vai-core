from typing import Optional

from src.core.llm.transport import LLMTransport
from src.core.llm.types import CoreLLMResponse
from src.governance.tool_selection import select_tool
from src.execution.engine import execute_tool
from src.core.types.result import CoreResult
from src.core.skills.registry import SkillRegistry
from .config import AgentConfig


class AgentRuntime:
    def __init__(self, transport: LLMTransport, config: AgentConfig):
        self.transport = transport
        self.config = config

    # ---------------------------------------------------------
    # Single-step agent
    # ---------------------------------------------------------
    def step(self, prompt: str) -> CoreResult:
        # Tightened tool exposure
        tools = SkillRegistry.all_specs_for_agent(self.config)

        llm_resp: CoreLLMResponse = self.transport.call(
            prompt=prompt,
            tools=tools,
            model=self.config.model,
        )

        # LLM returned plain text
        if not llm_resp.tool_name:
            return CoreResult.from_text(llm_resp.text or "")

        # Governance: ensure tool is allowed
        spec = select_tool(
            tool_name=llm_resp.tool_name,
            allowed_tools=self.config.allowed_tools,
            allowed_categories=self.config.allowed_categories,
            allowed_side_effects=self.config.allowed_side_effects,
            registry=SkillRegistry,
        )

        # Execute the tool
        return execute_tool(spec, llm_resp.tool_args or {})

    # ---------------------------------------------------------
    # Multi-step agent
    # ---------------------------------------------------------
    def run(self, prompt: str) -> CoreResult:
        context = prompt
        last_result: Optional[CoreResult] = None

        for _ in range(self.config.max_steps):
            tools = SkillRegistry.all_specs_for_agent(self.config)

            llm_resp: CoreLLMResponse = self.transport.call(
                prompt=context,
                tools=tools,
                model=self.config.model,
            )

            # LLM returned final text
            if not llm_resp.tool_name:
                return CoreResult.from_text(llm_resp.text or "")

            # Governance
            spec = select_tool(
                tool_name=llm_resp.tool_name,
                allowed_tools=self.config.allowed_tools,
                allowed_categories=self.config.allowed_categories,
                allowed_side_effects=self.config.allowed_side_effects,
                registry=SkillRegistry,
            )

            # Execute tool
            result = execute_tool(spec, llm_resp.tool_args or {})
            last_result = result

            if result.is_error:
                return result

            # Feed tool output back into LLM
            context += f"\n\nTool {result.tool_name} returned: {result.tool_output}"

        # Max steps reached
        if last_result is not None:
            return last_result

        return CoreResult.from_error(RuntimeError("Agent reached max_steps without result"))