import asyncio
import json
from typing import Any

import pytest
from langgraph.runtime import Runtime

from app.llm import LLMError
from app.nodes.revise_code import revise_code
from app.nodes.revise_tests import revise_tests
from app.repair import MAX_REVISIONS
from app.state import (
    CriticResult,
    GeneratedCode,
    GeneratedTests,
    GraphContext,
    Requirements,
    RevisedSolution,
    RevisedTests,
)
from tests.fake_llm import (
    CODE_FAILURE_VERDICT,
    REVISED_SOLUTION,
    REVISED_TESTS,
    TEST_FAILURE_VERDICT,
    VALID_GENERATED_TESTS,
    VALID_PYTHON_CODE,
    VALID_REQUIREMENTS,
    ScriptedReplies,
    fake_llm,
)
from tests.fake_sandbox import FAILED, FakeSandbox

ORIGINAL = GeneratedCode.model_validate(VALID_PYTHON_CODE)
# node, tool, the verdict that leads to it, a valid reply
NODES = {
    "revise_code": (
        revise_code,
        "RevisedSolution",
        CODE_FAILURE_VERDICT,
        REVISED_SOLUTION,
    ),
    "revise_tests": (revise_tests, "RevisedTests", TEST_FAILURE_VERDICT, REVISED_TESTS),
}


def state_for(verdict: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {
        "run_id": "run-1",
        "task": "Reverse a string.",
        "language": "python",
        "requirements": Requirements.model_validate(VALID_REQUIREMENTS),
        "generated_tests": GeneratedTests.model_validate(VALID_GENERATED_TESTS),
        "generated_code": ORIGINAL,
        "execution_result": FAILED,
        "critic_result": CriticResult.model_validate(verdict),
        **changes,
    }


def run(
    name: str,
    reply: Any,
    sandbox: FakeSandbox | None = None,
    **changes: Any,
) -> tuple[dict[str, Any], ScriptedReplies]:
    node, tool, verdict, _ = NODES[name]
    replies = ScriptedReplies({tool: reply})
    context = GraphContext(llm=fake_llm(replies), sandbox=sandbox or FakeSandbox())
    update = asyncio.run(node(state_for(verdict, **changes), Runtime(context=context)))
    return update, replies


def test_revise_code_replaces_only_the_solution() -> None:
    update, replies = run("revise_code", REVISED_SOLUTION)

    revised = update["generated_code"]
    assert set(update) == {"generated_code", "revision_count"}
    assert revised.solution_code == REVISED_SOLUTION["solution_code"]
    assert revised.test_code == ORIGINAL.test_code
    assert revised.language == ORIGINAL.language
    assert update["revision_count"] == 1
    assert replies.calls == ["RevisedSolution"]


def test_revise_tests_replaces_only_the_tests() -> None:
    update, replies = run("revise_tests", REVISED_TESTS)

    revised = update["generated_code"]
    assert set(update) == {"generated_code", "revision_count"}
    assert revised.test_code == REVISED_TESTS["test_code"]
    assert revised.solution_code == ORIGINAL.solution_code
    assert update["revision_count"] == 1
    assert replies.calls == ["RevisedTests"]


@pytest.mark.parametrize("name", list(NODES))
def test_a_revision_increments_the_counter_exactly_once(name: str) -> None:
    update, _ = run(name, NODES[name][3], revision_count=1, execution_retry_count=1)

    assert update["revision_count"] == 2
    assert "execution_retry_count" not in update


@pytest.mark.parametrize("name", list(NODES))
@pytest.mark.parametrize(
    "evidence",
    [
        pytest.param("requirements", id="requirements"),
        pytest.param("test-plan", id="test-plan"),
        pytest.param("solution", id="solution"),
        pytest.param("tests", id="tests"),
        pytest.param("execution", id="execution"),
        pytest.param("diagnosis", id="diagnosis"),
    ],
)
def test_revisions_see_the_latest_artifacts_and_diagnosis(
    name: str, evidence: str
) -> None:
    _, replies = run(name, NODES[name][3])
    state = state_for(NODES[name][2])
    expected = {
        "requirements": state["requirements"].model_dump_json(indent=2),
        "test-plan": state["generated_tests"].model_dump_json(indent=2),
        "solution": ORIGINAL.solution_code,
        "tests": ORIGINAL.test_code,
        "execution": FAILED.model_dump_json(indent=2),
        "diagnosis": state["critic_result"].model_dump_json(indent=2),
    }[evidence]

    assert expected in replies.prompts[0]


@pytest.mark.parametrize(
    ("name", "reply"),
    [
        pytest.param("revise_code", "not json", id="code-malformed"),
        pytest.param(
            "revise_code", {**REVISED_SOLUTION, "test_code": "x"}, id="code-with-tests"
        ),
        pytest.param(
            "revise_code", {**REVISED_SOLUTION, "solution_code": ""}, id="code-empty"
        ),
        pytest.param("revise_tests", "not json", id="tests-malformed"),
        pytest.param(
            "revise_tests",
            {**REVISED_TESTS, "solution_code": "x"},
            id="tests-with-code",
        ),
        pytest.param(
            "revise_tests", {**REVISED_TESTS, "test_code": ""}, id="tests-empty"
        ),
    ],
)
def test_invalid_revision_output_updates_nothing(name: str, reply: Any) -> None:
    with pytest.raises(LLMError, match="invalid structured output"):
        run(name, reply)

    assert ORIGINAL == GeneratedCode.model_validate(VALID_PYTHON_CODE)


@pytest.mark.parametrize("name", list(NODES))
@pytest.mark.parametrize(
    "missing",
    [
        "requirements",
        "generated_tests",
        "generated_code",
        "execution_result",
        "critic_result",
    ],
)
def test_revisions_need_every_earlier_result(name: str, missing: str) -> None:
    node, tool, verdict, reply = NODES[name]
    replies = ScriptedReplies({tool: reply})
    state = {k: v for k, v in state_for(verdict).items() if k != missing}
    context = GraphContext(llm=fake_llm(replies), sandbox=FakeSandbox())

    with pytest.raises(ValueError, match=missing):
        asyncio.run(node(state, Runtime(context=context)))

    assert replies.calls == []


@pytest.mark.parametrize("name", list(NODES))
def test_revisions_refuse_to_exceed_the_budget(name: str) -> None:
    node, tool, verdict, reply = NODES[name]
    replies = ScriptedReplies({tool: reply})
    context = GraphContext(llm=fake_llm(replies), sandbox=FakeSandbox())
    state = state_for(verdict, revision_count=MAX_REVISIONS)

    with pytest.raises(ValueError, match="no revision budget left"):
        asyncio.run(node(state, Runtime(context=context)))

    assert replies.calls == []


@pytest.mark.parametrize(
    ("schema", "fields"),
    [
        pytest.param(RevisedSolution, {"solution_code", "explanation"}, id="solution"),
        pytest.param(RevisedTests, {"test_code", "explanation"}, id="tests"),
    ],
)
def test_revision_schemas_carry_only_their_own_artifact(
    schema: type, fields: set[str]
) -> None:
    json_schema = schema.model_json_schema()

    assert set(json_schema["properties"]) == fields
    assert json_schema["additionalProperties"] is False
    assert all(
        field["type"] == "string" for field in json_schema["properties"].values()
    )


@pytest.mark.parametrize("name", list(NODES))
def test_revisions_never_execute_anything(name: str) -> None:
    sandbox = FakeSandbox()

    run(name, NODES[name][3], sandbox=sandbox)

    assert sandbox.calls == []


def test_revision_output_is_plain_json_for_the_llm() -> None:
    assert json.loads(json.dumps(REVISED_SOLUTION)) == REVISED_SOLUTION
