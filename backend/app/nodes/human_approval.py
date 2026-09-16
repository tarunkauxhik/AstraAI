from langgraph.types import interrupt
from pydantic import ValidationError

from app.state import AgentState, ApprovalDecision, ApprovalRequest, ApprovalStatus

APPROVAL_MEANS = (
    "Approving accepts this verified solution as the run's result. Nothing else happens: "
    "no code is published, deployed or sent anywhere."
)
REQUIRED_STATE = ("requirements", "execution_result", "critic_result")


def approval_request(state: AgentState) -> ApprovalRequest:
    """The compact, JSON-safe summary a human decides on. Pure: reads state only."""
    execution, critic = state["execution_result"], state["critic_result"]
    return ApprovalRequest(
        run_id=state["run_id"],
        task=state["task"],
        language=state["language"],
        problem_summary=state["requirements"].problem_summary,
        execution_status=execution.status,
        tests_passed=execution.tests_passed,
        tests_failed=execution.tests_failed,
        critic_reason=critic.reason,
        revision_count=state.get("revision_count", 0),
        execution_retry_count=state.get("execution_retry_count", 0),
        approval_means=APPROVAL_MEANS,
    )


def parse_decision(answer: object) -> ApprovalDecision | None:
    try:
        return ApprovalDecision.model_validate(answer)
    except ValidationError:
        return None


async def human_approval(state: AgentState) -> dict[str, ApprovalStatus]:
    """Pause until a human approves or rejects an agent-verified solution.

    LangGraph re-runs this node from the top when it resumes, so it has no side effects:
    it only reads state, interrupts, and returns the decision.
    """
    missing = [key for key in REQUIRED_STATE if state.get(key) is None]
    if missing:
        raise ValueError(
            f"human_approval needs {', '.join(missing)} from earlier nodes"
        )
    if state["critic_result"].recommended_action != "accept":
        raise ValueError("human approval is only for solutions the critic accepted")

    payload = approval_request(state).model_dump(mode="json")
    answer = interrupt(payload)
    while (decision := parse_decision(answer)) is None:
        # An invalid answer is never a decision, not even a rejection: ask again.
        answer = interrupt(payload)
    return {
        "approval_status": "approved" if decision.decision == "approve" else "rejected"
    }
