from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.state import AgentState


def placeholder(state: AgentState) -> dict[str, Any]:
    """Pass-through node so the graph compiles; replaced once real nodes exist."""
    return {}


def build_graph() -> CompiledStateGraph:
    builder = StateGraph(AgentState)
    builder.add_node("placeholder", placeholder)
    builder.add_edge(START, "placeholder")
    builder.add_edge("placeholder", END)
    return builder.compile()
