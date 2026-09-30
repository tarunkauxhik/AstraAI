from pathlib import Path

import pytest

from app.config import Settings, get_settings
from app.sandbox.docker import DockerSandbox


class StartupSandbox(DockerSandbox):
    """The app's sandbox, minus removing leftover containers from the real Docker daemon."""

    async def remove_leftovers(self) -> None:
        pass


@pytest.fixture(autouse=True)
def app_startup(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Keep app startup away from real data and, outside `docker` tests, real containers."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    # A token in the developer's environment must never reach a test's GitHub requests.
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    if not request.node.get_closest_marker("docker"):
        monkeypatch.setattr("app.main.DockerSandbox", StartupSandbox)


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
    for name in (
        "RUN_MAX_ACTIVE_RUNS",
        "RUN_MAX_QUEUED_RUNS",
        "RUN_MAX_RETAINED_RUNS",
        "RUN_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_RETRY_BACKOFF_SECONDS", "0")
