import asyncio

import httpx2
import pytest

from app.graph import build_graph
from app.llm import LLMError
from app.state import GeneratedCode, GeneratedTests, GraphContext, Requirements
from tests.fake_llm import (
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
        "__end__",
    }
    assert {(edge.source, edge.target) for edge in graph.edges} == {
        ("__start__", "analyze_task"),
        ("analyze_task", "generate_tests"),
        ("generate_tests", "generate_code"),
        ("generate_code", "execute_sandbox"),
        ("execute_sandbox", "__end__"),
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
    }
    assert list(prompts) == ["Requirements", "GeneratedTests", "GeneratedCode"]
    assert requirements.problem_summary in prompts["GeneratedCode"]
    assert generated_tests.cases[0].name in prompts["GeneratedCode"]
    assert sandbox.calls == [generated_code]


@pytest.mark.parametrize(
    ("failing_tool", "expected_tools"),
    [
        pytest.param("Requirements", ["Requirements"] * 2, id="analysis-fails"),
        pytest.param(
            "GeneratedTests",
            ["Requirements", "GeneratedTests", "GeneratedTests"],
            id="test-plan-fails",
        ),
        pytest.param(
            "GeneratedCode",
            ["Requirements", "GeneratedTests", "GeneratedCode", "GeneratedCode"],
            id="code-generation-fails",
        ),
    ],
)
def test_graph_stops_at_the_failing_node(
    failing_tool: str, expected_tools: list[str]
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
    assert sandbox.calls == []
