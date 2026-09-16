"""Opt-in checks against the real endpoint configured in .env or the environment.

Run with ASTRAAI_LIVE_LLM=1. The critic cases also execute code, so they need
ASTRAAI_DOCKER_TESTS=1 and the local Docker daemon. Never part of the normal run.
"""

import asyncio
import os

import pytest
from langgraph.runtime import Runtime

from app.config import Settings
from app.llm import LLMClient
from app.nodes.critic import critic
from app.sandbox.docker import DockerSandbox
from app.state import (
    CriticResult,
    GeneratedCode,
    GeneratedTests,
    GraphContext,
    Requirements,
)
from tests.fake_sandbox import FakeSandbox
from tests.graph_runs import checkpointed_graph, start

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("ASTRAAI_LIVE_LLM") != "1",
        reason="set ASTRAAI_LIVE_LLM=1 to call the real LLM",
    ),
]
needs_docker = pytest.mark.skipif(
    os.getenv("ASTRAAI_DOCKER_TESTS") != "1",
    reason="set ASTRAAI_DOCKER_TESTS=1 to execute generated code",
)


def report(*lines: str) -> None:
    """Print for -s runs without failing on consoles that cannot encode model text."""
    for line in lines:
        print(line.encode("ascii", "backslashreplace").decode("ascii"))


def real_context(sandbox: object | None = None) -> GraphContext:
    settings = Settings()
    return GraphContext(
        llm=LLMClient(settings), sandbox=sandbox or DockerSandbox(settings)
    )


def run_pipeline(task: str, language: str, context: GraphContext) -> dict:
    return asyncio.run(
        start(
            checkpointed_graph(),
            {"run_id": "live", "task": task, "language": language},
            context,
        )
    )


def test_workflow_with_real_llm() -> None:
    task = "Given an array of integers and a target, return indices of two numbers summing to it."
    # The sandbox is faked here: this test covers the gateway, not Docker.
    state = run_pipeline(task, "cpp", real_context(FakeSandbox()))

    assert state["requirements"].functional_requirements
    assert state["generated_tests"].cases
    generated_code = state["generated_code"]
    assert generated_code.language == "cpp"
    assert "```" not in generated_code.solution_code + generated_code.test_code
    assert isinstance(state["critic_result"], CriticResult)
    assert state["critic_result"].reason


@needs_docker
@pytest.mark.parametrize(
    ("language", "task"),
    [
        pytest.param(
            "python",
            "Write a function that returns the number of vowels in a lowercase string.",
            id="python",
        ),
        pytest.param(
            "cpp",
            "Write a function that returns the sum of all even numbers in a vector of ints.",
            id="cpp",
        ),
    ],
)
def test_correct_generated_solution_is_judged_by_the_critic(
    language: str, task: str
) -> None:
    state = run_pipeline(task, language, real_context())

    execution, verdict = state["execution_result"], state["critic_result"]
    report(
        f"{language}: execution={execution.status} critic={verdict.verdict}",
        f"reason: {verdict.reason}",
    )
    if execution.status == "passed":
        assert verdict.verdict == "pass", verdict.reason
    else:
        assert verdict.verdict != "pass", verdict.reason


SUM_EVEN_REQUIREMENTS = Requirements(
    problem_summary="Return the sum of the even integers in a list.",
    functional_requirements=[
        "Add up only the even numbers in nums.",
        "Return 0 when nums contains no even numbers.",
    ],
    edge_cases=["Empty list.", "Negative even numbers."],
    constraints=[],
    expected_input="nums: a list of integers",
    expected_output="An integer.",
    relevant_language_requirements=["Python function sum_even(nums) -> int."],
)
SUM_EVEN_TESTS = GeneratedTests.model_validate(
    {
        "interface": "function sum_even(nums: list of int) -> int",
        "comparison": "exact match",
        "cases": [
            {
                "name": "mixed_numbers",
                "category": "basic",
                "description": "Only 2 and 4 are even.",
                "input": "nums = [1, 2, 3, 4]",
                "input_generator": "",
                "expected_output": "6",
            },
            {
                "name": "no_even_numbers",
                "category": "empty_or_small",
                "description": "Nothing to add.",
                "input": "nums = [1, 3]",
                "input_generator": "",
                "expected_output": "0",
            },
            {
                "name": "negative_even",
                "category": "negative_or_zero",
                "description": "-2 is even.",
                "input": "nums = [-2, 5]",
                "input_generator": "",
                "expected_output": "-2",
            },
        ],
    }
)
SUM_EVEN_TEST_CODE = """import sys

from solution import sum_even

CASES = [
    ("mixed_numbers", [1, 2, 3, 4], 6),
    ("no_even_numbers", [1, 3], 0),
    ("negative_even", [-2, 5], -2),
]
failures = 0
for name, nums, expected in CASES:
    actual = sum_even(nums)
    if actual != expected:
        print(f"FAIL {name}: expected {expected}, got {actual}")
        failures += 1
if failures:
    sys.exit(1)
print(f"PASSED {len(CASES)} tests")
"""

REVERSE_REQUIREMENTS = Requirements(
    problem_summary="Return the characters of a string in reverse order.",
    functional_requirements=["Return s with its characters in reverse order."],
    edge_cases=["Empty string.", "Single character."],
    constraints=[],
    expected_input="s: a string",
    expected_output="The reversed string.",
    relevant_language_requirements=["Python function reverse(s) -> str."],
)
# The first case's expected result contradicts the requirements: reversing abc gives cba.
QUESTIONABLE_REVERSE_TESTS = GeneratedTests.model_validate(
    {
        "interface": "function reverse(s: str) -> str",
        "comparison": "exact match",
        "cases": [
            {
                "name": "basic_word",
                "category": "basic",
                "description": "Reverses a typical word.",
                "input": 's = "abc"',
                "input_generator": "",
                "expected_output": '"abc"',
            },
            {
                "name": "single_character",
                "category": "boundary",
                "description": "One character is its own reverse.",
                "input": 's = "x"',
                "input_generator": "",
                "expected_output": '"x"',
            },
        ],
    }
)
QUESTIONABLE_REVERSE_TEST_CODE = """import sys

from solution import reverse

CASES = [("basic_word", "abc", "abc"), ("single_character", "x", "x")]
failures = 0
for name, value, expected in CASES:
    actual = reverse(value)
    if actual != expected:
        print(f"FAIL {name}: expected {expected!r}, got {actual!r}")
        failures += 1
if failures:
    sys.exit(1)
print(f"PASSED {len(CASES)} tests")
"""


def judge(
    task: str,
    requirements: Requirements,
    tests: GeneratedTests,
    solution_code: str,
    test_code: str,
) -> tuple[str, CriticResult]:
    """Run hand-written code in real Docker, then ask the real critic about it."""
    context = real_context()
    code = GeneratedCode(
        language="python",
        solution_code=solution_code,
        test_code=test_code,
        explanation="hand-written live fixture",
    )
    execution = asyncio.run(context.sandbox.execute(code))
    state = {
        "run_id": "live-critic",
        "task": task,
        "language": "python",
        "requirements": requirements,
        "generated_tests": tests,
        "generated_code": code,
        "execution_result": execution,
    }
    update = asyncio.run(critic(state, Runtime(context=context)))
    result = update["critic_result"]
    report(
        f"execution={execution.status} critic={result.verdict}",
        f"reason: {result.reason}",
        f"code_issue: {result.code_issue}",
        f"test_issue: {result.test_issue}",
        f"action: {result.recommended_action}",
    )
    return execution.status, result


@needs_docker
def test_critic_blames_an_incorrect_implementation() -> None:
    status, result = judge(
        "Return the sum of the even integers in a list.",
        SUM_EVEN_REQUIREMENTS,
        SUM_EVEN_TESTS,
        "def sum_even(nums):\n    return sum(nums)\n",
        SUM_EVEN_TEST_CODE,
    )

    assert status == "failed"
    assert result.verdict == "code_failure", result.reason
    assert result.code_issue


@needs_docker
def test_critic_blames_a_test_whose_expectation_contradicts_the_requirements() -> None:
    status, result = judge(
        "Return the characters of a string in reverse order.",
        REVERSE_REQUIREMENTS,
        QUESTIONABLE_REVERSE_TESTS,
        "def reverse(s):\n    return s[::-1]\n",
        QUESTIONABLE_REVERSE_TEST_CODE,
    )

    assert status == "failed"
    assert result.verdict == "test_failure", result.reason
    assert result.test_issue
