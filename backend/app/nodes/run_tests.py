from langgraph.runtime import Runtime

from app.state import AgentState, ExecutionResult, GraphContext


async def run_tests(
    state: AgentState, runtime: Runtime[GraphContext]
) -> dict[str, ExecutionResult]:
    """Run the repository's tests again, now against the changed snapshot."""
    snapshot = runtime.context.snapshots.get(state["run_id"])
    if snapshot is None or state.get("changes") is None:
        raise ValueError("run_tests needs the changed snapshot from edit_code")
    return {"verification": await runtime.context.sandbox.run_repository(snapshot)}
