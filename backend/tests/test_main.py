import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.sandbox.executor import SandboxExecutor
from tests.fake_llm import (
    VALID_CRITIC_RESULT,
    VALID_GENERATED_TESTS,
    VALID_PYTHON_CODE,
    VALID_REQUIREMENTS,
    WORKFLOW_REPLIES,
    Reply,
)
from tests.fake_runs import hold_forever, manager_factory, poll
from tests.fake_sandbox import PASSED, FakeSandbox

# Python: the workflow fixtures generate Python code, and the sandbox node checks the match.
VALID_RUN = {"task": "Reverse a string.", "language": "python"}
Api = Callable[..., TestClient]


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Api:
    """TestClient whose run manager uses fake LLM and sandbox components."""

    def make(
        reply: Reply = WORKFLOW_REPLIES,
        sandbox: Callable[[], SandboxExecutor] = FakeSandbox,
        max_queued_runs: int = 10,
    ) -> TestClient:
        factory = manager_factory(reply, sandbox, max_queued_runs=max_queued_runs)
        monkeypatch.setattr("app.main.build_run_manager", factory)
        return TestClient(app)

    return make


def running(run: dict[str, Any]) -> bool:
    return run["status"] == "running"


def finished(run: dict[str, Any]) -> bool:
    return run["status"] in ("completed", "failed")


def test_health_reports_running() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "astraai"}


def test_startup_fails_without_llm_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY")

    with pytest.raises(ValidationError), TestClient(app):
        pass


def test_post_returns_202_without_waiting_for_the_workflow(api: Api) -> None:
    with api(hold_forever) as client:
        started = time.monotonic()
        response = client.post("/runs", json=VALID_RUN)
        elapsed = time.monotonic() - started

        assert response.status_code == 202
        body = response.json()
        assert body == {"run_id": body["run_id"], "status": "queued"}
        assert UUID(body["run_id"])
        assert elapsed < 1.0

        run = poll(client, body["run_id"], running)
        assert run["stage"] == "analyzing"
        assert run["requirements"] is None


def test_get_queued_run_while_another_runs(api: Api) -> None:
    with api(hold_forever) as client:
        first = client.post("/runs", json=VALID_RUN).json()["run_id"]
        poll(client, first, running)

        second = client.post("/runs", json=VALID_RUN).json()["run_id"]
        run = client.get(f"/runs/{second}").json()

    assert (run["status"], run["stage"]) == ("queued", "queued")
    assert run["generated_code"] is None


def test_completed_run_exposes_every_result(api: Api) -> None:
    with api() as client:
        run_id = client.post("/runs", json=VALID_RUN).json()["run_id"]
        run = poll(client, run_id, finished)

    assert (run["status"], run["stage"], run["error"]) == (
        "completed",
        "completed",
        None,
    )
    assert (run["task"], run["language"]) == (VALID_RUN["task"], "python")
    assert run["requirements"] == VALID_REQUIREMENTS
    assert run["generated_tests"] == VALID_GENERATED_TESTS
    assert run["generated_code"] == VALID_PYTHON_CODE
    assert run["execution_result"] == PASSED.model_dump()
    assert run["critic_result"] == VALID_CRITIC_RESULT
    assert (run["revision_count"], run["execution_retry_count"]) == (0, 0)


def test_failed_run_keeps_earlier_results_and_a_safe_error(api: Api) -> None:
    with api({**WORKFLOW_REPLIES, "GeneratedTests": "not json"}) as client:
        run_id = client.post("/runs", json=VALID_RUN).json()["run_id"]
        run = poll(client, run_id, finished)

    assert (run["status"], run["stage"]) == ("failed", "failed")
    assert run["error"] == {
        "code": "llm_failed",
        "message": "The language model request failed or returned unusable output.",
        "stage": "generating_tests",
    }
    assert run["requirements"] == VALID_REQUIREMENTS
    assert run["generated_tests"] is None


def test_unexpected_failure_exposes_no_internals(api: Api) -> None:
    def exploding_sandbox() -> FakeSandbox:
        return FakeSandbox(RuntimeError("Traceback: /var/run/docker.sock denied"))

    with api(sandbox=exploding_sandbox) as client:
        run_id = client.post("/runs", json=VALID_RUN).json()["run_id"]
        poll(client, run_id, finished)
        response = client.get(f"/runs/{run_id}")

    run = response.json()
    assert run["error"]["code"] == "internal_error"
    assert run["error"]["stage"] == "executing"
    for internal in ("Traceback", "docker.sock", "RuntimeError"):
        assert internal not in response.text


def test_unknown_run_is_404(api: Api) -> None:
    with api() as client:
        response = client.get("/runs/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found."}


def test_full_queue_returns_429(api: Api) -> None:
    with api(hold_forever, max_queued_runs=1) as client:
        active = client.post("/runs", json=VALID_RUN).json()["run_id"]
        poll(client, active, running)
        waiting = client.post("/runs", json=VALID_RUN)
        rejected = client.post("/runs", json=VALID_RUN)

    assert waiting.status_code == 202
    assert rejected.status_code == 429
    assert rejected.headers["retry-after"] == "30"
    assert rejected.json() == {
        "detail": "Too many runs are waiting. Try again shortly."
    }


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"language": "cpp"}, id="missing-task"),
        pytest.param({"task": "", "language": "cpp"}, id="empty-task"),
        pytest.param({"task": "   \n", "language": "cpp"}, id="blank-task"),
        pytest.param({"task": "x" * 20_001, "language": "cpp"}, id="task-too-long"),
        pytest.param({"task": "Reverse a string."}, id="missing-language"),
        pytest.param(
            {"task": "Reverse a string.", "language": "cobol"},
            id="unsupported-language",
        ),
    ],
)
def test_invalid_request_is_422(api: Api, payload: dict[str, Any]) -> None:
    with api() as client:
        response = client.post("/runs", json=payload)

    assert response.status_code == 422


def test_post_during_shutdown_returns_503(api: Api) -> None:
    with api() as client:
        client.portal.call(app.state.runs.stop)
        response = client.post("/runs", json=VALID_RUN)

    assert response.status_code == 503
    assert response.json() == {
        "detail": "The service is shutting down. Try again shortly."
    }
