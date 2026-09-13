from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from app.config import get_settings


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_settings()  # Fail fast on missing or invalid configuration.
    yield


app = FastAPI(title="AstraAi", lifespan=lifespan)


@app.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="astraai")
