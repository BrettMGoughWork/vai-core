#!/usr/bin/env python3

from pathlib import Path
from typing import Dict

from src.core.agent.config import AgentConfig
from src.core.agent.runtime import AgentRuntime
from src.core.llm.providers.deepseek_client import DeepSeekClient
from src.core.llm.transport import LLMTransport
from src.core.skills.categories import SkillCategory
from src.core.skills.registry import SkillRegistry
from src.core.skills.side_effects import SideEffect


def _load_llm_alias_map(path: Path) -> tuple[str, Dict[str, str]]:
    default_alias = "deepseek-chat"
    alias_to_model: Dict[str, str] = {}

    current_alias = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if line.startswith("default:"):
            default_alias = line.split(":", 1)[1].strip().strip('"')
            continue

        if line.startswith("  ") and stripped.endswith(":"):
            current_alias = stripped[:-1]
            continue

        if current_alias and stripped.startswith("model:"):
            model_name = stripped.split(":", 1)[1].strip().strip('"')
            alias_to_model[current_alias] = model_name

    return default_alias, alias_to_model


def _create_agent_config(model_alias: str) -> AgentConfig:
    allowed_tools = [spec.name for spec in SkillRegistry.all_specs()]
    return AgentConfig(
        model=model_alias,
        allowed_tools=allowed_tools,
        allowed_categories=list(SkillCategory),
        allowed_side_effects=list(SideEffect),
        max_steps=4,
    )


def _display_result(result) -> str:
    if result.error:
        return f"ERROR: {result.error}"
    if result.tool_name:
        return f"{result.tool_name}: {result.tool_output}"
    return result.text or ""


def main() -> None:
    llms_path = Path(__file__).resolve().parent / "config" / "llms.yaml"
    default_alias, alias_to_model = _load_llm_alias_map(llms_path)
    model_name = alias_to_model.get(default_alias, default_alias)

    client = DeepSeekClient()
    transport = LLMTransport(client)
    config = _create_agent_config(model_alias=model_name)
    runtime = AgentRuntime(transport, config)

    print("VAI Runtime - stdin mode")
    print("Type 'exit' or Ctrl-D to quit.\n")

    while True:
        try:
            prompt = input("> ").strip()
        except EOFError:
            print("\nExiting.")
            break

        if prompt.lower() in ("exit", "quit"):
            print("Goodbye.")
            break

        if not prompt:
            continue

        result = runtime.run(prompt)
        print(f"\n{_display_result(result)}\n")


if __name__ == "__main__":
    main()
