import pytest

from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dummy LLM settings; tests never read a developer's real .env."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    get_settings.cache_clear()
