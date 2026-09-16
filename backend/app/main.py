import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, StringConstraints

from app.config import get_settings
from app.graph import build_graph
from app.llm import LLMClient, LLMError, LLMTimeoutError
from app.sandbox.docker import DockerSandbox
from app.sandbox.executor import SandboxExecutor
from app.state import (
    ExecutionResult,
    GeneratedCode,
    GeneratedTests,
    GraphContext,
    Language,
    Requirements,
)

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str


class RunRequest(BaseModel):
    task: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)
    ]
    language: Language


class RunResponse(BaseModel):
    run_id: str
    requirements: Requirements
    generated_tests: GeneratedTests
    generated_code: GeneratedCode
    execution_result: ExecutionResult


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # One shared client and sandbox per process; fails fast on bad configuration.
    settings = get_settings()
    app.state.llm = LLMClient(settings)
    app.state.sandbox = DockerSandbox(settings)
    yield
    await app.state.llm.close()


app = FastAPI(title="AstraAi", lifespan=lifespan)
graph = build_graph()


def get_llm(request: Request) -> LLMClient:
    return request.app.state.llm


def get_sandbox(request: Request) -> SandboxExecutor:
    return request.app.state.sandbox


@app.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="astraai")


@app.post("/runs")
async def create_run(
    run: RunRequest,
    llm: Annotated[LLMClient, Depends(get_llm)],
    sandbox: Annotated[SandboxExecutor, Depends(get_sandbox)],
) -> RunResponse:
    run_id = str(uuid4())
    try:
        state = await graph.ainvoke(
            {"run_id": run_id, "task": run.task, "language": run.language},
            context=GraphContext(llm=llm, sandbox=sandbox),
        )
    except LLMError as exc:
        logger.warning("Run %s failed: %s", run_id, exc)
        status_code = 504 if isinstance(exc, LLMTimeoutError) else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return RunResponse(
        run_id=run_id,
        requirements=state["requirements"],
        generated_tests=state["generated_tests"],
        generated_code=state["generated_code"],
        execution_result=state["execution_result"],
    )
