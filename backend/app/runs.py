"""Run lifecycle: run records, a bounded queue, and in-process workers that drive the graph.

Everything queue-shaped lives behind RunManager, so a durable backend (a database or a
broker) can replace it later without changing the API or the graph.
"""

import asyncio
import logging
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict

from app.llm import LLMError, LLMTimeoutError
from app.repair import route_repair
from app.state import (
    CriticResult,
    ExecutionResult,
    GeneratedCode,
    GeneratedTests,
    GraphContext,
    Language,
    Requirements,
)

logger = logging.getLogger(__name__)

RunStatus = Literal["queued", "running", "completed", "failed"]
RunStage = Literal[
    "queued",
    "analyzing",
    "generating_tests",
    "generating_code",
    "executing",
    "reviewing",
    "revising_code",
    "revising_tests",
    "completed",
    "failed",
]

# The stage a run is in while each graph node works. Presentation only: nodes never see it.
NODE_STAGES: dict[str, RunStage] = {
    "analyze_task": "analyzing",
    "generate_tests": "generating_tests",
    "generate_code": "generating_code",
    "execute_sandbox": "executing",
    "critic": "reviewing",
    "revise_code": "revising_code",
    "revise_tests": "revising_tests",
    # A retry re-runs the same code at once, so it reads as executing.
    "retry_execution": "executing",
}
RESULT_FIELDS = frozenset(
    {
        "requirements",
        "generated_tests",
        "generated_code",
        "execution_result",
        "critic_result",
        "revision_count",
        "execution_retry_count",
    }
)


class RunError(BaseModel):
    """A concise, user-safe explanation of why a run failed."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    stage: RunStage


class Run(BaseModel):
    """Everything a client may see about one run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: RunStatus
    stage: RunStage
    task: str
    language: Language
    created_at: datetime
    updated_at: datetime
    requirements: Requirements | None = None
    generated_tests: GeneratedTests | None = None
    generated_code: GeneratedCode | None = None
    execution_result: ExecutionResult | None = None
    critic_result: CriticResult | None = None
    revision_count: int = 0
    execution_retry_count: int = 0
    error: RunError | None = None


class QueueFullError(Exception):
    """Too many runs are already waiting to execute."""


class RunManagerStoppedError(Exception):
    """The run manager is shutting down and accepts no new runs."""


# How long shutdown waits for an active run to cancel and clean up its sandbox.
SHUTDOWN_GRACE_SECONDS = 30
RUN_TIMEOUT_MESSAGE = "The run took longer than the allowed time and was stopped."
SHUTDOWN_MESSAGE = "The run was stopped because the service is shutting down."
# Safe explanations for runs that end without a verified solution, by repair decision.
UNRESOLVED_MESSAGES = {
    "needs_human_review": "The agent could not confirm a correct solution, so the result "
    "needs human review.",
    "revision_budget_exhausted": "The agent used all of its revision attempts without "
    "reaching a verified solution.",
    "retry_budget_exhausted": "The code could not be executed, even after retrying.",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def safe_error(exc: Exception, stage: RunStage) -> RunError:
    """Describe a failure without leaking internals such as messages or tracebacks."""
    if isinstance(exc, LLMTimeoutError):
        code, message = "llm_timeout", "The language model took too long to respond."
    elif isinstance(exc, LLMError):
        code = "llm_failed"
        message = "The language model request failed or returned unusable output."
    elif isinstance(exc, ValueError):
        code = "invalid_step_output"
        message = "A step produced output that the next step could not use."
    else:
        code, message = "internal_error", "The run failed because of an internal error."
    return RunError(code=code, message=message, stage=stage)


class RunManager:
    """Creates, queues and executes runs in this process, a bounded number at a time.

    Workers pull run ids from a bounded queue and drive the LangGraph workflow. Stages and
    partial results are recorded from the graph's own stream, so the nodes stay unaware.
    """

    def __init__(
        self,
        graph: CompiledStateGraph,
        context: GraphContext,
        *,
        max_active_runs: int,
        max_queued_runs: int,
        max_retained_runs: int,
        run_timeout_seconds: float,
    ) -> None:
        self._graph = graph
        self._context = context
        self._max_active_runs = max_active_runs
        self._max_retained_runs = max_retained_runs
        self._run_timeout_seconds = run_timeout_seconds
        self._runs: OrderedDict[str, Run] = OrderedDict()
        self._enqueued: set[str] = set()
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=max_queued_runs)
        self._workers: list[asyncio.Task[None]] = []
        self._stopping = False

    async def start(self) -> None:
        """Start one worker per allowed active run."""
        self._stopping = False
        self._workers = [
            asyncio.create_task(self._work()) for _ in range(self._max_active_runs)
        ]

    async def stop(self) -> None:
        """Stop taking work, fail waiting runs, cancel active ones and await cleanup."""
        self._stopping = True
        waiting = [
            run_id for run_id, run in self._runs.items() if run.status == "queued"
        ]
        for run_id in waiting:
            self._fail(run_id, self._error(run_id, "shutdown", SHUTDOWN_MESSAGE))
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            _, pending = await asyncio.wait(
                self._workers, timeout=SHUTDOWN_GRACE_SECONDS
            )
            if pending:
                logger.warning("%d run worker(s) did not stop in time", len(pending))
        self._workers = []

    def submit(self, task: str, language: Language) -> Run:
        """Create a queued run and enqueue it; raise if stopping or nothing fits."""
        if self._stopping:
            raise RunManagerStoppedError
        if self._queue.full():
            raise QueueFullError
        created = utc_now()
        run = Run(
            run_id=str(uuid4()),
            status="queued",
            stage="queued",
            task=task,
            language=language,
            created_at=created,
            updated_at=created,
        )
        self._runs[run.run_id] = run
        self.enqueue(run.run_id)
        self._forget_old_runs()
        return run

    def enqueue(self, run_id: str) -> bool:
        """Queue a waiting run once; False if it is unknown, already queued or started."""
        run = self._runs.get(run_id)
        if run is None or run.status != "queued" or run_id in self._enqueued:
            return False
        try:
            self._queue.put_nowait(run_id)
        except asyncio.QueueFull as exc:
            raise QueueFullError from exc
        self._enqueued.add(run_id)
        return True

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    async def _work(self) -> None:
        while True:
            run_id = await self._queue.get()
            try:
                await self._execute(run_id)
            finally:
                self._queue.task_done()

    async def _execute(self, run_id: str) -> None:
        self._enqueued.discard(run_id)
        run = self._runs.get(run_id)
        if self._stopping or run is None or run.status != "queued":
            return  # Shutting down, forgotten, or already claimed: never run twice.
        # Claim it before the first await, so no other worker can start it too.
        self._update(run_id, status="running")
        initial = {"run_id": run_id, "task": run.task, "language": run.language}
        try:
            async with asyncio.timeout(self._run_timeout_seconds):
                await self._drive_graph(run_id, initial)
        except TimeoutError:
            # Cancelling the graph also cancels the active node, whose own cleanup
            # (for example removing a sandbox container) runs before we get here.
            self._fail(run_id, self._error(run_id, "run_timeout", RUN_TIMEOUT_MESSAGE))
            return
        except asyncio.CancelledError:
            self._fail(run_id, self._error(run_id, "shutdown", SHUTDOWN_MESSAGE))
            raise
        # Worker boundary: any failure must become a safe, failed run, never a dead worker.
        except Exception as exc:  # noqa: BLE001
            self._fail(run_id, safe_error(exc, self._runs[run_id].stage), exc)
            return
        self._finish(run_id)

    async def _drive_graph(self, run_id: str, initial: dict[str, Any]) -> None:
        async for mode, chunk in self._graph.astream(
            initial, context=self._context, stream_mode=["tasks", "updates"]
        ):
            if mode == "tasks" and "input" in chunk and chunk["name"] in NODE_STAGES:
                self._update(run_id, stage=NODE_STAGES[chunk["name"]])
            elif mode == "updates":
                for values in chunk.values():
                    results = {
                        key: value
                        for key, value in (values or {}).items()
                        if key in RESULT_FIELDS
                    }
                    self._update(run_id, **results)

    def _update(self, run_id: str, **changes: Any) -> None:
        run = self._runs[run_id]
        self._runs[run_id] = run.model_copy(update={**changes, "updated_at": utc_now()})

    def _error(self, run_id: str, code: str, message: str) -> RunError:
        return RunError(code=code, message=message, stage=self._runs[run_id].stage)

    def _fail(
        self, run_id: str, error: RunError, exc: BaseException | None = None
    ) -> None:
        if error.code == "internal_error":
            logger.error("Run %s failed during %s", run_id, error.stage, exc_info=exc)
        else:
            logger.warning(
                "Run %s failed during %s: %s", run_id, error.stage, error.code
            )
        self._update(run_id, status="failed", stage="failed", error=error)

    def _finish(self, run_id: str) -> None:
        result = self._runs[run_id].execution_result
        if result is not None and result.status == "infrastructure_error":
            # The code never ran, so the run did not complete. Sandbox output here would
            # be daemon messages, not program output, so it is not exposed.
            logger.warning(
                "Run %s: sandbox unavailable (%s)", run_id, result.error_type
            )
            self._update(
                run_id,
                status="failed",
                stage="failed",
                execution_result=result.model_copy(update={"stdout": "", "stderr": ""}),
                error=RunError(
                    code="sandbox_unavailable",
                    message="The code could not be executed because the sandbox is "
                    "unavailable.",
                    stage="executing",
                ),
            )
            return
        run = self._runs[run_id]
        decision = route_repair(
            run.critic_result, run.revision_count, run.execution_retry_count
        )
        if decision == "accept":
            self._update(run_id, status="completed", stage="completed")
            return
        # The graph stopped without a verified solution: never report that as success.
        logger.warning("Run %s ended without a verified solution: %s", run_id, decision)
        self._update(
            run_id,
            status="failed",
            stage="failed",
            error=RunError(
                code=decision,
                message=UNRESOLVED_MESSAGES.get(
                    decision, UNRESOLVED_MESSAGES["needs_human_review"]
                ),
                stage="reviewing",
            ),
        )

    def _forget_old_runs(self) -> None:
        """Keep memory bounded: drop the oldest finished runs beyond the retention limit."""
        excess = len(self._runs) - self._max_retained_runs
        if excess <= 0:
            return
        finished = [
            run_id
            for run_id, run in self._runs.items()
            if run.status in ("completed", "failed")
        ]
        for run_id in finished[:excess]:
            del self._runs[run_id]
