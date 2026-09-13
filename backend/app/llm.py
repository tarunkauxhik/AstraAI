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


class LLMClient:
    """Structured-output calls to the configured OpenAI-compatible endpoint."""

    def __init__(
        self, settings: Settings, http_client: httpx2.AsyncClient | None = None
    ) -> None:
        self._model = settings.openai_model
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
        """Force a tool call whose parameters are `schema` and validate its arguments.

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
        except openai.APIError as exc:
            status = getattr(exc, "status_code", None)
            logger.warning(
                "LLM request failed: %s (status=%s, model=%s)",
                type(exc).__name__,
                status,
                self._model,
            )
            raise LLMError("LLM request failed") from exc

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
            raise LLMError("LLM returned invalid structured output")
        try:
            return schema.model_validate_json(arguments)
        except ValidationError as exc:
            logger.warning(
                "LLM output failed %s validation: %s",
                tool_name,
                exc.errors(include_input=False, include_url=False),
            )
            raise LLMError("LLM returned invalid structured output") from exc

    async def close(self) -> None:
        await self._client.close()
