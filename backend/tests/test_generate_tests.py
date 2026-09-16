import asyncio
import json
from typing import Any

import httpx2
import pytest
from langgraph.runtime import Runtime

from app.llm import LLMClient, LLMError
from app.nodes.generate_tests import generate_tests
from app.state import GeneratedTests, GraphContext, Requirements
from tests.fake_llm import (
    VALID_GENERATED_TESTS,
    VALID_GENERATED_TESTS_JSON,
    VALID_REQUIREMENTS,
    fake_llm,
    tool_call,
)
from tests.fake_sandbox import FakeSandbox

REQUIREMENTS = Requirements.model_validate(VALID_REQUIREMENTS)
STATE = {
    "run_id": "run-1",
    "task": "Reverse a string.",
    "language": "python",
    "requirements": REQUIREMENTS,
}


def run_node(llm: LLMClient, state: dict[str, Any] = STATE) -> dict[str, Any]:
    return asyncio.run(
        generate_tests(
            state, Runtime(context=GraphContext(llm=llm, sandbox=FakeSandbox()))
        )
    )


def plan(**changes: Any) -> str:
    return json.dumps({**VALID_GENERATED_TESTS, **changes})


def with_case(**changes: Any) -> str:
    return plan(cases=[{**VALID_GENERATED_TESTS["cases"][0], **changes}])


def case_without(key: str) -> str:
    case = {k: v for k, v in VALID_GENERATED_TESTS["cases"][0].items() if k != key}
    return plan(cases=[case])


def test_generate_tests_returns_only_the_test_plan() -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        return tool_call(VALID_GENERATED_TESTS_JSON, name="GeneratedTests")

    update = run_node(fake_llm(handler))

    assert update == {
        "generated_tests": GeneratedTests.model_validate(VALID_GENERATED_TESTS)
    }
    assert requests[0]["tool_choice"]["function"]["name"] == "GeneratedTests"
    assert requests[0]["messages"][1]["content"] == (
        "Language: python\n\nTask:\nReverse a string.\n\n"
        f"Requirements:\n{REQUIREMENTS.model_dump_json(indent=2)}"
    )


def test_generate_tests_accepts_generated_input() -> None:
    arguments = with_case(
        category="performance",
        input="",
        input_generator="s = 'a' * 100000",
        expected_output="the same 100000 'a' characters",
    )

    case = run_node(fake_llm(arguments))["generated_tests"].cases[0]

    assert (case.input, case.input_generator) == ("", "s = 'a' * 100000")


@pytest.mark.parametrize(
    "empty",
    [pytest.param({}, id="live-gateway-empty-object"), pytest.param(None, id="null")],
)
def test_generate_tests_reads_gateway_empty_values_as_empty_strings(
    empty: object,
) -> None:
    arguments = with_case(input="", input_generator=empty)

    case = run_node(fake_llm(arguments))["generated_tests"].cases[0]

    assert (case.input, case.input_generator) == ("", "")


def test_generate_tests_restores_numeric_expected_outputs_from_the_gateway() -> None:
    first, second = VALID_GENERATED_TESTS["cases"][:2]
    arguments = plan(
        cases=[{**first, "expected_output": 3}, {**second, "expected_output": 0}]
    )

    cases = run_node(fake_llm(arguments))["generated_tests"].cases

    assert [case.expected_output for case in cases] == ["3", "0"]


def test_generate_tests_needs_requirements_and_skips_llm() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return tool_call(VALID_GENERATED_TESTS_JSON, name="GeneratedTests")

    state = {key: value for key, value in STATE.items() if key != "requirements"}

    with pytest.raises(ValueError, match="needs requirements"):
        run_node(fake_llm(handler), state)

    assert requests == []


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param("not json", id="malformed-json"),
        pytest.param(plan(cases=[]), id="no-cases"),
        pytest.param(case_without("expected_output"), id="missing-expected-output"),
        pytest.param(
            plan(cases=[VALID_GENERATED_TESTS["cases"][0]] * 2), id="duplicate-names"
        ),
        pytest.param(plan(solution="def reverse(s): ..."), id="solution-field"),
        pytest.param(with_case(test_code="assert reverse('a')"), id="test-code-field"),
        pytest.param(with_case(category="random"), id="unknown-category"),
        pytest.param(with_case(input={"s": "abc"}), id="input-not-a-string"),
        pytest.param(
            with_case(expected_output={"item": ["c", "b", "a"]}),
            id="expected-output-mangled-object",
        ),
        pytest.param(with_case(input_generator=["a"]), id="generator-list"),
    ],
)
def test_generate_tests_rejects_invalid_test_plans(arguments: str) -> None:
    with pytest.raises(LLMError, match="invalid structured output"):
        run_node(fake_llm(arguments))


def test_test_plan_schema_is_flat_strings_with_no_place_for_code() -> None:
    schema = GeneratedTests.model_json_schema()
    case_properties = schema["$defs"]["GeneratedTestCase"]["properties"]

    assert set(schema["properties"]) == {"interface", "comparison", "cases"}
    assert set(case_properties) == {
        "name",
        "category",
        "description",
        "input",
        "input_generator",
        "expected_output",
    }
    assert all(field["type"] == "string" for field in case_properties.values())
