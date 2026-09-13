from app.graph import build_graph
from app.state import AgentState


def test_graph_compiles_with_expected_nodes() -> None:
    graph = build_graph()

    assert set(graph.get_graph().nodes) == {"__start__", "placeholder", "__end__"}


def test_graph_invocation_returns_state() -> None:
    state: AgentState = {
        "run_id": "run-1",
        "task": "Reverse a string.",
        "language": "python",
        "max_attempts": 3,
        "attempt_count": 0,
        "status": "pending",
        "errors": [],
    }

    assert build_graph().invoke(state) == state
