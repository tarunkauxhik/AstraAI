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
from tests.fake_runs import Clock, hold_forever, manager_factory, poll
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
        **options: Any,
    ) -> TestClient:
        factory = manager_factory(
            reply, sandbox, max_queued_runs=max_queued_runs, **options
        )
        monkeypatch.setattr("app.main.build_run_manager", factory)
        return TestClient(app)

    return make


def running(run: dict[str, Any]) -> bool:
    return run["status"] == "running"


def finished(run: dict[str, Any]) -> bool:
    return run["status"] in ("completed", "failed", "expired")


def waiting(run: dict[str, Any]) -> bool:
    return run["status"] == "waiting_for_approval"


def paused_run(client: TestClient) -> str:
    """Start a run and wait until it asks for approval."""
    run_id = client.post("/runs", json=VALID_RUN).json()["run_id"]
    poll(client, run_id, waiting)
    return run_id


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
        run_id = paused_run(client)
        approval = client.post(f"/runs/{run_id}/approval", json={"decision": "approve"})
        run = poll(client, run_id, finished)

    assert approval.status_code == 202
    assert approval.json() == {"run_id": run_id, "status": "running"}

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
    assert (run["approval_status"], run["approval_required"]) == ("approved", False)


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


def test_a_run_waiting_for_approval_shows_what_to_decide(api: Api) -> None:
    with api() as client:
        run_id = paused_run(client)
        run = client.get(f"/runs/{run_id}").json()

    assert (run["status"], run["stage"], run["error"]) == (
        "waiting_for_approval",
        "waiting_for_approval",
        None,
    )
    assert (run["approval_status"], run["approval_required"]) == ("pending", True)
    request = run["approval_request"]
    assert (request["run_id"], request["execution_status"]) == (run_id, "passed")
    assert request["approval_means"]
    assert run["generated_code"] == VALID_PYTHON_CODE
    # Checkpoint internals are never exposed.
    for internal in ("thread_id", "checkpoint", "__interrupt__", "configurable"):
        assert internal not in str(run)


def test_rejection_over_http_fails_the_run(api: Api) -> None:
    with api() as client:
        run_id = paused_run(client)
        response = client.post(f"/runs/{run_id}/approval", json={"decision": "reject"})
        run = poll(client, run_id, finished)

    assert response.status_code == 202
    assert (run["status"], run["approval_status"]) == ("failed", "rejected")
    assert run["error"] == {
        "code": "approval_rejected",
        "message": "A human rejected the verified solution.",
        "stage": "waiting_for_approval",
    }


def test_duplicate_approval_is_a_conflict(api: Api) -> None:
    with api() as client:
        run_id = paused_run(client)
        first = client.post(f"/runs/{run_id}/approval", json={"decision": "approve"})
        second = client.post(f"/runs/{run_id}/approval", json={"decision": "reject"})
        run = poll(client, run_id, finished)
        after = client.post(f"/runs/{run_id}/approval", json={"decision": "approve"})

    assert (first.status_code, second.status_code, after.status_code) == (
        202,
        409,
        409,
    )
    assert second.json() == {"detail": "The run is not waiting for approval."}
    assert (run["status"], run["approval_status"]) == ("completed", "approved")


def test_approving_a_run_that_is_not_waiting_is_a_conflict(api: Api) -> None:
    with api(hold_forever) as client:
        run_id = client.post("/runs", json=VALID_RUN).json()["run_id"]
        poll(client, run_id, running)
        response = client.post(f"/runs/{run_id}/approval", json={"decision": "approve"})

    assert response.status_code == 409


def test_approving_an_unknown_run_is_404(api: Api) -> None:
    with api() as client:
        response = client.post(
            "/runs/does-not-exist/approval", json={"decision": "approve"}
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found."}


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"decision": "yes"}, id="unknown-decision"),
        pytest.param({"decision": "Approve"}, id="wrong-case"),
        pytest.param({"decision": True}, id="boolean"),
        pytest.param({}, id="missing-decision"),
        pytest.param({"decision": "approve", "note": "lgtm"}, id="extra-field"),
        pytest.param("approve", id="bare-string"),
        pytest.param(None, id="null"),
    ],
)
def test_malformed_approval_is_422_and_the_run_keeps_waiting(
    api: Api, body: object
) -> None:
    with api() as client:
        run_id = paused_run(client)
        response = client.post(f"/runs/{run_id}/approval", json=body)
        run = client.get(f"/runs/{run_id}").json()

    assert response.status_code == 422
    assert (run["status"], run["approval_status"]) == (
        "waiting_for_approval",
        "pending",
    )


def test_non_json_approval_is_422(api: Api) -> None:
    with api() as client:
        run_id = paused_run(client)
        response = client.post(
            f"/runs/{run_id}/approval",
            content=b"approve",
            headers={"content-type": "application/json"},
        )
        run = client.get(f"/runs/{run_id}").json()

    assert response.status_code == 422
    assert run["status"] == "waiting_for_approval"


def test_approval_during_shutdown_returns_503(api: Api) -> None:
    with api() as client:
        run_id = paused_run(client)
        client.portal.call(app.state.runs.stop)
        response = client.post(f"/runs/{run_id}/approval", json={"decision": "approve"})

    assert response.status_code == 503


def test_an_expired_approval_is_409_and_shows_as_expired(api: Api) -> None:
    clock = Clock()
    with api(clock=clock) as client:
        run_id = paused_run(client)
        clock.advance(600)
        responses = [
            client.post(f"/runs/{run_id}/approval", json={"decision": decision})
            for decision in ("approve", "reject")
        ]
        run = client.get(f"/runs/{run_id}").json()

    for response in responses:
        assert response.status_code == 409
        assert response.json() == {"detail": "The approval request has expired."}
    # Expiry is not a failure: the verified solution and its evidence are still there.
    assert (run["status"], run["stage"], run["error"]) == ("expired", "expired", None)
    assert (run["approval_status"], run["approval_required"]) == ("expired", False)
    assert run["approval_expires_at"] is not None
    assert run["execution_result"]["status"] == "passed"
    assert run["generated_code"] is not None


def test_more_time_restarts_the_approval_window(api: Api) -> None:
    clock = Clock()
    with api(clock=clock) as client:
        run_id = paused_run(client)
        before = client.get(f"/runs/{run_id}").json()
        clock.advance(300)
        response = client.post(f"/runs/{run_id}/approval/extend")
        after = client.get(f"/runs/{run_id}").json()

    assert response.status_code == 200
    assert response.json() == {
        "run_id": run_id,
        "approval_expires_at": after["approval_expires_at"],
    }
    assert after["approval_expires_at"] > before["approval_expires_at"]
    assert after["approval_requested_at"] == before["approval_requested_at"]
    assert after["status"] == "waiting_for_approval"


def test_more_time_is_409_once_expired_or_decided_and_404_when_unknown(
    api: Api,
) -> None:
    clock = Clock()
    with api(clock=clock) as client:
        expiring = paused_run(client)
        decided = paused_run(client)
        client.post(f"/runs/{decided}/approval", json={"decision": "reject"})
        clock.advance(600)
        expired = client.post(f"/runs/{expiring}/approval/extend")
        not_waiting = client.post(f"/runs/{decided}/approval/extend")
        unknown = client.post("/runs/no-such-run/approval/extend")

    assert (expired.status_code, expired.json()) == (
        409,
        {"detail": "The approval request has expired."},
    )
    assert (not_waiting.status_code, not_waiting.json()) == (
        409,
        {"detail": "The run is not waiting for approval."},
    )
    assert unknown.status_code == 404


def test_a_rejected_run_cannot_be_decided_again(api: Api) -> None:
    with api() as client:
        run_id = paused_run(client)
        rejected = client.post(f"/runs/{run_id}/approval", json={"decision": "reject"})
        again = [
            client.post(f"/runs/{run_id}/approval", json={"decision": decision})
            for decision in ("approve", "reject")
        ]

    assert (rejected.status_code, rejected.json()) == (
        202,
        {"run_id": run_id, "status": "failed"},
    )
    assert [response.status_code for response in again] == [409, 409]
    assert again[0].json() == {"detail": "The run is not waiting for approval."}
