from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.nodes.analyze_task import analyze_task
from app.nodes.execute_sandbox import execute_sandbox
from app.nodes.generate_code import generate_code
from app.nodes.generate_tests import generate_tests
from app.state import AgentState, GraphContext


def build_graph() -> CompiledStateGraph:
    builder = StateGraph(AgentState, context_schema=GraphContext)
    builder.add_node("analyze_task", analyze_task)
    builder.add_node("generate_tests", generate_tests)
    builder.add_node("generate_code", generate_code)
    builder.add_node("execute_sandbox", execute_sandbox)
    builder.add_edge(START, "analyze_task")
    builder.add_edge("analyze_task", "generate_tests")
    builder.add_edge("generate_tests", "generate_code")
    builder.add_edge("generate_code", "execute_sandbox")
    builder.add_edge("execute_sandbox", END)
    return builder.compile()
