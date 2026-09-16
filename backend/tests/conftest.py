import pytest

from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def llm_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dummy LLM settings; only `live` tests may read the real .env."""
    get_settings.cache_clear()
    if request.node.get_closest_marker("live"):
        return
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.delenv("LLM_MAX_ATTEMPTS", raising=False)
    monkeypatch.delenv("LLM_MAX_CONCURRENCY", raising=False)
    monkeypatch.setenv("LLM_RETRY_BACKOFF_SECONDS", "0")
