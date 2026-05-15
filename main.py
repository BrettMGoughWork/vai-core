from src.core.loop import CoreLoop
from src.governance.schema import Governance
from src.execution.executor import Executor
from src.skills.registry import SkillRegistry
from src.caching.cache import Cache
from src.transport.llm import DeepSeekLLM
from src.observability.logger import StructuredLogger
from src.telemetry.telemetry import Telemetry
from src.policy.policy import Policy
from src.core.config.loader import Config
from src.tools.schema import ToolSchemaGenerator
from src.tools.prompt_builder import ToolPromptBuilder
from src.tools.validator import ToolValidator

def create_runtime():
    config = Config()

    registry = SkillRegistry()
    registry.load()

    # Generate tool schema
    schema = ToolSchemaGenerator(registry).generate()
    
    # Build Prompt
    schema_prompt = ToolPromptBuilder.build_schema_prompt(schema)

    # Create validator
    validator = ToolValidator(schema)
    
    llm = DeepSeekLLM(
        model=config.get("llm", "model"),
        schema_prompt=schema_prompt
    )

    governance = Governance(validator=validator)
    executor = Executor(registry)
    policy = Policy(
        allowed_tools=set(config.get("policy", "allowed_tools")),
        max_args_size=config.get("policy", "max_args_size"),
        max_tool_name=config.get("policy", "max_tool_name"),
    )
    cache = Cache()
    logger = StructuredLogger() if config.get("logging", "enabled") else None
    telemetry = Telemetry() if config.get("telemetry", "enabled") else None

    return CoreLoop(
        llm, 
        governance, 
        executor, 
        policy=policy, 
        cache=cache, 
        logger=logger, 
        telemetry=telemetry
    )

if __name__ == "__main__":
    runtime = create_runtime()
    print(runtime.run("add 1 and 2"))
    if runtime.telemetry:
        print("\nTelemetry snapshot:")
        print(runtime.telemetry.snapshot())