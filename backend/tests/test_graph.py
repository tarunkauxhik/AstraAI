import asyncio

import httpx2
import pytest

from app.graph import build_graph
from app.llm import LLMError
from app.state import GeneratedTests, GraphContext, Requirements
from tests.fake_llm import (
    VALID_GENERATED_TESTS_JSON,
    VALID_REQUIREMENTS,
    WORKFLOW_REPLIES,
    fake_llm,
    forced_tool,
    tool_call,
)

INITIAL = {"run_id": "run-1", "task": "Reverse a string.", "language": "python"}


def test_graph_topology() -> None:
    graph = build_graph().get_graph()

    assert set(graph.nodes) == {
        "__start__",
        "analyze_task",
        "generate_tests",
        "__end__",
    }
    assert {(edge.source, edge.target) for edge in graph.edges} == {
        ("__start__", "analyze_task"),
        ("analyze_task", "generate_tests"),
        ("generate_tests", "__end__"),
    }


def test_graph_passes_requirements_to_generate_tests_and_stores_both() -> None:
    prompts: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        tool = forced_tool(request)
        prompts[tool] = request.content.decode()
        return tool_call(WORKFLOW_REPLIES[tool], name=tool)

    state = asyncio.run(
        build_graph().ainvoke(INITIAL, context=GraphContext(llm=fake_llm(handler)))
    )

    requirements = Requirements.model_validate(VALID_REQUIREMENTS)
    assert state == {
        **INITIAL,
        "requirements": requirements,
        "generated_tests": GeneratedTests.model_validate_json(
            VALID_GENERATED_TESTS_JSON
        ),
    }
    assert list(prompts) == ["Requirements", "GeneratedTests"]
    assert requirements.problem_summary in prompts["GeneratedTests"]
    assert requirements.edge_cases[0] in prompts["GeneratedTests"]


def test_graph_stops_before_generate_tests_when_analysis_fails() -> None:
    tools: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        tools.append(forced_tool(request))
        return tool_call("not json", name=tools[-1])

    with pytest.raises(LLMError):
        asyncio.run(
            build_graph().ainvoke(INITIAL, context=GraphContext(llm=fake_llm(handler)))
        )

    assert tools == ["Requirements", "Requirements"]
