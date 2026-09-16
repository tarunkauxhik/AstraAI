from langgraph.runtime import Runtime

from app.state import AgentState, ExecutionResult, GraphContext


async def execute_sandbox(
    state: AgentState, runtime: Runtime[GraphContext]
) -> dict[str, ExecutionResult]:
    """Run the generated tests in the sandbox. Knows nothing about Docker itself."""
    generated_code = state.get("generated_code")
    if generated_code is None:
        raise ValueError("execute_sandbox needs generated_code from generate_code")
    if generated_code.language != state["language"]:
        raise ValueError(
            f"generated code is {generated_code.language}, "
            f"but the run is {state['language']}"
        )
    execution_result = await runtime.context.sandbox.execute(generated_code)
    return {"execution_result": execution_result}
