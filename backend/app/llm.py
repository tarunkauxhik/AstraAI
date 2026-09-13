import asyncio
import json
import logging

import httpx2
import openai
from pydantic import BaseModel, ValidationError

from app.config import Settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """The LLM request failed or returned output that does not match the schema."""


class LLMTimeoutError(LLMError):
    """The LLM did not answer within the configured timeout."""


class RetryableLLMError(LLMError):
    """Invalid structured output or a transient gateway failure: worth another attempt."""


def restore_coerced_strings(arguments: str, error: ValidationError) -> object | None:
    """Undo the gateway's coercion of string arguments; None if nothing to restore.

    MiniMax tool calling can turn an empty string into {} or null, and a numeric or
    boolean string such as "3" into the JSON value 3. Only fields the schema types as
    strings are touched, and only scalars are restored; nested values still fail.
    """
    restorations: dict[tuple[int | str, ...], str] = {}
    for detail in error.errors():
        if detail["type"] != "string_type":
            continue
        value = detail["input"]
        if value in ({}, None):
            restorations[detail["loc"]] = ""
        elif isinstance(value, int | float):
            restorations[detail["loc"]] = json.dumps(value)
    if not restorations:
        return None
    data = json.loads(arguments)
    for location, text in restorations.items():
        parent = data
        for key in location[:-1]:
            parent = parent[key]
        parent[location[-1]] = text
    return data


class LLMClient:
    """Structured-output calls to the configured OpenAI-compatible endpoint."""

    def __init__(
        self, settings: Settings, http_client: httpx2.AsyncClient | None = None
    ) -> None:
        self._model = settings.openai_model
        self._max_attempts = settings.llm_max_attempts
        self._retry_backoff_seconds = settings.llm_retry_backoff_seconds
        self._client = openai.AsyncOpenAI(
            base_url=str(settings.openai_base_url),
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
            http_client=http_client,
        )

    async def generate[T: BaseModel](
        self, instructions: str, prompt: str, schema: type[T]
    ) -> T:
        """Return `schema` validated from a forced tool call, with bounded retries.

        Invalid output and transient gateway failures (5xx, 408, 429, connection errors)
        get another attempt after a linear backoff. Timeouts and other 4xx errors do not.
        """
        attempt = 1
        while True:
            try:
                return await self._generate_once(instructions, prompt, schema)
            except RetryableLLMError as exc:
                if attempt >= self._max_attempts:
                    logger.warning(
                        "LLM call gave up after %d attempt(s): %s", attempt, exc
                    )
                    raise
                delay = self._retry_backoff_seconds * attempt
                logger.warning(
                    "LLM attempt %d/%d failed: %s; retrying in %.1fs",
                    attempt,
                    self._max_attempts,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                attempt += 1

    async def _generate_once[T: BaseModel](
        self, instructions: str, prompt: str, schema: type[T]
    ) -> T:
        """One forced tool call whose parameters are `schema`, validated.

        Tool calling, not `response_format`: the MiniMax gateway accepts but does not
        enforce `response_format`, and its `content` mixes reasoning with markdown.
        """
        tool_name = schema.__name__
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": prompt},
                ],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "description": f"Submit the {tool_name}.",
                            "parameters": schema.model_json_schema(),
                        },
                    }
                ],
                tool_choice={"type": "function", "function": {"name": tool_name}},
            )
        except openai.APITimeoutError as exc:
            logger.warning("LLM request timed out (model=%s)", self._model)
            raise LLMTimeoutError("LLM request timed out") from exc
        except openai.APIStatusError as exc:
            logger.warning(
                "LLM request failed: %s (status=%s, model=%s)",
                type(exc).__name__,
                exc.status_code,
                self._model,
            )
            transient = exc.status_code >= 500 or exc.status_code in (408, 429)
            error_class = RetryableLLMError if transient else LLMError
            raise error_class("LLM request failed") from exc
        except openai.APIError as exc:
            logger.warning(
                "LLM request failed: %s (model=%s)", type(exc).__name__, self._model
            )
            raise RetryableLLMError("LLM request failed") from exc

        choice = response.choices[0] if response.choices else None
        arguments = next(
            (
                call.function.arguments
                for call in (choice.message.tool_calls if choice else None) or []
                if call.type == "function" and call.function.name == tool_name
            ),
            None,
        )
        if arguments is None:
            logger.warning(
                "LLM did not call the %s tool (finish_reason=%s)",
                tool_name,
                choice.finish_reason if choice else None,
            )
            raise RetryableLLMError("LLM returned invalid structured output")
        try:
            return schema.model_validate_json(arguments)
        except ValidationError as exc:
            error = exc
        restored = restore_coerced_strings(arguments, error)
        if restored is not None:
            try:
                return schema.model_validate(restored)
            except ValidationError as exc:
                error = exc
        logger.warning(
            "LLM output failed %s validation: %d error(s), e.g. %s",
            tool_name,
            error.error_count(),
            [(detail["type"], detail["loc"]) for detail in error.errors()[:3]],
        )
        raise RetryableLLMError("LLM returned invalid structured output") from error

    async def close(self) -> None:
        await self._client.close()
