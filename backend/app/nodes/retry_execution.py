from app.repair import MAX_EXECUTION_RETRIES
from app.state import AgentState


async def retry_execution(state: AgentState) -> dict[str, int]:
    """Count one more execution attempt after a sandbox infrastructure error.

    Changes no code or tests; the graph runs the same artifacts again next.
    """
    count = state.get("execution_retry_count", 0)
    if count >= MAX_EXECUTION_RETRIES:
        raise ValueError(
            f"no execution retries left ({count} of {MAX_EXECUTION_RETRIES})"
        )
    return {"execution_retry_count": count + 1}
