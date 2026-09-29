from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, status
from pydantic import BaseModel, StringConstraints

from app.config import Settings, get_settings
from app.graph import build_checkpointer, build_graph
from app.llm import LLMClient
from app.runs import (
    ApprovalConflictError,
    ApprovalExpiredError,
    QueueFullError,
    Run,
    RunManager,
    RunManagerStoppedError,
    RunNotFoundError,
    RunStatus,
)
from app.sandbox.docker import DockerSandbox
from app.state import ApprovalDecision, GraphContext, Language
from app.store import RunStore


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str


class RunRequest(BaseModel):
    task: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
    ]
    language: Language


class RunAccepted(BaseModel):
    run_id: str
    status: RunStatus


class ApprovalExtended(BaseModel):
    run_id: str
    approval_expires_at: datetime


def build_run_manager(settings: Settings, context: GraphContext) -> RunManager:
    """The run manager on durable storage in settings.data_dir; it closes both on stop."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return RunManager(
        build_graph(build_checkpointer(settings.data_dir / "checkpoints.sqlite3")),
        context,
        RunStore(settings.data_dir / "runs.sqlite3"),
        max_active_runs=settings.run_max_active_runs,
        max_queued_runs=settings.run_max_queued_runs,
        max_retained_runs=settings.run_max_retained_runs,
        run_timeout_seconds=settings.run_timeout_seconds,
        approval_timeout_seconds=settings.approval_timeout_seconds,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # One LLM client, sandbox and run manager per process; fails fast on bad configuration.
    settings = get_settings()
    llm = LLMClient(settings)
    sandbox = DockerSandbox(settings)
    runs = build_run_manager(settings, GraphContext(llm=llm, sandbox=sandbox))
    app.state.runs = runs
    # Before recovery: an execution interrupted by a crash must not keep running.
    await sandbox.remove_leftovers()
    await runs.start()
    try:
        yield
    finally:
        await runs.stop()
        await llm.close()


app = FastAPI(title="AstraAi", lifespan=lifespan)


def get_run_manager(request: Request) -> RunManager:
    return request.app.state.runs


@app.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="astraai")


def queue_full() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many runs are waiting. Try again shortly.",
        headers={"Retry-After": "30"},
    )


def shutting_down() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="The service is shutting down. Try again shortly.",
    )


def run_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")


def approval_expired() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="The approval request has expired.",
    )


def not_waiting() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="The run is not waiting for approval.",
    )


@app.post("/runs", status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    run: RunRequest, runs: Annotated[RunManager, Depends(get_run_manager)]
) -> RunAccepted:
    try:
        created = runs.submit(run.task, run.language)
    except QueueFullError as exc:
        raise queue_full() from exc
    except RunManagerStoppedError as exc:
        raise shutting_down() from exc
    return RunAccepted(run_id=created.run_id, status=created.status)


@app.post("/runs/{run_id}/approval", status_code=status.HTTP_202_ACCEPTED)
async def decide_approval(
    run_id: str,
    body: ApprovalDecision,
    runs: Annotated[RunManager, Depends(get_run_manager)],
) -> RunAccepted:
    """Approve a waiting run, which resumes on the same thread, or reject it."""
    try:
        decided = await runs.resolve_approval(run_id, body.decision)
    except RunNotFoundError as exc:
        raise run_not_found() from exc
    except ApprovalExpiredError as exc:
        raise approval_expired() from exc
    except ApprovalConflictError as exc:
        raise not_waiting() from exc
    except QueueFullError as exc:
        raise queue_full() from exc
    except RunManagerStoppedError as exc:
        raise shutting_down() from exc
    return RunAccepted(run_id=decided.run_id, status=decided.status)


@app.post("/runs/{run_id}/approval/extend")
async def extend_approval(
    run_id: str, runs: Annotated[RunManager, Depends(get_run_manager)]
) -> ApprovalExtended:
    """Restart the approval window from now, so a slow review never runs out unwarned."""
    try:
        extended = await runs.extend_approval(run_id)
    except RunNotFoundError as exc:
        raise run_not_found() from exc
    except ApprovalExpiredError as exc:
        raise approval_expired() from exc
    except ApprovalConflictError as exc:
        raise not_waiting() from exc
    except RunManagerStoppedError as exc:
        raise shutting_down() from exc
    return ApprovalExtended.model_validate(extended, from_attributes=True)


@app.get("/runs/{run_id}")
async def get_run(
    run_id: str, runs: Annotated[RunManager, Depends(get_run_manager)]
) -> Run:
    found = runs.get(run_id)
    if found is None:
        raise run_not_found()
    return found
