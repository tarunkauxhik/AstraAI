"""Repair-loop policy: the revision and retry budgets, and where to go after the critic.

Pure and deterministic, so the graph routes with it and the run manager explains a run's
outcome with the same rules.
"""

from typing import Literal

from app.state import AgentState, CriticResult, ExecutionResult

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


# DEVELOP: one repair after the first change. It is tested and reviewed like the first
# change, and then the run ends, whatever that shows.
MAX_DEVELOP_REPAIRS = 1
DevelopDecision = Literal["repair_changes", "finish"]


def new_failures(existing: ExecutionResult | None, after: ExecutionResult) -> bool:
    """Whether the changed repository's tests fail where the original's didn't.

    Tests that already failed before the change say nothing about it. A suite that no longer
    even collects does: it ran before the change.
    """
    if after.status != "failed":
        return False
    if existing is None or existing.status == "passed":
        return True
    if existing.tests_failed is None or after.tests_failed is None:
        return True
    # ponytail: compares counts, so a fixed old failure can hide a new one; compare test
    # ids if that matters.
    return after.tests_failed > existing.tests_failed


def route_develop(
    existing: ExecutionResult | None,
    after: ExecutionResult | None,
    review: CriticResult | None,
    revision_count: int,
) -> DevelopDecision:
    """Repair once if the tests show the change is wrong, or if they pass but the review
    found a real problem to fix. A sandbox or limit problem is no evidence either way, and
    a review never outvotes failing tests: those always get the repair.
    """
    if revision_count >= MAX_DEVELOP_REPAIRS or after is None:
        return "finish"
    if after.status not in ("passed", "failed"):
        return "finish"
    if new_failures(existing, after):
        return "repair_changes"
    action = review.recommended_action if review is not None else None
    return "repair_changes" if action in ("revise_code", "revise_tests") else "finish"


def develop_router(state: AgentState) -> DevelopDecision:
    """The DEVELOP graph's conditional edge after the review."""
    return route_develop(
        state.get("existing_tests"),
        state.get("verification"),
        state.get("critic_result"),
        state.get("revision_count", 0),
    )
