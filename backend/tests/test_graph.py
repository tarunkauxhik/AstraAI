import asyncio

import httpx2
import pytest

from app.graph import build_graph
from app.llm import LLMError
from app.nodes.critic import INVALID_VERDICT
from app.state import (
    CriticResult,
    GeneratedCode,
    GeneratedTests,
    GraphContext,
    Requirements,
)
from tests.fake_llm import (
    VALID_CRITIC_RESULT,
    VALID_GENERATED_TESTS,
    VALID_PYTHON_CODE,
    VALID_REQUIREMENTS,
    WORKFLOW_REPLIES,
    fake_llm,
    forced_tool,
    tool_call,
)
from tests.fake_sandbox import PASSED, FakeSandbox

INITIAL = {"run_id": "run-1", "task": "Reverse a string.", "language": "python"}


def test_graph_topology() -> None:
    graph = build_graph().get_graph()

    assert set(graph.nodes) == {
        "__start__",
        "analyze_task",
        "generate_tests",
        "generate_code",
        "execute_sandbox",
        "critic",
        "revise_code",
        "revise_tests",
        "retry_execution",
        "__end__",
    }
    assert {(edge.source, edge.target, edge.conditional) for edge in graph.edges} == {
        ("__start__", "analyze_task", False),
        ("analyze_task", "generate_tests", False),
        ("generate_tests", "generate_code", False),
        ("generate_code", "execute_sandbox", False),
        ("execute_sandbox", "critic", False),
        ("critic", "__end__", True),
        ("critic", "revise_code", True),
        ("critic", "revise_tests", True),
        ("critic", "retry_execution", True),
        ("revise_code", "execute_sandbox", False),
        ("revise_tests", "execute_sandbox", False),
        ("retry_execution", "execute_sandbox", False),
    }


def test_every_way_back_into_execution_passes_a_budget_counter() -> None:
    graph = build_graph().get_graph()

    into_execution = {
        edge.source for edge in graph.edges if edge.target == "execute_sandbox"
    }

    # generate_code runs once; the others each spend a bounded budget.
    assert into_execution == {
        "generate_code",
        "revise_code",
        "revise_tests",
        "retry_execution",
    }


def test_graph_feeds_each_node_and_stores_every_result() -> None:
    prompts: dict[str, str] = {}
    sandbox = FakeSandbox()

    def handler(request: httpx2.Request) -> httpx2.Response:
        tool = forced_tool(request)
        prompts[tool] = request.content.decode()
        return tool_call(WORKFLOW_REPLIES[tool], name=tool)

    state = asyncio.run(
        build_graph().ainvoke(
            INITIAL, context=GraphContext(llm=fake_llm(handler), sandbox=sandbox)
        )
    )

    requirements = Requirements.model_validate(VALID_REQUIREMENTS)
    generated_tests = GeneratedTests.model_validate(VALID_GENERATED_TESTS)
    generated_code = GeneratedCode.model_validate(VALID_PYTHON_CODE)
    assert state == {
        **INITIAL,
        "requirements": requirements,
        "generated_tests": generated_tests,
        "generated_code": generated_code,
        "execution_result": PASSED,
        "critic_result": CriticResult.model_validate(VALID_CRITIC_RESULT),
    }
    assert list(prompts) == [
        "Requirements",
        "GeneratedTests",
        "GeneratedCode",
        "CriticResult",
    ]
    assert requirements.problem_summary in prompts["GeneratedCode"]
    assert generated_tests.cases[0].name in prompts["GeneratedCode"]
    assert "PASSED 3 tests" in prompts["CriticResult"]
    assert sandbox.calls == [generated_code]


@pytest.mark.parametrize(
    ("failing_tool", "expected_tools", "sandbox_calls"),
    [
        pytest.param("Requirements", ["Requirements"] * 2, 0, id="analysis-fails"),
        pytest.param(
            "GeneratedTests",
            ["Requirements", "GeneratedTests", "GeneratedTests"],
            0,
            id="test-plan-fails",
        ),
        pytest.param(
            "GeneratedCode",
            ["Requirements", "GeneratedTests", "GeneratedCode", "GeneratedCode"],
            0,
            id="code-generation-fails",
        ),
    ],
)
def test_graph_stops_at_the_failing_node(
    failing_tool: str, expected_tools: list[str], sandbox_calls: int
) -> None:
    tools: list[str] = []
    sandbox = FakeSandbox()

    def handler(request: httpx2.Request) -> httpx2.Response:
        tool = forced_tool(request)
        tools.append(tool)
        arguments = "not json" if tool == failing_tool else WORKFLOW_REPLIES[tool]
        return tool_call(arguments, name=tool)

    with pytest.raises(LLMError):
        asyncio.run(
            build_graph().ainvoke(
                INITIAL, context=GraphContext(llm=fake_llm(handler), sandbox=sandbox)
            )
        )

    assert tools == expected_tools
    assert len(sandbox.calls) == sandbox_calls


def test_graph_completes_with_a_human_review_when_the_critic_answer_is_invalid() -> (
    None
):
    replies = {**WORKFLOW_REPLIES, "CriticResult": "not json"}

    state = asyncio.run(
        build_graph().ainvoke(
            INITIAL, context=GraphContext(llm=fake_llm(replies), sandbox=FakeSandbox())
        )
    )

    assert state["critic_result"] == INVALID_VERDICT
    assert state["execution_result"] == PASSED
