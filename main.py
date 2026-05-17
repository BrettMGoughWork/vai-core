#!/usr/bin/env python3

import json
from pathlib import Path
import sys
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


def _extract_plan_from_record(record: dict):
    payload = record.get("payload")
    if isinstance(payload, dict):
        plan = payload.get("plan")
        if isinstance(plan, dict):
            return plan
        if {"intent", "targetskillid", "arguments"}.issubset(payload.keys()):
            return payload

    plan = record.get("last_plan")
    if isinstance(plan, dict):
        return plan

    if {"intent", "targetskillid", "arguments"}.issubset(record.keys()):
        return record
    return None


def _load_latest_plan_from_logs(logs_dir: Path):
    if not logs_dir.exists() or not logs_dir.is_dir():
        return None

    files = sorted(
        [path for path in logs_dir.rglob("*") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        except OSError:
            continue

        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                plan = _extract_plan_from_record(record)
                if plan is not None:
                    return plan
    return None


def main() -> None:
    if sys.argv[1:] == ["agent", "plan"]:
        logs_dir = Path(__file__).resolve().parent / "logs"
        plan = _load_latest_plan_from_logs(logs_dir)
        if plan is None:
            print("No plan found in logs.")
        else:
            print(json.dumps(plan, indent=2, ensure_ascii=False))
        return

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
