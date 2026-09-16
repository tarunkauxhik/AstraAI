import asyncio
import json
import os
import subprocess
from typing import Any

import httpx2
import pytest
from langgraph.runtime import Runtime

from app.llm import LLMClient, LLMError
from app.nodes.generate_code import generate_code
from app.state import GeneratedCode, GeneratedTests, GraphContext, Requirements
from tests.fake_llm import (
    VALID_CPP_CODE,
    VALID_GENERATED_TESTS,
    VALID_PYTHON_CODE,
    VALID_PYTHON_CODE_JSON,
    VALID_REQUIREMENTS,
    fake_llm,
    tool_call,
)
from tests.fake_sandbox import FakeSandbox

REQUIREMENTS = Requirements.model_validate(VALID_REQUIREMENTS)
GENERATED_TESTS = GeneratedTests.model_validate(VALID_GENERATED_TESTS)
STATE = {
    "run_id": "run-1",
    "task": "Reverse a string.",
    "language": "python",
    "requirements": REQUIREMENTS,
    "generated_tests": GENERATED_TESTS,
}


def run_node(llm: LLMClient, state: dict[str, Any] = STATE) -> dict[str, Any]:
    return asyncio.run(
        generate_code(
            state, Runtime(context=GraphContext(llm=llm, sandbox=FakeSandbox()))
        )
    )


def code(**changes: Any) -> str:
    return json.dumps({**VALID_PYTHON_CODE, **changes})


def test_generate_code_returns_only_generated_code() -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        return tool_call(VALID_PYTHON_CODE_JSON, name="GeneratedCode")

    update = run_node(fake_llm(handler))

    assert list(update) == ["generated_code"]
    assert update["generated_code"] == GeneratedCode.model_validate(VALID_PYTHON_CODE)
    assert requests[0]["tool_choice"]["function"]["name"] == "GeneratedCode"


def test_generate_code_prompt_carries_task_requirements_and_test_plan() -> None:
    prompts: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        prompts.append(json.loads(request.content)["messages"][1]["content"])
        return tool_call(VALID_PYTHON_CODE_JSON, name="GeneratedCode")

    run_node(fake_llm(handler))

    prompt = prompts[0]
    assert "Language: python" in prompt
    assert "Task:\nReverse a string." in prompt
    assert REQUIREMENTS.model_dump_json(indent=2) in prompt
    assert GENERATED_TESTS.model_dump_json(indent=2) in prompt
    assert "basic_word" in prompt


@pytest.mark.parametrize(
    "fixture", [VALID_PYTHON_CODE, VALID_CPP_CODE], ids=["python", "cpp"]
)
def test_generate_code_stores_code_strings(fixture: dict[str, str]) -> None:
    state = {**STATE, "language": fixture["language"]}

    generated = run_node(fake_llm(json.dumps(fixture)), state)["generated_code"]

    assert isinstance(generated.solution_code, str)
    assert isinstance(generated.test_code, str)
    assert generated.language == fixture["language"]
    assert generated.solution_code == fixture["solution_code"]
    assert generated.test_code == fixture["test_code"]
    assert "```" not in generated.solution_code + generated.test_code


@pytest.mark.parametrize("missing", ["requirements", "generated_tests"])
def test_generate_code_needs_earlier_results_and_skips_llm(missing: str) -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return tool_call(VALID_PYTHON_CODE_JSON, name="GeneratedCode")

    state = {key: value for key, value in STATE.items() if key != missing}

    with pytest.raises(ValueError, match=missing):
        run_node(fake_llm(handler), state)

    assert requests == []


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param("not json", id="malformed-json"),
        pytest.param(code(files=[{"path": "solution.py"}]), id="unknown-field"),
        pytest.param(code(solution_code=""), id="empty-solution"),
        pytest.param(code(test_code=""), id="empty-test-code"),
        pytest.param(code(solution_code={}), id="empty-object-solution"),
        pytest.param(
            code(solution_code={"files": ["solution.py"]}), id="nested-solution"
        ),
        pytest.param(code(test_code=["import sys"]), id="list-test-code"),
        pytest.param(code(language="rust"), id="unsupported-language"),
        pytest.param(
            json.dumps(
                {k: v for k, v in VALID_PYTHON_CODE.items() if k != "test_code"}
            ),
            id="missing-test-code",
        ),
    ],
)
def test_generate_code_rejects_invalid_output(arguments: str) -> None:
    with pytest.raises(LLMError, match="invalid structured output"):
        run_node(fake_llm(arguments))


def test_generate_code_never_runs_the_generated_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("generate_code must not run anything")

    monkeypatch.setattr(subprocess, "run", explode)
    monkeypatch.setattr(subprocess, "Popen", explode)
    monkeypatch.setattr(os, "system", explode)
    crashing = "raise RuntimeError('executed')\n"

    generated = run_node(fake_llm(code(solution_code=crashing, test_code=crashing)))[
        "generated_code"
    ]

    assert generated.solution_code == crashing
    assert generated.test_code == crashing


def test_generated_code_schema_is_flat_strings() -> None:
    schema = GeneratedCode.model_json_schema()

    assert "$defs" not in schema
    assert set(schema["properties"]) == {
        "language",
        "solution_code",
        "test_code",
        "explanation",
    }
    assert all(field["type"] == "string" for field in schema["properties"].values())
    assert schema["additionalProperties"] is False
