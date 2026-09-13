from collections.abc import Callable, Iterator
from typing import Any
from uuid import UUID

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app, get_llm
from tests.fake_llm import (
    VALID_GENERATED_TESTS,
    VALID_REQUIREMENTS,
    VALID_REQUIREMENTS_JSON,
    WORKFLOW_REPLIES,
    Reply,
    fake_llm,
    timeout,
)

VALID_RUN = {"task": "Reverse a string.", "language": "cpp"}


@pytest.fixture
def client_with_llm() -> Iterator[Callable[[Reply], TestClient]]:
    """TestClient whose runs use a fake LLM answering with the given reply."""

    def make(reply: Reply) -> TestClient:
        app.dependency_overrides[get_llm] = lambda: fake_llm(reply)
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


def test_health_reports_running() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "astraai"}


def test_startup_fails_without_llm_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY")

    with pytest.raises(ValidationError), TestClient(app):
        pass


def test_create_run_returns_requirements_and_generated_tests(
    client_with_llm: Callable[[Reply], TestClient],
) -> None:
    with client_with_llm(WORKFLOW_REPLIES) as client:
        response = client.post("/runs", json=VALID_RUN)

    assert response.status_code == 200
    body = response.json()
    assert UUID(body["run_id"])
    assert body["requirements"] == VALID_REQUIREMENTS
    assert body["generated_tests"] == VALID_GENERATED_TESTS


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
def test_create_run_rejects_invalid_request(
    client_with_llm: Callable[[Reply], TestClient], payload: dict[str, Any]
) -> None:
    with client_with_llm(WORKFLOW_REPLIES) as client:
        response = client.post("/runs", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("reply", "status_code", "detail"),
    [
        pytest.param(
            "not json",
            502,
            "LLM returned invalid structured output",
            id="invalid-requirements",
        ),
        pytest.param(
            {"Requirements": VALID_REQUIREMENTS_JSON, "GeneratedTests": "not json"},
            502,
            "LLM returned invalid structured output",
            id="invalid-generated-tests",
        ),
        pytest.param(
            lambda request: httpx2.Response(500),
            502,
            "LLM request failed",
            id="failure",
        ),
        pytest.param(timeout, 504, "LLM request timed out", id="timeout"),
    ],
)
def test_create_run_maps_llm_errors(
    client_with_llm: Callable[[Reply], TestClient],
    reply: Reply,
    status_code: int,
    detail: str,
) -> None:
    with client_with_llm(reply) as client:
        response = client.post("/runs", json=VALID_RUN)

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
