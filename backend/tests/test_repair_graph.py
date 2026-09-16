"""The repair loop as LangGraph runs it, with scripted LLM replies and sandbox results."""

import asyncio
from typing import Any

from app.graph import build_graph
from app.repair import MAX_EXECUTION_RETRIES, MAX_REVISIONS, repair_router
from app.state import CriticResult, GeneratedCode, GraphContext
from tests.fake_llm import (
    CODE_FAILURE_VERDICT,
    REVISED_SOLUTION,
    REVISED_TESTS,
    TEST_FAILURE_VERDICT,
    VALID_CRITIC_RESULT,
    VALID_PYTHON_CODE,
    WORKFLOW_REPLIES,
    ScriptedReplies,
    fake_llm,
)
from tests.fake_sandbox import FAILED, INFRASTRUCTURE_ERROR, PASSED, ScriptedSandbox

INITIAL = {"run_id": "run-1", "task": "Reverse a string.", "language": "python"}
ORIGINAL = GeneratedCode.model_validate(VALID_PYTHON_CODE)
GENERATION = ["Requirements", "GeneratedTests", "GeneratedCode"]


def run_graph(
    sandbox: ScriptedSandbox, **replies: Any
) -> tuple[dict[str, Any], ScriptedReplies]:
    scripted = ScriptedReplies({**WORKFLOW_REPLIES, **replies})
    state = asyncio.run(
        build_graph().ainvoke(
            INITIAL, context=GraphContext(llm=fake_llm(scripted), sandbox=sandbox)
        )
    )
    return state, scripted


def test_correct_solution_passes_straight_through() -> None:
    sandbox = ScriptedSandbox(PASSED)

    state, llm = run_graph(sandbox)

    assert llm.calls == [*GENERATION, "CriticResult"]
    assert sandbox.calls == [ORIGINAL]
    assert state.get("revision_count", 0) == 0
    assert repair_router(state) == "accept"


def test_wrong_code_is_revised_then_executed_and_reviewed_again() -> None:
    sandbox = ScriptedSandbox(FAILED, PASSED)

    state, llm = run_graph(
        sandbox,
        CriticResult=[CODE_FAILURE_VERDICT, VALID_CRITIC_RESULT],
        RevisedSolution=REVISED_SOLUTION,
    )

    assert llm.calls == [*GENERATION, "CriticResult", "RevisedSolution", "CriticResult"]
    first, second = sandbox.calls
    assert first == ORIGINAL
    assert second.solution_code == REVISED_SOLUTION["solution_code"]
    assert second.test_code == ORIGINAL.test_code
    # The state holds exactly the pair that was executed and reviewed last.
    assert state["generated_code"] == second
    assert REVISED_SOLUTION["solution_code"] in llm.prompts[-1]
    assert (state["execution_result"], state["revision_count"]) == (PASSED, 1)
    assert repair_router(state) == "accept"


def test_wrong_test_is_revised_then_executed_and_reviewed_again() -> None:
    sandbox = ScriptedSandbox(FAILED, PASSED)

    state, llm = run_graph(
        sandbox,
        CriticResult=[TEST_FAILURE_VERDICT, VALID_CRITIC_RESULT],
        RevisedTests=REVISED_TESTS,
    )

    assert llm.calls == [*GENERATION, "CriticResult", "RevisedTests", "CriticResult"]
    first, second = sandbox.calls
    assert first == ORIGINAL
    assert second.test_code == REVISED_TESTS["test_code"]
    assert second.solution_code == ORIGINAL.solution_code
    assert state["generated_code"] == second
    assert state["revision_count"] == 1
    assert repair_router(state) == "accept"


def test_infrastructure_error_retries_execution_without_a_revision() -> None:
    sandbox = ScriptedSandbox(INFRASTRUCTURE_ERROR, PASSED)

    state, llm = run_graph(sandbox)

    # The infrastructure verdict is deterministic, so the model reviews only real evidence.
    assert llm.calls == [*GENERATION, "CriticResult"]
    assert sandbox.calls == [ORIGINAL, ORIGINAL]
    assert state["execution_retry_count"] == 1
    assert state.get("revision_count", 0) == 0
    assert repair_router(state) == "accept"


def test_persistent_infrastructure_error_stops_when_retries_run_out() -> None:
    sandbox = ScriptedSandbox(INFRASTRUCTURE_ERROR)

    state, llm = run_graph(sandbox)

    assert llm.calls == GENERATION
    assert len(sandbox.calls) == 1 + MAX_EXECUTION_RETRIES
    assert state["execution_retry_count"] == MAX_EXECUTION_RETRIES
    assert repair_router(state) == "retry_budget_exhausted"


def test_repeated_code_failure_never_exceeds_the_revision_budget() -> None:
    sandbox = ScriptedSandbox(FAILED)

    state, llm = run_graph(
        sandbox, CriticResult=CODE_FAILURE_VERDICT, RevisedSolution=REVISED_SOLUTION
    )

    assert llm.calls.count("RevisedSolution") == MAX_REVISIONS
    assert len(sandbox.calls) == 1 + MAX_REVISIONS
    # Exactly one critic call per execution.
    assert llm.calls.count("CriticResult") == len(sandbox.calls)
    assert state["revision_count"] == MAX_REVISIONS
    assert repair_router(state) == "revision_budget_exhausted"


def test_code_and_test_revisions_share_one_budget() -> None:
    sandbox = ScriptedSandbox(FAILED)

    state, llm = run_graph(
        sandbox,
        CriticResult=[CODE_FAILURE_VERDICT, TEST_FAILURE_VERDICT, CODE_FAILURE_VERDICT],
        RevisedSolution=REVISED_SOLUTION,
        RevisedTests=REVISED_TESTS,
    )

    assert (llm.calls.count("RevisedSolution"), llm.calls.count("RevisedTests")) == (
        1,
        1,
    )
    assert state["revision_count"] == MAX_REVISIONS
    last = state["generated_code"]
    assert last.solution_code == REVISED_SOLUTION["solution_code"]
    assert last.test_code == REVISED_TESTS["test_code"]
    assert repair_router(state) == "revision_budget_exhausted"


def test_human_review_verdict_ends_without_repairs() -> None:
    sandbox = ScriptedSandbox(FAILED)
    review = CriticResult(
        verdict="ambiguous",
        reason="The requirements do not settle it.",
        code_issue="",
        test_issue="",
        recommended_action="needs_human_review",
    )

    state, llm = run_graph(sandbox, CriticResult=review.model_dump())

    assert llm.calls == [*GENERATION, "CriticResult"]
    assert len(sandbox.calls) == 1
    assert repair_router(state) == "needs_human_review"


def test_worst_case_spends_both_budgets_and_still_terminates() -> None:
    # Retry once after an infrastructure error, then revise twice: the longest possible run.
    sandbox = ScriptedSandbox(INFRASTRUCTURE_ERROR, FAILED)

    state, llm = run_graph(
        sandbox, CriticResult=CODE_FAILURE_VERDICT, RevisedSolution=REVISED_SOLUTION
    )

    assert len(sandbox.calls) == 1 + MAX_EXECUTION_RETRIES + MAX_REVISIONS
    assert (state["execution_retry_count"], state["revision_count"]) == (
        MAX_EXECUTION_RETRIES,
        MAX_REVISIONS,
    )
    # Deterministic infrastructure verdicts skip the model; real evidence gets one review each.
    assert llm.calls.count("CriticResult") == len(sandbox.calls) - MAX_EXECUTION_RETRIES
    assert repair_router(state) == "revision_budget_exhausted"
