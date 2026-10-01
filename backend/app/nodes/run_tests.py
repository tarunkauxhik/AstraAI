from typing import Any

from langgraph.runtime import Runtime

from app.checks import compare_tests
from app.state import AgentState, GraphContext


async def run_tests(
    state: AgentState, runtime: Runtime[GraphContext]
) -> dict[str, Any]:
    """Run the repository's tests again, now against the changed snapshot, and compare
    them with the run before any change."""
    snapshot = runtime.context.snapshots.get(state["run_id"])
    changes, existing = state.get("changes"), state.get("existing_tests")
    if snapshot is None or changes is None or existing is None:
        raise ValueError("run_tests needs the changed snapshot from edit_code")
    verification = await runtime.context.sandbox.run_repository(snapshot)
    return {
        "verification": verification,
        "checks": compare_tests(existing, verification, changes),
    }
