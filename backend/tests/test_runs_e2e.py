"""Opt-in end-to-end check of the run lifecycle over HTTP, with slowed-down fakes.

Run with ASTRAAI_E2E_TESTS=1. Each step is delayed so polling can observe every stage.
"""

import asyncio
import os
import time

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.state import ExecutionResult, GeneratedCode
from tests.fake_llm import WORKFLOW_REPLIES, forced_tool, tool_call
from tests.fake_runs import manager_factory
from tests.fake_sandbox import FakeSandbox

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.getenv("ASTRAAI_E2E_TESTS") != "1",
        reason="set ASTRAAI_E2E_TESTS=1 to run the lifecycle end to end",
    ),
]

STEP_SECONDS = 0.25


async def slow_llm(request: httpx2.Request) -> httpx2.Response:
    tool = forced_tool(request)
    await asyncio.sleep(STEP_SECONDS)
    return tool_call(WORKFLOW_REPLIES[tool], name=tool)


class SlowSandbox(FakeSandbox):
    async def execute(self, generated_code: GeneratedCode) -> ExecutionResult:
        await asyncio.sleep(STEP_SECONDS)
        return await super().execute(generated_code)


def test_run_lifecycle_over_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.main.build_run_manager", manager_factory(slow_llm, SlowSandbox)
    )
    stages: list[str] = []
    approved = False

    with TestClient(app) as client:
        accepted = client.post(
            "/runs", json={"task": "Reverse a string.", "language": "python"}
        )
        assert accepted.status_code == 202
        run_id = accepted.json()["run_id"]

        deadline = time.monotonic() + 10
        while True:
            run = client.get(f"/runs/{run_id}").json()
            if not stages or stages[-1] != run["stage"]:
                stages.append(run["stage"])
            if run["status"] == "waiting_for_approval" and not approved:
                decision = {"decision": "approve"}
                response = client.post(f"/runs/{run_id}/approval", json=decision)
                assert response.status_code == 202
                approved = True
            if run["status"] in ("completed", "failed"):
                break
            assert time.monotonic() < deadline, f"stuck at {run['stage']}"
            time.sleep(0.02)

    assert run["status"] == "completed"
    # Resuming after approval is too quick to observe reliably when polling.
    assert [stage for stage in stages if stage not in ("queued", "resuming")] == [
        "analyzing",
        "generating_tests",
        "generating_code",
        "executing",
        "reviewing",
        "waiting_for_approval",
        "completed",
    ]
    assert run["approval_status"] == "approved"
    assert run["execution_result"]["status"] == "passed"
    assert run["generated_code"]["solution_code"]
