from src.core.agent.runtime import AgentRuntime
from src.core.agent.config import AgentConfig
from src.core.llm.transport import LLMTransport
from src.core.types.result import CoreResult
from src.skills.categories import SkillCategory
from src.skills.side_effects import SideEffect

# import the dev skill so it registers itself
from src.skills._dev.test_math import test_math_add

# Fake LLM that always calls the tool
class FakeLLM:
    @staticmethod
    def chat(model, messages, tools, temperature):
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "test_math_add",
                                    "arguments": '{"a": 1, "b": 2}',
                                }
                            }
                        ],
                        "content": None,
                    }
                }
            ]
        }


def test_agent_loop_end_to_end():
    # 1. Setup transport with fake LLM
    transport = LLMTransport(FakeLLM())

    # 2. Agent config
    config = AgentConfig(
        model="fake-model",
        allowed_tools=["test_math_add"],
        allowed_categories=[SkillCategory.MATH],
        allowed_side_effects=[SideEffect.NONE],
        max_steps=1,
    )

    # 3. Agent runtime
    agent = AgentRuntime(transport, config)

    # 4. Run the agent
    result: CoreResult = agent.run("add 1 and 2")

    # 5. Assertions
    assert result.is_tool
    assert result.tool_name == "test_math_add"
    assert result.tool_output == 3