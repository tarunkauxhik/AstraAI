import asyncio

import pytest

from app.nodes.retry_execution import retry_execution
from app.repair import (
    MAX_EXECUTION_RETRIES,
    MAX_REVISIONS,
    TERMINAL_DECISIONS,
    repair_router,
    route_repair,
)
from app.state import CriticResult
from tests.fake_llm import (
    CODE_FAILURE_VERDICT,
    TEST_FAILURE_VERDICT,
    VALID_CRITIC_RESULT,
)


def verdict_for(action: str) -> CriticResult:
    known = {
        "accept": VALID_CRITIC_RESULT,
        "revise_code": CODE_FAILURE_VERDICT,
        "revise_tests": TEST_FAILURE_VERDICT,
    }
    if action in known:
        return CriticResult.model_validate(known[action])
    return CriticResult(
        verdict="execution_failure" if action == "retry_execution" else "ambiguous",
        reason="The evidence.",
        code_issue="",
        test_issue="",
        recommended_action=action,
    )


def test_budgets_are_small_and_separate() -> None:
    assert (MAX_REVISIONS, MAX_EXECUTION_RETRIES) == (2, 1)
    assert TERMINAL_DECISIONS == {
        "accept",
        "needs_human_review",
        "revision_budget_exhausted",
        "retry_budget_exhausted",
    }


@pytest.mark.parametrize(
    ("action", "revisions", "retries", "decision"),
    [
        pytest.param("accept", 0, 0, "accept", id="accept"),
        pytest.param(
            "accept",
            MAX_REVISIONS,
            MAX_EXECUTION_RETRIES,
            "accept",
            id="accept-after-budgets",
        ),
        pytest.param(
            "needs_human_review", 0, 0, "needs_human_review", id="human-review"
        ),
        pytest.param("revise_code", 0, 0, "revise_code", id="revise-code"),
        pytest.param(
            "revise_code",
            MAX_REVISIONS - 1,
            0,
            "revise_code",
            id="revise-code-last-revision",
        ),
        pytest.param(
            "revise_code",
            MAX_REVISIONS,
            0,
            "revision_budget_exhausted",
            id="revise-code-exhausted",
        ),
        pytest.param("revise_tests", 0, 0, "revise_tests", id="revise-tests"),
        pytest.param(
            "revise_tests",
            MAX_REVISIONS,
            0,
            "revision_budget_exhausted",
            id="revise-tests-exhausted",
        ),
        pytest.param("retry_execution", 0, 0, "retry_execution", id="retry"),
        pytest.param(
            "retry_execution",
            0,
            MAX_EXECUTION_RETRIES,
            "retry_budget_exhausted",
            id="retry-exhausted",
        ),
        pytest.param(
            "retry_execution",
            MAX_REVISIONS,
            0,
            "retry_execution",
            id="retries-ignore-revisions",
        ),
        pytest.param(
            "revise_code",
            0,
            MAX_EXECUTION_RETRIES,
            "revise_code",
            id="revisions-ignore-retries",
        ),
    ],
)
def test_route_repair(action: str, revisions: int, retries: int, decision: str) -> None:
    assert route_repair(verdict_for(action), revisions, retries) == decision


def test_routing_follows_the_action_not_the_verdict() -> None:
    cautious = CriticResult(
        verdict="code_failure",
        reason="Probably the code, but unclear.",
        code_issue="Maybe an off-by-one.",
        test_issue="",
        recommended_action="needs_human_review",
    )

    assert route_repair(cautious, 0, 0) == "needs_human_review"


@pytest.mark.parametrize(
    "critic_result",
    [
        pytest.param(None, id="no-critic-result"),
        pytest.param(
            CriticResult.model_construct(
                verdict="ambiguous",
                reason="?",
                code_issue="",
                test_issue="",
                recommended_action="rewrite_everything",
            ),
            id="unknown-action",
        ),
    ],
)
def test_anything_unexpected_stops_for_human_review(
    critic_result: CriticResult | None,
) -> None:
    assert route_repair(critic_result, 0, 0) == "needs_human_review"


def test_repair_router_reads_counters_from_state_defaulting_to_zero() -> None:
    assert repair_router({"critic_result": verdict_for("revise_code")}) == "revise_code"
    assert (
        repair_router(
            {
                "critic_result": verdict_for("revise_code"),
                "revision_count": MAX_REVISIONS,
            }
        )
        == "revision_budget_exhausted"
    )
    assert (
        repair_router(
            {
                "critic_result": verdict_for("retry_execution"),
                "execution_retry_count": MAX_EXECUTION_RETRIES,
            }
        )
        == "retry_budget_exhausted"
    )


def test_retry_execution_counts_a_retry_and_nothing_else() -> None:
    update = asyncio.run(retry_execution({"revision_count": 1}))

    assert update == {"execution_retry_count": 1}


def test_retry_execution_refuses_without_budget() -> None:
    with pytest.raises(ValueError, match="no execution retries left"):
        asyncio.run(retry_execution({"execution_retry_count": MAX_EXECUTION_RETRIES}))
