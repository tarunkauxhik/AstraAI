from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.nodes.analyze_task import analyze_task
from app.nodes.critic import critic
from app.nodes.execute_sandbox import execute_sandbox
from app.nodes.generate_code import generate_code
from app.nodes.generate_tests import generate_tests
from app.nodes.retry_execution import retry_execution
from app.nodes.revise_code import revise_code
from app.nodes.revise_tests import revise_tests
from app.repair import repair_router
from app.state import AgentState, GraphContext


def build_graph() -> CompiledStateGraph:
    builder = StateGraph(AgentState, context_schema=GraphContext)
    builder.add_node("analyze_task", analyze_task)
    builder.add_node("generate_tests", generate_tests)
    builder.add_node("generate_code", generate_code)
    builder.add_node("execute_sandbox", execute_sandbox)
    builder.add_node("critic", critic)
    builder.add_node("revise_code", revise_code)
    builder.add_node("revise_tests", revise_tests)
    builder.add_node("retry_execution", retry_execution)

    builder.add_edge(START, "analyze_task")
    builder.add_edge("analyze_task", "generate_tests")
    builder.add_edge("generate_tests", "generate_code")
    builder.add_edge("generate_code", "execute_sandbox")
    builder.add_edge("execute_sandbox", "critic")
    # The repair loop. Every way back into execute_sandbox passes a bounded counter:
    # revise_code and revise_tests spend the revision budget, retry_execution the retry one.
    builder.add_conditional_edges(
        "critic",
        repair_router,
        {
            "accept": END,
            "needs_human_review": END,
            "revision_budget_exhausted": END,
            "retry_budget_exhausted": END,
            "revise_code": "revise_code",
            "revise_tests": "revise_tests",
            "retry_execution": "retry_execution",
        },
    )
    builder.add_edge("revise_code", "execute_sandbox")
    builder.add_edge("revise_tests", "execute_sandbox")
    builder.add_edge("retry_execution", "execute_sandbox")
    return builder.compile()
