from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, status
from pydantic import BaseModel, StringConstraints

from app.config import Settings, get_settings
from app.graph import build_graph
from app.llm import LLMClient
from app.runs import (
    QueueFullError,
    Run,
    RunManager,
    RunManagerStoppedError,
    RunStatus,
)
from app.sandbox.docker import DockerSandbox
from app.state import GraphContext, Language


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


def build_run_manager(settings: Settings, context: GraphContext) -> RunManager:
    return RunManager(
        build_graph(),
        context,
        max_active_runs=settings.run_max_active_runs,
        max_queued_runs=settings.run_max_queued_runs,
        max_retained_runs=settings.run_max_retained_runs,
        run_timeout_seconds=settings.run_timeout_seconds,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # One LLM client, sandbox and run manager per process; fails fast on bad configuration.
    settings = get_settings()
    llm = LLMClient(settings)
    runs = build_run_manager(
        settings, GraphContext(llm=llm, sandbox=DockerSandbox(settings))
    )
    app.state.runs = runs
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


@app.post("/runs", status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    run: RunRequest, runs: Annotated[RunManager, Depends(get_run_manager)]
) -> RunAccepted:
    try:
        created = runs.submit(run.task, run.language)
    except QueueFullError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many runs are waiting. Try again shortly.",
            headers={"Retry-After": "30"},
        ) from exc
    except RunManagerStoppedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The service is shutting down. Try again shortly.",
        ) from exc
    return RunAccepted(run_id=created.run_id, status=created.status)


@app.get("/runs/{run_id}")
async def get_run(
    run_id: str, runs: Annotated[RunManager, Depends(get_run_manager)]
) -> Run:
    found = runs.get(run_id)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run not found."
        )
    return found
