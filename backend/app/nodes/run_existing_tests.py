from langgraph.runtime import Runtime

from app.state import AgentState, ExecutionResult, GraphContext


async def run_existing_tests(
    state: AgentState, runtime: Runtime[GraphContext]
) -> dict[str, ExecutionResult]:
    """Run the repository's own tests, exactly as they are, in the sandbox."""
    snapshot = runtime.context.snapshots.get(state["run_id"])
    if snapshot is None:
        raise ValueError(
            "run_existing_tests needs the snapshot from prepare_repository"
        )
    return {"existing_tests": await runtime.context.sandbox.run_repository(snapshot)}
