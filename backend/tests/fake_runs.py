"""Helpers for run-lifecycle tests: gated fakes, a manager factory and polling."""

import asyncio
import time
from collections.abc import Callable
from typing import Any

import httpx2
from fastapi.testclient import TestClient

from app.config import Settings
from app.graph import build_graph
from app.llm import LLMClient
from app.runs import RunManager
from app.sandbox.executor import SandboxExecutor
from app.state import ExecutionResult, GeneratedCode, GraphContext
from tests.fake_llm import WORKFLOW_REPLIES, Reply, fake_llm, forced_tool, tool_call
from tests.fake_sandbox import PASSED, FakeSandbox

STEPS = ("Requirements", "GeneratedTests", "GeneratedCode", "sandbox", "CriticResult")


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


async def hold_forever(request: httpx2.Request) -> httpx2.Response:
    """LLM handler that never answers, keeping a run busy for as long as a test needs."""
    await asyncio.Event().wait()
    raise AssertionError("unreachable")


def manager_factory(
    reply: Reply = WORKFLOW_REPLIES,
    sandbox: Callable[[], SandboxExecutor] = FakeSandbox,
    *,
    max_queued_runs: int = 10,
) -> Callable[[Settings, GraphContext], RunManager]:
    """Stand-in for app.main.build_run_manager that wires in fakes.

    The fakes are built inside, because the app lifespan calls this on its own event loop.
    """

    def build(settings: Settings, context: GraphContext) -> RunManager:
        return RunManager(
            build_graph(),
            GraphContext(llm=fake_llm(reply), sandbox=sandbox()),
            max_active_runs=1,
            max_queued_runs=max_queued_runs,
            max_retained_runs=100,
            run_timeout_seconds=300,
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
