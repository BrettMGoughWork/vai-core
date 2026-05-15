from typing import Optional

from src.core.llm.transport import LLMTransport
from src.core.llm.types import CoreLLMResponse
from src.governance.tool_selection import select_tool
from src.execution.engine import execute_tool
from src.core.types.result import CoreResult
from src.core.skills.registry import SkillRegistry
from .config import AgentConfig


class _SkillRegistryAdapter:
    @staticmethod
    def get_spec(name: str):
        try:
            return SkillRegistry.get(name)
        except KeyError:
            return None


class AgentRuntime:
    def __init__(self, transport: LLMTransport, config: AgentConfig):
        self.transport = transport
        self.config = config

    def step(self, prompt: str) -> CoreResult:
        """
        Single-step agent:
        - call LLM
        - maybe call one tool
        - return CoreResult
        """
        llm_resp: CoreLLMResponse = self.transport.call(
            prompt=prompt,
            tools=SkillRegistry.all(),
            model=self.config.model,
        )

        # No tool requested → plain text
        if not llm_resp.tool_name:
            return CoreResult.from_text(llm_resp.text or "")

        # Tool requested → governance + execution
        spec = select_tool(
            tool_name=llm_resp.tool_name,
            allowed_tools=self.config.allowed_tools,
            allowed_categories=self.config.allowed_categories,
            allowed_side_effects=self.config.allowed_side_effects,
            registry=_SkillRegistryAdapter,
        )

        return execute_tool(spec, llm_resp.tool_args or {})

    def run(self, prompt: str) -> CoreResult:
        """
        Multi-step agent:
        - loop up to max_steps
        - feed tool results back into LLM
        - stop on text or error
        """
        context: str = prompt
        last_result: Optional[CoreResult] = None

        for _ in range(self.config.max_steps):
            llm_resp: CoreLLMResponse = self.transport.call(
                prompt=context,
                tools=SkillRegistry.all(),
                model=self.config.model,
            )

            if not llm_resp.tool_name:
                return CoreResult.from_text(llm_resp.text or "")

            spec = select_tool(
                tool_name=llm_resp.tool_name,
                allowed_tools=self.config.allowed_tools,
                allowed_categories=self.config.allowed_categories,
                allowed_side_effects=self.config.allowed_side_effects,
                registry=_SkillRegistryAdapter,
            )

            result = execute_tool(spec, llm_resp.tool_args or {})
            last_result = result

            if result.is_error:
                return result

            # naive: append tool output back into context
            context += f"\n\nTool {result.tool_name} returned: {result.tool_output}"

        # max steps reached
        if last_result is not None:
            return last_result

        return CoreResult.from_error(RuntimeError("Agent reached max_steps without result"))
