import asyncio
import json

import httpx2
from langgraph.runtime import Runtime

from app.nodes.analyze_task import analyze_task
from app.state import GraphContext, Requirements
from tests.fake_llm import (
    VALID_REQUIREMENTS,
    VALID_REQUIREMENTS_JSON,
    fake_llm,
    tool_call,
)
from tests.fake_sandbox import FakeSandbox


def test_analyze_task_returns_requirements_from_llm() -> None:
    prompts: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        prompts.append(json.loads(request.content)["messages"][1]["content"])
        return tool_call(VALID_REQUIREMENTS_JSON)

    runtime = Runtime(
        context=GraphContext(llm=fake_llm(handler), sandbox=FakeSandbox())
    )
    state = {"run_id": "run-1", "task": "Reverse a string.", "language": "python"}

    update = asyncio.run(analyze_task(state, runtime))

    assert update == {"requirements": Requirements(**VALID_REQUIREMENTS)}
    assert prompts == ["Language: python\n\nTask:\nReverse a string."]
