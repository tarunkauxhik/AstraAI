import asyncio

from app.graph import build_graph
from app.state import GraphContext, Requirements
from tests.fake_llm import VALID_REQUIREMENTS, VALID_REQUIREMENTS_JSON, fake_llm


def test_graph_topology() -> None:
    graph = build_graph().get_graph()

    assert set(graph.nodes) == {"__start__", "analyze_task", "__end__"}
    assert {(edge.source, edge.target) for edge in graph.edges} == {
        ("__start__", "analyze_task"),
        ("analyze_task", "__end__"),
    }


def test_graph_execution_stores_requirements() -> None:
    context = GraphContext(llm=fake_llm(VALID_REQUIREMENTS_JSON))
    initial = {"run_id": "run-1", "task": "Reverse a string.", "language": "python"}

    state = asyncio.run(build_graph().ainvoke(initial, context=context))

    assert state == {**initial, "requirements": Requirements(**VALID_REQUIREMENTS)}
