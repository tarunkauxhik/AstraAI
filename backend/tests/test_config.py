from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings


def test_settings_load_from_environment() -> None:
    settings = get_settings()

    assert str(settings.openai_base_url) == "http://llm.test/v1"
    assert settings.openai_api_key.get_secret_value() == "test-key"
    assert settings.openai_model == "test-model"
    assert "test-key" not in repr(settings)


def test_settings_load_from_dotenv_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"):
        monkeypatch.delenv(name)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENAI_BASE_URL=https://llm.example/v1\nOPENAI_API_KEY=dotenv-key\nOPENAI_MODEL=minimax\n"
    )

    settings = Settings(_env_file=env_file)

    assert settings.openai_model == "minimax"
    assert settings.openai_api_key.get_secret_value() == "dotenv-key"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("OPENAI_BASE_URL", "not-a-url"),
        ("OPENAI_API_KEY", ""),
        ("OPENAI_MODEL", ""),
        ("LLM_TIMEOUT_SECONDS", "0"),
        ("LLM_MAX_ATTEMPTS", "0"),
        ("LLM_MAX_ATTEMPTS", "6"),
        ("LLM_RETRY_BACKOFF_SECONDS", "-1"),
        ("LLM_MAX_CONCURRENCY", "0"),
        ("LLM_MAX_CONCURRENCY", "9"),
    ],
)
def test_settings_reject_invalid_values(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings()


def test_llm_reliability_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_RETRY_BACKOFF_SECONDS")

    settings = Settings()

    assert settings.llm_max_attempts == 2
    assert settings.llm_retry_backoff_seconds == 1.0
    assert settings.llm_max_concurrency == 2


def test_settings_errors_do_not_echo_the_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_MODEL")

    with pytest.raises(ValidationError) as error:
        Settings()

    assert "test-key" not in str(error.value)
