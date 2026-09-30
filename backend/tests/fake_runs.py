"""Helpers for run-lifecycle tests: gated fakes, a manager factory and polling."""

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2
from fastapi.testclient import TestClient
from langgraph.graph.state import CompiledStateGraph

from app.config import Settings, get_settings
from app.github import GitHubProvider
from app.graph import build_checkpointer, build_develop_graph, build_graph
from app.llm import LLMClient
from app.runs import Run, RunManager
from app.sandbox.executor import SandboxExecutor
from app.state import ExecutionResult, GeneratedCode, GraphContext
from app.store import RunStore
from tests.fake_llm import WORKFLOW_REPLIES, Reply, fake_llm, forced_tool, tool_call
from tests.fake_sandbox import PASSED, FakeSandbox

STEPS = ("Requirements", "GeneratedTests", "GeneratedCode", "sandbox", "CriticResult")


def storage(data_dir: Path | None = None) -> tuple[CompiledStateGraph, RunStore]:
    """The graph and run store on real SQLite files, as the app builds them.

    Defaults to the test's own data dir, so a second manager in the same test finds the
    first one's runs, as a restarted process would. Needs a running event loop.
    """
    data_dir = data_dir or get_settings().data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    graph = build_graph(build_checkpointer(data_dir / "checkpoints.sqlite3"))
    return graph, RunStore(data_dir / "runs.sqlite3")


def stored(run_id: str) -> Run | None:
    """Read a run straight from the test's run store, as the next process would."""
    store = RunStore(get_settings().data_dir / "runs.sqlite3")
    try:
        return store.get(run_id)
    finally:
        store.close()


class GatedSandbox(FakeSandbox):
    """Sandbox that waits for its gate before returning a result."""

    def __init__(self, gate: asyncio.Event, result: ExecutionResult = PASSED) -> None:
        super().__init__(result)
        self._gate = gate

    async def execute(self, generated_code: GeneratedCode) -> ExecutionResult:
        await self._gate.wait()
        return await super().execute(generated_code)


class Gates:
    """One event per workflow step; each step waits until the test opens its gate.

    Create it inside the event loop that runs the scenario.
    """

    def __init__(self) -> None:
        self.events = {step: asyncio.Event() for step in STEPS}

    def open(self, *steps: str) -> None:
        for step in steps or STEPS:
            self.events[step].set()

    def llm(self, replies: dict[str, str] = WORKFLOW_REPLIES) -> LLMClient:
        async def handler(request: httpx2.Request) -> httpx2.Response:
            tool = forced_tool(request)
            await self.events[tool].wait()
            return tool_call(replies[tool], name=tool)

        return fake_llm(handler)

    def sandbox(self, result: ExecutionResult = PASSED) -> GatedSandbox:
        return GatedSandbox(self.events["sandbox"], result)


class Clock:
    """A controllable UTC clock for RunManager, so approval timeouts need no sleeping."""

    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


async def hold_forever(request: httpx2.Request) -> httpx2.Response:
    """LLM handler that never answers, keeping a run busy for as long as a test needs."""
    await asyncio.Event().wait()
    raise AssertionError("unreachable")


def manager_factory(
    reply: Reply = WORKFLOW_REPLIES,
    sandbox: Callable[[], SandboxExecutor] = FakeSandbox,
    *,
    github: Callable[[], GitHubProvider] | None = None,
    max_queued_runs: int = 10,
    **options: Any,
) -> Callable[[Settings, GraphContext], RunManager]:
    """Stand-in for app.main.build_run_manager that wires in fakes.

    The fakes are built inside, because the app lifespan calls this on its own event loop.
    """

    def build(settings: Settings, context: GraphContext) -> RunManager:
        graph, store = storage(settings.data_dir)
        return RunManager(
            graph,
            GraphContext(
                llm=fake_llm(reply),
                sandbox=sandbox(),
                github=github() if github is not None else None,
            ),
            store,
            develop_graph=build_develop_graph(graph.checkpointer),
            max_active_runs=1,
            max_queued_runs=max_queued_runs,
            max_retained_runs=100,
            run_timeout_seconds=300,
            approval_timeout_seconds=600,
            **options,
        )

    return build


def poll(
    client: TestClient,
    run_id: str,
    done: Callable[[dict[str, Any]], bool],
    timeout: float = 5.0,
) -> dict[str, Any]:
    """GET a run until `done` holds, failing clearly if it never does."""
    deadline = time.monotonic() + timeout
    while True:
        run = client.get(f"/runs/{run_id}").json()
        if done(run):
            return run
        if time.monotonic() > deadline:
            raise AssertionError(f"run stuck at {run.get('status')}/{run.get('stage')}")
        time.sleep(0.01)
