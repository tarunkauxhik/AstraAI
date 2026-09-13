from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    # hide_input_in_errors keeps raw values, such as the API key, out of validation errors.
    model_config = SettingsConfigDict(env_file=ENV_FILE, hide_input_in_errors=True)

    openai_base_url: HttpUrl
    openai_api_key: SecretStr = Field(min_length=1)
    openai_model: str = Field(min_length=1)
    llm_timeout_seconds: float = Field(default=120, gt=0)
    llm_max_attempts: int = Field(default=2, ge=1, le=5)
    llm_retry_backoff_seconds: float = Field(default=1.0, ge=0, le=30)


@lru_cache
def get_settings() -> Settings:
    return Settings()
