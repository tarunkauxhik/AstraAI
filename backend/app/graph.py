from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.nodes.analyze_task import analyze_task
from app.nodes.generate_tests import generate_tests
from app.state import AgentState, GraphContext


def build_graph() -> CompiledStateGraph:
    builder = StateGraph(AgentState, context_schema=GraphContext)
    builder.add_node("analyze_task", analyze_task)
    builder.add_node("generate_tests", generate_tests)
    builder.add_edge(START, "analyze_task")
    builder.add_edge("analyze_task", "generate_tests")
    builder.add_edge("generate_tests", END)
    return builder.compile()
