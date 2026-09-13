import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app


def test_health_reports_running() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "astraai"}


def test_startup_fails_without_llm_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY")

    with pytest.raises(ValidationError):
        with TestClient(app):
            pass
