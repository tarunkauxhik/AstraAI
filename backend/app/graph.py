from pathlib import Path

import aiosqlite
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.nodes.analyze_task import analyze_task
from app.nodes.critic import critic
from app.nodes.edit_code import edit_code
from app.nodes.execute_sandbox import execute_sandbox
from app.nodes.generate_code import generate_code
from app.nodes.generate_tests import generate_tests
from app.nodes.human_approval import human_approval
from app.nodes.prepare_repository import prepare_repository
from app.nodes.repair_changes import repair_changes
from app.nodes.retry_execution import retry_execution
from app.nodes.review_changes import review_changes
from app.nodes.revise_code import revise_code
from app.nodes.revise_tests import revise_tests
from app.nodes.run_existing_tests import run_existing_tests
from app.nodes.run_tests import run_tests
from app.nodes.understand_task import understand_task
from app.repair import develop_router, repair_router
from app.state import (
    AgentState,
    ChangePlan,
    ChangeSet,
    CriticResult,
    ExecutionResult,
    FileChange,
    FirstAttempt,
    GeneratedCode,
    GeneratedTests,
    GraphContext,
    RepositoryRef,
    Requirements,
)

# Every application type stored in checkpoints, allowlisted for msgpack deserialization.
CHECKPOINTED_MODELS = (
    Requirements,
    GeneratedTests,
    GeneratedCode,
    ExecutionResult,
    CriticResult,
    RepositoryRef,
    ChangePlan,
    ChangeSet,
    FileChange,
    FirstAttempt,
)


def checkpoint_serde() -> JsonPlusSerializer:
    """Checkpoint serialization that only revives the application's own models.

    State holds application data only: the LLM client and sandbox travel in the runtime
    context, which is never checkpointed.
    """
    allowed = [(model.__module__, model.__name__) for model in CHECKPOINTED_MODELS]
    return JsonPlusSerializer(allowed_msgpack_modules=allowed)


def build_checkpointer(path: str | Path) -> AsyncSqliteSaver:
    """One SQLite checkpointer for the whole process; runs are isolated by thread_id.

    Needs a running event loop. It connects on first use, and whoever owns it closes
    `checkpointer.conn`. Its own file: it holds a write lock across awaits, which must not
    meet the run store's synchronous writes.
    """
    return AsyncSqliteSaver(aiosqlite.connect(path), serde=checkpoint_serde())


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


def existing_tests_ran(state: AgentState) -> str:
    """Change the repository only if its own tests can run here: they verify the change.

    Failing tests still ran. A suite that couldn't run stops the run before any model call.
    """
    result = state.get("existing_tests")
    ran = result is not None and (
        result.status == "passed" or result.error_type == "test_failure"
    )
    return "understand_task" if ran else END


def repaired(state: AgentState) -> str:
    """Test and review a repair that was made; if none could be, the first change stands."""
    return "run_tests" if state.get("first_attempt") is not None else END


def build_develop_graph(checkpointer: BaseCheckpointSaver | None) -> CompiledStateGraph:
    """DEVELOP: the repository at its current commit and its own tests, then one change,
    the same tests on the changed repository, and a review. If the tests or the review show
    the change is wrong, one repair, tested and reviewed the same way; then it ends.

    Shares the SOLVE graph's checkpointer; a run's mode decides which graph drives it.
    """
    builder = StateGraph(AgentState, context_schema=GraphContext)
    builder.add_node("prepare_repository", prepare_repository)
    builder.add_node("run_existing_tests", run_existing_tests)
    builder.add_node("understand_task", understand_task)
    builder.add_node("edit_code", edit_code)
    builder.add_node("run_tests", run_tests)
    builder.add_node("review_changes", review_changes)
    builder.add_node("repair_changes", repair_changes)
    builder.add_edge(START, "prepare_repository")
    builder.add_edge("prepare_repository", "run_existing_tests")
    builder.add_conditional_edges(
        "run_existing_tests",
        existing_tests_ran,
        {"understand_task": "understand_task", END: END},
    )
    builder.add_edge("understand_task", "edit_code")
    builder.add_edge("edit_code", "run_tests")
    builder.add_edge("run_tests", "review_changes")
    builder.add_conditional_edges(
        "review_changes",
        develop_router,
        {"repair_changes": "repair_changes", "finish": END},
    )
    builder.add_conditional_edges(
        "repair_changes", repaired, {"run_tests": "run_tests", END: END}
    )
    return builder.compile(checkpointer=checkpointer)
