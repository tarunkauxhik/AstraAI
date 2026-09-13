from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE)

    openai_base_url: HttpUrl
    openai_api_key: SecretStr = Field(min_length=1)
    openai_model: str = Field(min_length=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
