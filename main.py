from src.agent.dispatcher import AgentDispatcher
from src.core.planning.dispatch.safe_step_dispatcher import SafeStepDispatcher
from src.execution.minimal_executor import MinimalCoreStepExecutor
from src.agent.loop import AgentLoop
from src.core.planning.safety.minimal_policy import MinimalSafetyPolicy

def main():
    print("Starting agent loop...")
    dispatcher = AgentDispatcher()
    safety_policies = [
        MinimalSafetyPolicy(),
    ]
    safe_dispatcher = SafeStepDispatcher(dispatcher, safety_policies)
    executor = MinimalCoreStepExecutor()

    loop = AgentLoop(
        dispatcher=safe_dispatcher,
        engine=executor,
    )

if __name__ == "__main__":
    main()