import asyncio
import json
import os
import subprocess
from typing import Any

import httpx2
import pytest
from langgraph.runtime import Runtime

from app.llm import LLMClient, LLMError
from app.nodes.critic import DETERMINISTIC_FAILURES, INVALID_VERDICT, critic, reconcile
from app.state import (
    CriticResult,
    ExecutionResult,
    GeneratedCode,
    GeneratedTests,
    GraphContext,
    Requirements,
)
from tests.fake_llm import (
    VALID_CRITIC_RESULT,
    VALID_CRITIC_RESULT_JSON,
    VALID_GENERATED_TESTS,
    VALID_PYTHON_CODE,
    VALID_REQUIREMENTS,
    fake_llm,
    tool_call,
)
from tests.fake_sandbox import PASSED, FakeSandbox

FAILED_TESTS = ExecutionResult(
    status="failed",
    exit_code=1,
    stdout="FAIL basic_word: expected cba, got abc\n",
    tests_failed=1,
    error_type="test_failure",
)
STATE: dict[str, Any] = {
    "run_id": "run-1",
    "task": "Reverse a string.",
    "language": "python",
    "requirements": Requirements.model_validate(VALID_REQUIREMENTS),
    "generated_tests": GeneratedTests.model_validate(VALID_GENERATED_TESTS),
    "generated_code": GeneratedCode.model_validate(VALID_PYTHON_CODE),
    "execution_result": FAILED_TESTS,
}


class Recorder:
    """Fake LLM handler that records critic prompts and replies with fixed arguments."""

    def __init__(self, arguments: str = VALID_CRITIC_RESULT_JSON) -> None:
        self.arguments = arguments
        self.prompts: list[str] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        self.prompts.append(body["messages"][1]["content"])
        return tool_call(self.arguments, name=body["tool_choice"]["function"]["name"])


def run_node(
    llm: LLMClient, state: dict[str, Any] = STATE, sandbox: FakeSandbox | None = None
) -> dict[str, Any]:
    context = GraphContext(llm=llm, sandbox=sandbox or FakeSandbox())
    return asyncio.run(critic(state, Runtime(context=context)))


def verdict(**changes: Any) -> dict[str, Any]:
    return {**VALID_CRITIC_RESULT, **changes}


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(VALID_CRITIC_RESULT, id="pass"),
        pytest.param(
            verdict(
                verdict="code_failure",
                reason="reverse returns its input unchanged.",
                code_issue="The characters are never reversed.",
                recommended_action="revise_code",
            ),
            id="code-failure",
        ),
        pytest.param(
            verdict(
                verdict="test_failure",
                reason="The requirements say reverse; the test expects the input back.",
                test_issue="basic_word expects abc for abc, but reversing gives cba.",
                recommended_action="revise_tests",
            ),
            id="test-failure",
        ),
        pytest.param(
            verdict(
                verdict="execution_failure",
                reason="The test file does not compile, so no case ran.",
                code_issue="solution.cpp is missing a semicolon.",
                recommended_action="revise_code",
            ),
            id="execution-failure",
        ),
        pytest.param(
            verdict(
                verdict="ambiguous",
                reason="The requirements do not say how to treat whitespace.",
                recommended_action="needs_human_review",
            ),
            id="ambiguous",
        ),
    ],
)
def test_critic_stores_the_structured_verdict(reply: dict[str, Any]) -> None:
    recorder = Recorder(json.dumps(reply))
    # A pass may only stand on passing evidence.
    evidence = PASSED if reply["verdict"] == "pass" else FAILED_TESTS

    update = run_node(
        fake_llm(recorder.handler), {**STATE, "execution_result": evidence}
    )

    assert update == {"critic_result": CriticResult.model_validate(reply)}
    assert len(recorder.prompts) == 1


@pytest.mark.parametrize(
    "evidence",
    [
        pytest.param(
            STATE["requirements"].model_dump_json(indent=2), id="requirements"
        ),
        pytest.param(
            STATE["generated_tests"].model_dump_json(indent=2), id="test-plan"
        ),
        pytest.param(VALID_PYTHON_CODE["solution_code"], id="solution-code"),
        pytest.param(VALID_PYTHON_CODE["test_code"], id="test-code"),
        pytest.param(FAILED_TESTS.model_dump_json(indent=2), id="execution-result"),
        pytest.param("Task:\nReverse a string.", id="task"),
        pytest.param("Language: python", id="language"),
    ],
)
def test_critic_receives_every_piece_of_evidence(evidence: str) -> None:
    recorder = Recorder()

    run_node(fake_llm(recorder.handler))

    assert evidence in recorder.prompts[0]


@pytest.mark.parametrize(
    "evidence",
    [
        pytest.param(PASSED, id="passed"),
        pytest.param(FAILED_TESTS, id="failed-assertion"),
        pytest.param(
            ExecutionResult(
                status="failed",
                exit_code=90,
                stderr="error: expected ';'",
                error_type="compile_error",
            ),
            id="compile-error",
        ),
        pytest.param(
            ExecutionResult(
                status="failed",
                exit_code=1,
                stderr="NameError: name 'x' is not defined",
                error_type="runtime_error",
            ),
            id="runtime-error",
        ),
    ],
)
def test_normal_execution_evidence_calls_the_llm_exactly_once(
    evidence: ExecutionResult,
) -> None:
    recorder = Recorder()

    run_node(fake_llm(recorder.handler), {**STATE, "execution_result": evidence})

    assert len(recorder.prompts) == 1


@pytest.mark.parametrize(
    ("status", "action"),
    [
        pytest.param(
            "infrastructure_error", "retry_execution", id="sandbox-unavailable"
        ),
        pytest.param("timed_out", "needs_human_review", id="timeout"),
        pytest.param("resource_exceeded", "needs_human_review", id="resource-exceeded"),
    ],
)
def test_no_evidence_outcomes_are_classified_without_the_llm(
    status: str, action: str
) -> None:
    recorder = Recorder()
    evidence = ExecutionResult(
        status=status,
        exit_code=1,
        stderr="Error response from daemon: SECRET-INTERNAL-DETAIL",
    )

    update = run_node(
        fake_llm(recorder.handler), {**STATE, "execution_result": evidence}
    )

    result = update["critic_result"]
    assert recorder.prompts == []
    assert (result.verdict, result.recommended_action) == ("execution_failure", action)
    assert (result.code_issue, result.test_issue) == ("", "")
    assert "SECRET" not in result.model_dump_json()


def test_only_evidence_free_outcomes_skip_the_llm() -> None:
    assert set(DETERMINISTIC_FAILURES) == {
        "infrastructure_error",
        "timed_out",
        "resource_exceeded",
    }


def test_sandbox_limits_never_ask_for_a_code_rewrite() -> None:
    for status in ("timed_out", "resource_exceeded"):
        assert DETERMINISTIC_FAILURES[status].recommended_action == "needs_human_review"


@pytest.mark.parametrize(
    "missing",
    ["requirements", "generated_tests", "generated_code", "execution_result"],
)
def test_critic_needs_every_earlier_result(missing: str) -> None:
    recorder = Recorder()
    state = {key: value for key, value in STATE.items() if key != missing}

    with pytest.raises(ValueError, match=missing):
        run_node(fake_llm(recorder.handler), state)

    assert recorder.prompts == []


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param("not json", id="malformed-json"),
        pytest.param(json.dumps(verdict(confidence="high")), id="unknown-field"),
        pytest.param(
            json.dumps(verdict(solution_code="def f(): ...")), id="code-field"
        ),
        pytest.param(json.dumps(verdict(test_code="assert f()")), id="test-code-field"),
        pytest.param(
            json.dumps(verdict(replacement_tests="new cases")), id="replacement-tests"
        ),
        pytest.param(json.dumps(verdict(verdict="maybe")), id="unknown-verdict"),
        pytest.param(
            json.dumps(verdict(recommended_action="revise_code")),
            id="pass-without-accept",
        ),
        pytest.param(
            json.dumps(verdict(verdict="code_failure")), id="accept-without-pass"
        ),
        pytest.param(json.dumps(verdict(reason="")), id="empty-reason"),
        pytest.param(
            json.dumps(
                {k: v for k, v in VALID_CRITIC_RESULT.items() if k != "verdict"}
            ),
            id="missing-verdict",
        ),
    ],
)
def test_invalid_critic_output_becomes_a_safe_human_review(arguments: str) -> None:
    update = run_node(fake_llm(Recorder(arguments).handler))

    assert update == {"critic_result": INVALID_VERDICT}
    assert (INVALID_VERDICT.verdict, INVALID_VERDICT.recommended_action) == (
        "ambiguous",
        "needs_human_review",
    )


def test_llm_request_failures_still_fail_the_critic() -> None:
    llm = fake_llm(lambda request: httpx2.Response(500))

    with pytest.raises(LLMError, match="request failed"):
        run_node(llm)


MODEL_PASS = CriticResult.model_validate(VALID_CRITIC_RESULT)
CODE_FAILURE = CriticResult(
    verdict="code_failure",
    reason="reverse returns its input unchanged.",
    code_issue="The characters are never reversed.",
    test_issue="",
    recommended_action="revise_code",
)
TEST_FAILURE = CriticResult(
    verdict="test_failure",
    reason="basic_word expects the input back, but the requirements say reverse.",
    code_issue="",
    test_issue="basic_word should expect cba.",
    recommended_action="revise_tests",
)


def evidence(status: str) -> ExecutionResult:
    return ExecutionResult(status=status, exit_code=0 if status == "passed" else 1)


@pytest.mark.parametrize(
    ("status", "judged"),
    [
        pytest.param("passed", MODEL_PASS, id="passed-and-pass"),
        pytest.param("failed", CODE_FAILURE, id="failed-and-code-failure"),
        pytest.param("failed", TEST_FAILURE, id="failed-and-test-failure"),
        pytest.param("passed", CODE_FAILURE, id="passed-but-tests-too-weak"),
    ],
)
def test_reconcile_keeps_verdicts_the_evidence_allows(
    status: str, judged: CriticResult
) -> None:
    assert reconcile(judged, evidence(status)) == judged


@pytest.mark.parametrize(
    "status", ["failed", "timed_out", "resource_exceeded", "infrastructure_error"]
)
def test_reconcile_never_lets_a_pass_stand_without_passing_tests(status: str) -> None:
    result = reconcile(MODEL_PASS, evidence(status))

    assert result.verdict != "pass"
    assert result.recommended_action in ("needs_human_review", "retry_execution")


@pytest.mark.parametrize("judged", [MODEL_PASS, CODE_FAILURE, TEST_FAILURE])
def test_reconcile_keeps_infrastructure_failures_deterministic(
    judged: CriticResult,
) -> None:
    result = reconcile(judged, evidence("infrastructure_error"))

    assert (result.verdict, result.recommended_action) == (
        "execution_failure",
        "retry_execution",
    )


def test_failed_tests_with_a_model_pass_become_a_human_review() -> None:
    recorder = Recorder(VALID_CRITIC_RESULT_JSON)

    result = run_node(fake_llm(recorder.handler))["critic_result"]

    assert len(recorder.prompts) == 1
    assert (result.verdict, result.recommended_action) == (
        "ambiguous",
        "needs_human_review",
    )
    assert "failed" in result.reason
    assert (result.code_issue, result.test_issue) == ("", "")


@pytest.mark.parametrize("status", ["timed_out", "resource_exceeded"])
def test_sandbox_limits_with_a_model_pass_are_still_not_a_pass(status: str) -> None:
    recorder = Recorder(VALID_CRITIC_RESULT_JSON)

    result = run_node(
        fake_llm(recorder.handler), {**STATE, "execution_result": evidence(status)}
    )["critic_result"]

    assert recorder.prompts == []
    assert (result.verdict, result.recommended_action) == (
        "execution_failure",
        "needs_human_review",
    )


def test_critic_schema_is_flat_with_no_place_for_code() -> None:
    schema = CriticResult.model_json_schema()

    assert "$defs" not in schema
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "verdict",
        "reason",
        "code_issue",
        "test_issue",
        "recommended_action",
    }
    assert all(field["type"] == "string" for field in schema["properties"].values())


def test_critic_never_executes_or_changes_earlier_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("the critic must not run anything")

    monkeypatch.setattr(subprocess, "run", explode)
    monkeypatch.setattr(subprocess, "Popen", explode)
    monkeypatch.setattr(os, "system", explode)
    sandbox = FakeSandbox()

    update = run_node(fake_llm(Recorder().handler), sandbox=sandbox)

    assert list(update) == ["critic_result"]
    assert sandbox.calls == []
