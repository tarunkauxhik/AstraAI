"""Repair-loop policy: the revision and retry budgets, and where to go after the critic.

Pure and deterministic, so the graph routes with it and the run manager explains a run's
outcome with the same rules.
"""

from typing import Literal

from app.state import AgentState, CriticResult

# Code or test revisions per run. Each costs an LLM call, an execution and a critic call.
MAX_REVISIONS = 2
# Re-executions after a sandbox infrastructure error. Not revisions: nothing is rewritten.
MAX_EXECUTION_RETRIES = 1

RepairDecision = Literal[
    "accept",
    "needs_human_review",
    "revise_code",
    "revise_tests",
    "retry_execution",
    "revision_budget_exhausted",
    "retry_budget_exhausted",
]
TERMINAL_DECISIONS: frozenset[str] = frozenset(
    {
        "accept",
        "needs_human_review",
        "revision_budget_exhausted",
        "retry_budget_exhausted",
    }
)


def route_repair(
    critic_result: CriticResult | None, revision_count: int, execution_retry_count: int
) -> RepairDecision:
    """Decide the next step from the reconciled critic action and the remaining budgets.

    Routes on recommended_action, never on verdict alone.
    """
    action = critic_result.recommended_action if critic_result is not None else None
    if action == "accept":
        return "accept"
    if action == "revise_code":
        return (
            "revise_code"
            if revision_count < MAX_REVISIONS
            else "revision_budget_exhausted"
        )
    if action == "revise_tests":
        return (
            "revise_tests"
            if revision_count < MAX_REVISIONS
            else "revision_budget_exhausted"
        )
    if action == "retry_execution":
        if execution_retry_count < MAX_EXECUTION_RETRIES:
            return "retry_execution"
        return "retry_budget_exhausted"
    # needs_human_review, a missing verdict, or anything unexpected: stop safely.
    return "needs_human_review"


def repair_router(state: AgentState) -> RepairDecision:
    """The graph's conditional edge after the critic."""
    return route_repair(
        state.get("critic_result"),
        state.get("revision_count", 0),
        state.get("execution_retry_count", 0),
    )
