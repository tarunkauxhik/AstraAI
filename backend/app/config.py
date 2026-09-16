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
    llm_max_concurrency: int = Field(default=2, ge=1, le=8)

    # Sandbox limits, deliberately conservative for a small shared VPS.
    sandbox_python_image: str = Field(default="python:3.12-slim", min_length=1)
    sandbox_cpp_image: str = Field(default="gcc:13", min_length=1)
    sandbox_user: str = Field(default="65534:65534", min_length=1)
    sandbox_timeout_seconds: float = Field(default=30, gt=0, le=300)
    sandbox_cpu_limit: float = Field(default=1.0, gt=0, le=4)
    sandbox_memory_mb: int = Field(default=512, ge=64, le=2048)
    sandbox_pids_limit: int = Field(default=64, ge=8, le=512)
    sandbox_scratch_mb: int = Field(default=64, ge=8, le=512)
    sandbox_max_output_bytes: int = Field(default=64_000, ge=1_000, le=1_000_000)
    sandbox_max_concurrency: int = Field(default=1, ge=1, le=4)

    # Run lifecycle. One full agent run at a time: each one already holds LLM calls and a
    # sandbox, and the target is a small VPS.
    run_max_active_runs: int = Field(default=1, ge=1, le=4)
    run_max_queued_runs: int = Field(default=10, ge=1, le=100)
    run_max_retained_runs: int = Field(default=100, ge=10, le=1000)
    # Caps the whole graph run; per-LLM-call and sandbox timeouts still apply inside it.
    run_timeout_seconds: float = Field(default=300, ge=30, le=3600)
    # How long a verified solution waits for a human decision before the run expires.
    # Separate from run_timeout_seconds, which counts active work only.
    approval_timeout_seconds: float = Field(default=600, ge=5, le=86_400)


@lru_cache
def get_settings() -> Settings:
    return Settings()
