"""Run lifecycle: durable run records, a bounded queue, and in-process workers.

The run store is the source of truth for what the API reports; the checkpointer only holds
what a paused graph needs to continue. The queue is an execution mechanism, rebuilt from
the store when the process starts.

Restart semantics, applied by `start` before any worker runs:
- queued: never started, so it is queued again, in its original order.
- running: the process that owned the work is gone and nothing can confirm its outcome,
  so it fails as interrupted ("shutdown"), keeping the evidence it had. Sandbox executions
  are never continued.
- waiting_for_approval: still waiting on its checkpoint; the approval window is unchanged.
- approved and resuming: the approval was acknowledged, so it is carried out. The run
  resumes on the same thread if its checkpoint is still paused for approval, or completes if
  the resume already reached the end and only recording that was lost. Resuming only
  replays the approval step, which has no side effects, so repeating it is safe. Without a
  usable checkpoint it fails as interrupted.
- completed, failed, expired: unchanged.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, computed_field

from app.llm import LLMError, LLMTimeoutError
from app.repair import route_repair
from app.state import (
    ApprovalRequest,
    ApprovalStatus,
    CriticResult,
    ExecutionResult,
    GeneratedCode,
    GeneratedTests,
    GraphContext,
    Language,
    Requirements,
)

if TYPE_CHECKING:
    from app.store import RunStore

logger = logging.getLogger(__name__)

RunStatus = Literal[
    "queued",
    "running",
    "waiting_for_approval",
    "completed",
    "failed",
    # Nobody decided in time. Not a failure: the verified solution and its evidence stay.
    "expired",
]
Decision = Literal["approve", "reject"]
RunStage = Literal[
    "queued",
    "analyzing",
    "generating_tests",
    "generating_code",
    "executing",
    "reviewing",
    "revising_code",
    "revising_tests",
    "waiting_for_approval",
    # Approved and about to continue on its checkpoint.
    "resuming",
    "completed",
    "failed",
    "expired",
]
FINISHED_STATUSES: frozenset[RunStatus] = frozenset({"completed", "failed", "expired"})

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
        "approval_status",
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
    approval_status: ApprovalStatus | None = None
    approval_request: ApprovalRequest | None = None
    approval_requested_at: datetime | None = None
    approval_expires_at: datetime | None = None
    error: RunError | None = None

    @computed_field
    @property
    def approval_required(self) -> bool:
        return self.status == "waiting_for_approval"


class QueueFullError(Exception):
    """Too many runs are already waiting to execute."""


class RunManagerStoppedError(Exception):
    """The run manager is shutting down and accepts no new runs."""


class RunNotFoundError(Exception):
    """No run with this id is known."""


class ApprovalConflictError(Exception):
    """The run is not waiting for approval, or a decision was already made."""


class ApprovalExpiredError(ApprovalConflictError):
    """Nobody decided within the approval timeout, so the run can no longer be approved."""


# How long shutdown waits for an active run to cancel and clean up its sandbox.
SHUTDOWN_GRACE_SECONDS = 30
RUN_TIMEOUT_MESSAGE = "The run took longer than the allowed time and was stopped."
SHUTDOWN_MESSAGE = "The run was stopped because the service is shutting down."
RESTART_MESSAGE = (
    "The run was stopped because the service restarted while it was working."
)
REJECTED_MESSAGE = "A human rejected the verified solution."
# How often waiting runs are checked for an expired approval request.
APPROVAL_SWEEP_SECONDS = 60
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
    One manager per process owns the store and the checkpointer, and closes them on stop.
    """

    def __init__(
        self,
        graph: CompiledStateGraph,
        context: GraphContext,
        store: "RunStore",
        *,
        max_active_runs: int,
        max_queued_runs: int,
        max_retained_runs: int,
        run_timeout_seconds: float,
        approval_timeout_seconds: float,
        approval_sweep_seconds: float = APPROVAL_SWEEP_SECONDS,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if graph.checkpointer is None:
            raise ValueError("RunManager needs a graph compiled with a checkpointer")
        self._graph = graph
        self._context = context
        self._max_active_runs = max_active_runs
        self._max_retained_runs = max_retained_runs
        self._run_timeout_seconds = run_timeout_seconds
        self._approval_timeout = timedelta(seconds=approval_timeout_seconds)
        self._approval_sweep_seconds = approval_sweep_seconds
        self._clock = clock
        self._store = store
        self._enqueued: set[str] = set()
        # Approved runs queued to resume; only these may be claimed while not queued.
        self._resuming: set[str] = set()
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=max_queued_runs)
        self._workers: list[asyncio.Task[None]] = []
        self._sweeper: asyncio.Task[None] | None = None
        self._stopping = False

    async def start(self) -> None:
        """Reconcile stored runs, then start the workers and the approval sweeper, once."""
        if self._workers:
            return
        self._stopping = False
        await self._recover()
        self._workers = [
            asyncio.create_task(self._work()) for _ in range(self._max_active_runs)
        ]
        self._sweeper = asyncio.create_task(self._sweep_approvals())

    async def stop(self) -> None:
        """Stop taking work, cancel active runs, await their cleanup and close storage.

        Idle runs are left as stored: queued and approved runs are queued again, and
        waiting ones keep waiting, when the next process starts. So is an approved run whose
        resume is cancelled here: an acknowledged approval is never dropped.
        """
        self._stopping = True
        if self._sweeper is not None:
            self._sweeper.cancel()
            await asyncio.gather(self._sweeper, return_exceptions=True)
            self._sweeper = None
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            _, pending = await asyncio.wait(
                self._workers, timeout=SHUTDOWN_GRACE_SECONDS
            )
            if pending:
                logger.warning("%d run worker(s) did not stop in time", len(pending))
        self._workers = []
        self._store.close()
        if isinstance(self._graph.checkpointer, AsyncSqliteSaver):
            await self._graph.checkpointer.conn.close()

    async def _recover(self) -> None:
        """Apply the restart semantics in the module docstring to every unfinished run."""
        paused: set[str] = set()
        for run in self._store.with_status("queued", "running", "waiting_for_approval"):
            run_id = run.run_id
            if run.status == "waiting_for_approval":
                if await self._paused_for_approval(run_id):
                    paused.add(run_id)
                    continue
            elif run.status == "queued" or (
                run.stage == "resuming" and await self._paused_for_approval(run_id)
            ):
                if run.status == "running":
                    self._resuming.add(run_id)
                    paused.add(run_id)
                try:
                    self.enqueue(run_id)
                    continue
                except QueueFullError:
                    self._resuming.discard(run_id)
                    paused.discard(run_id)
            elif run.stage == "resuming" and await self._resume_finished(run_id):
                # The resume reached the end; only recording its outcome was lost.
                self._finish(run_id)
                continue
            logger.warning(
                "Run %s: interrupted by a restart during %s", run_id, run.stage
            )
            self._fail(run_id, self._error(run_id, "shutdown", RESTART_MESSAGE))
        # Only paused runs can use a checkpoint; any other is left over from the last process.
        checkpointer = self._graph.checkpointer
        threads = {
            saved.config["configurable"]["thread_id"]
            async for saved in checkpointer.alist(None)
        }
        for thread_id in threads - paused:
            await checkpointer.adelete_thread(thread_id)

    async def _paused_for_approval(self, run_id: str) -> bool:
        """Whether the run's checkpoint is paused at the approval interrupt."""
        state = await self._graph.aget_state({"configurable": {"thread_id": run_id}})
        return state.next == ("human_approval",) and bool(state.interrupts)

    async def _resume_finished(self, run_id: str) -> bool:
        """Whether the run's checkpoint shows an approved resume that reached the end."""
        state = await self._graph.aget_state({"configurable": {"thread_id": run_id}})
        return not state.next and state.values.get("approval_status") == "approved"

    def submit(self, task: str, language: Language) -> Run:
        """Create a queued run and enqueue it; raise if stopping or nothing fits."""
        if self._stopping:
            raise RunManagerStoppedError
        if self._queue.full():
            raise QueueFullError
        created = self._clock()
        run = Run(
            run_id=str(uuid4()),
            status="queued",
            stage="queued",
            task=task,
            language=language,
            created_at=created,
            updated_at=created,
        )
        self._store.put(run)
        self.enqueue(run.run_id)
        self._forget_old_runs()
        return run

    def enqueue(self, run_id: str) -> bool:
        """Queue a new or resuming run once; False if unknown, already queued or started."""
        run = self._store.get(run_id)
        claimable = run is not None and (
            run.status == "queued" or run_id in self._resuming
        )
        if not claimable or run_id in self._enqueued:
            return False
        try:
            self._queue.put_nowait(run_id)
        except asyncio.QueueFull as exc:
            raise QueueFullError from exc
        self._enqueued.add(run_id)
        return True

    def get(self, run_id: str) -> Run | None:
        return self._store.get(run_id)

    async def _waiting_run(self, run_id: str) -> Run:
        """The run, if it is still waiting for a human; otherwise raise why not.

        Returns without awaiting, so a caller's own changes still happen before its first
        await: on the event loop exactly one of approval, rejection, extension, expiry or
        shutdown wins for a run.
        """
        if self._stopping:
            raise RunManagerStoppedError
        run = self._store.get(run_id)
        if run is None:
            raise RunNotFoundError
        if run.approval_status == "expired":
            raise ApprovalExpiredError
        if run.status != "waiting_for_approval":
            raise ApprovalConflictError
        if self._approval_expired(run):
            # Expired but not yet swept: the answer must not depend on sweep timing.
            self._expire(run_id)
            await self._graph.checkpointer.adelete_thread(run_id)
            raise ApprovalExpiredError
        return run

    async def extend_approval(self, run_id: str) -> Run:
        """Give a waiting run a fresh approval window, counted from now.

        People who need longer to review can ask for more time as often as they like, so
        the timeout only ever ends a review nobody is attending to.
        """
        await self._waiting_run(run_id)
        self._update(run_id, approval_expires_at=self._clock() + self._approval_timeout)
        return self._store.get(run_id)

    async def resolve_approval(self, run_id: str, decision: Decision) -> Run:
        """Apply a human decision to a run waiting for approval.

        Approval queues the run to resume on its own thread; rejection ends it at once.
        """
        run = await self._waiting_run(run_id)
        if decision == "reject":
            self._update(
                run_id,
                status="failed",
                stage="failed",
                approval_status="rejected",
                error=RunError(
                    code="approval_rejected",
                    message=REJECTED_MESSAGE,
                    stage="waiting_for_approval",
                ),
            )
            logger.warning("Run %s: solution rejected", run_id)
            await self._graph.checkpointer.adelete_thread(run_id)
            return self._store.get(run_id)
        self._resuming.add(run_id)
        self._update(
            run_id, status="running", stage="resuming", approval_status="approved"
        )
        try:
            self.enqueue(run_id)
        except QueueFullError:
            self._resuming.discard(run_id)
            self._update(
                run_id,
                status=run.status,
                stage=run.stage,
                approval_status=run.approval_status,
            )
            raise
        return self._store.get(run_id)

    def _approval_expired(self, run: Run) -> bool:
        return (
            run.status == "waiting_for_approval"
            and run.approval_expires_at is not None
            and self._clock() >= run.approval_expires_at
        )

    def _expire(self, run_id: str) -> None:
        # The work succeeded; only the decision lapsed. So the run keeps its verified
        # solution and evidence, carries no error, and just can't be decided any more.
        logger.warning("Run %s: approval request expired", run_id)
        self._update(
            run_id, status="expired", stage="expired", approval_status="expired"
        )

    async def expire_approvals(self) -> list[str]:
        """End every run whose approval request has expired and drop its checkpoint."""
        if self._stopping:
            return []
        expired = [
            run.run_id
            for run in self._store.with_status("waiting_for_approval")
            if self._approval_expired(run)
        ]
        # Mark them all before awaiting, so no approval can slip in between.
        for run_id in expired:
            self._expire(run_id)
        for run_id in expired:
            await self._graph.checkpointer.adelete_thread(run_id)
        return expired

    async def _sweep_approvals(self) -> None:
        """One lightweight loop for every waiting run, instead of a timer per run."""
        while True:
            await asyncio.sleep(self._approval_sweep_seconds)
            try:
                await self.expire_approvals()
            # Keep sweeping: one failed pass must not leave waiting runs to pile up.
            except Exception:
                logger.exception("Approval sweep failed")

    async def _work(self) -> None:
        while True:
            run_id = await self._queue.get()
            try:
                await self._execute(run_id)
            # Storage errors (a full disk, say) must not end the worker; whatever state the
            # run was left in is reconciled at the next start.
            except Exception:
                logger.exception("Run %s: could not be recorded", run_id)
            finally:
                self._queue.task_done()

    async def _execute(self, run_id: str) -> None:
        self._enqueued.discard(run_id)
        run = self._store.get(run_id)
        resuming = run_id in self._resuming
        self._resuming.discard(run_id)
        if self._stopping or run is None or not (run.status == "queued" or resuming):
            return  # Shutting down, forgotten, or already claimed: never run twice.
        # Claim it before the first await, so no other worker can start it too. A new run
        # reads as analyzing at once: loading its checkpoint must not show running/queued.
        self._update(
            run_id, status="running", **({} if resuming else {"stage": "analyzing"})
        )
        graph_input: dict[str, Any] | Command = (
            Command(resume={"decision": "approve"})
            if resuming
            else {"run_id": run_id, "task": run.task, "language": run.language}
        )
        try:
            # Each start or resume gets its own window: waiting for a human is not counted.
            async with asyncio.timeout(self._run_timeout_seconds):
                approval_request = await self._drive_graph(run_id, graph_input)
        except TimeoutError:
            # Cancelling the graph also cancels the active node, whose own cleanup
            # (for example removing a sandbox container) runs before we get here.
            self._fail(run_id, self._error(run_id, "run_timeout", RUN_TIMEOUT_MESSAGE))
        except asyncio.CancelledError:
            # A cancelled resume stays approved and resuming; the next start finishes it.
            if not resuming:
                self._fail(run_id, self._error(run_id, "shutdown", SHUTDOWN_MESSAGE))
            raise
        # Worker boundary: any failure must become a safe, failed run, never a dead worker.
        except Exception as exc:  # noqa: BLE001
            self._fail(run_id, safe_error(exc, self._store.get(run_id).stage), exc)
        else:
            if approval_request is None:
                self._finish(run_id)
            else:
                # Paused, not finished: the checkpoint keeps the thread, and this worker
                # is free for other runs.
                requested_at = self._clock()
                self._update(
                    run_id,
                    status="waiting_for_approval",
                    stage="waiting_for_approval",
                    approval_status="pending",
                    approval_request=ApprovalRequest.model_validate(approval_request),
                    # The approval timeout starts now, when a human is first asked.
                    approval_requested_at=requested_at,
                    approval_expires_at=requested_at + self._approval_timeout,
                )
        finally:
            if self._store.get(run_id).status in FINISHED_STATUSES:
                await self._graph.checkpointer.adelete_thread(run_id)

    async def _drive_graph(
        self, run_id: str, graph_input: dict[str, Any] | Command
    ) -> dict[str, Any] | None:
        """Drive the graph on the run's own thread; return the approval payload if it pauses."""
        interrupted: dict[str, Any] | None = None
        async for mode, chunk in self._graph.astream(
            graph_input,
            config={"configurable": {"thread_id": run_id}},
            context=self._context,
            stream_mode=["tasks", "updates"],
        ):
            if mode == "tasks" and "input" in chunk and chunk["name"] in NODE_STAGES:
                stage = NODE_STAGES[chunk["name"]]
                # The claim already set the first stage; a retry re-enters executing.
                if self._store.get(run_id).stage != stage:
                    self._update(run_id, stage=stage)
            elif mode == "updates":
                for node, values in chunk.items():
                    if node == "__interrupt__":
                        interrupted = values[0].value
                        continue
                    results = {
                        key: value
                        for key, value in (values or {}).items()
                        if key in RESULT_FIELDS
                    }
                    self._update(run_id, **results)
        return interrupted

    def _update(self, run_id: str, **changes: Any) -> None:
        run = self._store.get(run_id)
        self._store.put(run.model_copy(update={**changes, "updated_at": self._clock()}))

    def _error(self, run_id: str, code: str, message: str) -> RunError:
        return RunError(code=code, message=message, stage=self._store.get(run_id).stage)

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
        result = self._store.get(run_id).execution_result
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
        run = self._store.get(run_id)
        decision = route_repair(
            run.critic_result, run.revision_count, run.execution_retry_count
        )
        if decision == "accept":
            if run.approval_status == "approved":
                self._update(run_id, status="completed", stage="completed")
                return
            # A verified solution completes only with a human's approval.
            logger.warning(
                "Run %s: solution not approved (%s)", run_id, run.approval_status
            )
            self._update(
                run_id,
                status="failed",
                stage="failed",
                error=RunError(
                    code="approval_rejected",
                    message=REJECTED_MESSAGE,
                    stage="waiting_for_approval",
                ),
            )
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
        """Keep storage bounded: drop the oldest finished runs beyond the retention limit.

        Finished runs have no checkpoint left, so this never touches a paused graph.
        """
        self._store.forget_finished(keep=self._max_retained_runs)
