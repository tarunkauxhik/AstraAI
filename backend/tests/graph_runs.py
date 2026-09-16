"""Drive the checkpointed graph directly, on one thread per test, as RunManager does."""

from typing import Any

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.graph import build_checkpointer, build_graph
from app.state import GraphContext


def thread(run_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": run_id}}


def checkpointed_graph() -> CompiledStateGraph:
    return build_graph(build_checkpointer())


async def start(
    graph: CompiledStateGraph, initial: dict[str, Any], context: GraphContext
) -> dict[str, Any]:
    return await graph.ainvoke(
        initial, config=thread(initial["run_id"]), context=context
    )


async def resume(
    graph: CompiledStateGraph, run_id: str, answer: object, context: GraphContext
) -> dict[str, Any]:
    return await graph.ainvoke(
        Command(resume=answer), config=thread(run_id), context=context
    )


async def pending_interrupts(graph: CompiledStateGraph, run_id: str) -> list[Any]:
    return [item.value for item in (await graph.aget_state(thread(run_id))).interrupts]
