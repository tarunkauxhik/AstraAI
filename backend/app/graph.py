from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.nodes.analyze_task import analyze_task
from app.nodes.critic import critic
from app.nodes.execute_sandbox import execute_sandbox
from app.nodes.generate_code import generate_code
from app.nodes.generate_tests import generate_tests
from app.nodes.human_approval import human_approval
from app.nodes.retry_execution import retry_execution
from app.nodes.revise_code import revise_code
from app.nodes.revise_tests import revise_tests
from app.repair import repair_router
from app.state import (
    AgentState,
    CriticResult,
    ExecutionResult,
    GeneratedCode,
    GeneratedTests,
    GraphContext,
    Requirements,
)

# Every application type stored in checkpoints, allowlisted for msgpack deserialization.
CHECKPOINTED_MODELS = (
    Requirements,
    GeneratedTests,
    GeneratedCode,
    ExecutionResult,
    CriticResult,
)


def build_checkpointer() -> InMemorySaver:
    """One in-memory checkpointer for the whole process; runs are isolated by thread_id.

    State holds application data only: the LLM client and sandbox travel in the runtime
    context, which is never checkpointed.
    """
    allowed = [(model.__module__, model.__name__) for model in CHECKPOINTED_MODELS]
    return InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=allowed))


def build_graph(checkpointer: BaseCheckpointSaver | None) -> CompiledStateGraph:
    """The AstraAi workflow. Pausing for human approval needs a checkpointer."""
    builder = StateGraph(AgentState, context_schema=GraphContext)
    builder.add_node("analyze_task", analyze_task)
    builder.add_node("generate_tests", generate_tests)
    builder.add_node("generate_code", generate_code)
    builder.add_node("execute_sandbox", execute_sandbox)
    builder.add_node("critic", critic)
    builder.add_node("revise_code", revise_code)
    builder.add_node("revise_tests", revise_tests)
    builder.add_node("retry_execution", retry_execution)
    builder.add_node("human_approval", human_approval)

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
            "accept": "human_approval",
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
    builder.add_edge("human_approval", END)
    return builder.compile(checkpointer=checkpointer)
