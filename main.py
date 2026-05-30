from src.agent.dispatcher import AgentDispatcher
from src.core.planning.dispatch.safe_step_dispatcher import SafeStepDispatcher
from src.core.state.runtime import AgentRuntime
from src.execution.minimal_executor import MinimalCoreStepExecutor
from src.core.planning.safety.minimal_policy import MinimalSafetyPolicy
from src.core.config.loader import Config
from src.core.llm.builder import create_llm_transport

def main():
    config = Config()

    # Load full config (not just llm/default)
    llm_config = config.get("llm")

    # Build LLM transport
    llm = create_llm_transport(llm_config)
    
    # build dispatcher chain
    dispatcher = SafeStepDispatcher(
        AgentDispatcher(),
        [MinimalSafetyPolicy()]
    )

    # build executor
    executor = MinimalCoreStepExecutor(llm)

    # build agent runtime with dispatcher and executor
    runtime = AgentRuntime(
        dispatcher=dispatcher,
        executor=executor,
        config=config._config,
    )

    result = runtime.run("Hello, what is your name?")
    print(result)

if __name__ == "__main__":
    main()