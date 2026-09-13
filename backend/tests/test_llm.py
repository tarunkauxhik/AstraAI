import asyncio
import json
from typing import Any

import httpx2
import pytest

from app.llm import LLMError, LLMTimeoutError
from app.state import Requirements
from tests.fake_llm import (
    MINIMAX_THINK_CONTENT,
    VALID_REQUIREMENTS,
    VALID_REQUIREMENTS_JSON,
    fake_llm,
    text_reply,
    timeout,
    tool_call,
)


def test_generate_forces_schema_tool_call() -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return tool_call(VALID_REQUIREMENTS_JSON)

    asyncio.run(fake_llm(handler).generate("Analyze.", "Reverse it.", Requirements))

    body = sent[0]
    assert body["model"] == "test-model"
    assert body["messages"] == [
        {"role": "system", "content": "Analyze."},
        {"role": "user", "content": "Reverse it."},
    ]
    assert body["tools"][0]["function"]["name"] == "Requirements"
    assert (
        body["tools"][0]["function"]["parameters"] == Requirements.model_json_schema()
    )
    assert body["tool_choice"] == {
        "type": "function",
        "function": {"name": "Requirements"},
    }
    assert "response_format" not in body


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(None, id="plain-openai-shape"),
        pytest.param(MINIMAX_THINK_CONTENT, id="live-minimax-shape-with-think"),
    ],
)
def test_generate_returns_validated_tool_arguments(content: str | None) -> None:
    llm = fake_llm(lambda request: tool_call(VALID_REQUIREMENTS_JSON, content=content))

    result = asyncio.run(llm.generate("Analyze.", "task", Requirements))

    assert result == Requirements(**VALID_REQUIREMENTS)


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(tool_call("not json"), id="malformed-json"),
        pytest.param(tool_call(VALID_REQUIREMENTS_JSON[:-5]), id="truncated-json"),
        pytest.param(
            tool_call(f"```json\n{VALID_REQUIREMENTS_JSON}\n```"), id="fenced-arguments"
        ),
        pytest.param(
            tool_call(json.dumps({**VALID_REQUIREMENTS, "edge_cases": "none"})),
            id="wrong-type",
        ),
        pytest.param(
            tool_call(json.dumps({**VALID_REQUIREMENTS, "code": "print()"})),
            id="extra-field",
        ),
        pytest.param(
            tool_call(json.dumps(Requirements.model_json_schema())),
            id="schema-echoed-instead-of-data",
        ),
        pytest.param(
            tool_call(VALID_REQUIREMENTS_JSON, name="other_tool"), id="wrong-tool"
        ),
        pytest.param(text_reply(VALID_REQUIREMENTS_JSON), id="json-content-no-tool"),
        pytest.param(
            text_reply(f"<think>Hmm.</think>\n```json\n{VALID_REQUIREMENTS_JSON}\n```"),
            id="think-and-fenced-content-no-tool",
        ),
    ],
)
def test_generate_rejects_invalid_structured_output(
    response: httpx2.Response, caplog: pytest.LogCaptureFixture
) -> None:
    llm = fake_llm(lambda request: response)

    with pytest.raises(LLMError, match="invalid structured output"):
        asyncio.run(llm.generate("Analyze.", "task", Requirements))

    assert "Reverse a string." not in caplog.text


def test_generate_reports_request_failure_without_leaking_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    llm = fake_llm(
        lambda request: httpx2.Response(500, json={"error": {"message": "down"}})
    )

    with pytest.raises(LLMError, match="request failed"):
        asyncio.run(llm.generate("Analyze.", "task", Requirements))

    assert "status=500" in caplog.text
    assert "test-key" not in caplog.text


def test_generate_reports_timeout() -> None:
    with pytest.raises(LLMTimeoutError):
        asyncio.run(fake_llm(timeout).generate("Analyze.", "task", Requirements))
