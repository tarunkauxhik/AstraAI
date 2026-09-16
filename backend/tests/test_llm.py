import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from app.llm import LLMClient, LLMError, LLMTimeoutError
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

Step = httpx2.Response | Callable[[httpx2.Request], httpx2.Response]
REQUIREMENTS = Requirements(**VALID_REQUIREMENTS)


def scripted(*steps: Step) -> tuple[LLMClient, list[httpx2.Request]]:
    """LLMClient answering request n with steps[n]; also returns the requests made."""
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        step = steps[len(requests) - 1]
        return step(request) if callable(step) else step

    return fake_llm(handler), requests


def generate(llm: LLMClient) -> Requirements:
    return asyncio.run(llm.generate("Analyze.", "task", Requirements))


def valid() -> httpx2.Response:
    return tool_call(VALID_REQUIREMENTS_JSON)


def connection_error(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("connection refused", request=request)


def test_generate_forces_schema_tool_call() -> None:
    sent: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return valid()

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
    llm, requests = scripted(tool_call(VALID_REQUIREMENTS_JSON, content=content))

    assert generate(llm) == REQUIREMENTS
    assert len(requests) == 1


def test_generate_restores_strings_the_gateway_coerced() -> None:
    arguments = json.dumps(
        {
            **VALID_REQUIREMENTS,
            "problem_summary": 3,
            "expected_input": {},
            "expected_output": None,
            "edge_cases": [True, 2.5],
        }
    )

    result = generate(fake_llm(arguments))

    assert (result.problem_summary, result.expected_input, result.expected_output) == (
        "3",
        "",
        "",
    )
    assert result.edge_cases == ["true", "2.5"]


INVALID_OUTPUTS = [
    pytest.param(
        lambda: tool_call(
            json.dumps({**VALID_REQUIREMENTS, "expected_input": {"a": 1}})
        ),
        id="non-empty-object-for-string",
    ),
    pytest.param(
        lambda: tool_call(json.dumps({**VALID_REQUIREMENTS, "edge_cases": None})),
        id="null-for-list",
    ),
    pytest.param(
        lambda: tool_call(json.dumps({**VALID_REQUIREMENTS, "expected_input": [1, 2]})),
        id="list-for-string",
    ),
    pytest.param(
        lambda: tool_call(
            json.dumps({**VALID_REQUIREMENTS, "expected_input": {}, "code": "x"})
        ),
        id="empty-object-plus-extra-field",
    ),
    pytest.param(lambda: tool_call("not json"), id="malformed-json"),
    pytest.param(lambda: tool_call(VALID_REQUIREMENTS_JSON[:-5]), id="truncated-json"),
    pytest.param(
        lambda: tool_call(f"```json\n{VALID_REQUIREMENTS_JSON}\n```"),
        id="fenced-arguments",
    ),
    pytest.param(
        lambda: tool_call(json.dumps({**VALID_REQUIREMENTS, "edge_cases": "none"})),
        id="wrong-type",
    ),
    pytest.param(
        lambda: tool_call(json.dumps({**VALID_REQUIREMENTS, "code": "print()"})),
        id="extra-field",
    ),
    pytest.param(
        lambda: tool_call(json.dumps(Requirements.model_json_schema())),
        id="schema-echoed-instead-of-data",
    ),
    pytest.param(
        lambda: tool_call(VALID_REQUIREMENTS_JSON, name="other_tool"), id="wrong-tool"
    ),
    pytest.param(lambda: text_reply(VALID_REQUIREMENTS_JSON), id="missing-tool-call"),
    pytest.param(
        lambda: text_reply(
            f"<think>Hmm.</think>\n```json\n{VALID_REQUIREMENTS_JSON}\n```"
        ),
        id="think-and-fenced-content-no-tool",
    ),
]


@pytest.mark.parametrize("invalid", INVALID_OUTPUTS)
def test_generate_rejects_invalid_output_on_every_attempt(
    invalid: Callable[[], httpx2.Response],
) -> None:
    llm, requests = scripted(invalid(), invalid())

    with pytest.raises(LLMError, match="invalid structured output"):
        generate(llm)

    assert len(requests) == 2


@pytest.mark.parametrize(
    "first_failure",
    [
        *INVALID_OUTPUTS,
        pytest.param(lambda: httpx2.Response(500), id="http-500"),
        pytest.param(lambda: httpx2.Response(503), id="http-503"),
        pytest.param(lambda: httpx2.Response(408), id="http-408"),
        pytest.param(lambda: httpx2.Response(429), id="http-429"),
        pytest.param(lambda: connection_error, id="connection-error"),
    ],
)
def test_generate_retries_once_then_succeeds(
    first_failure: Callable[[], Step], caplog: pytest.LogCaptureFixture
) -> None:
    llm, requests = scripted(first_failure(), valid())

    assert generate(llm) == REQUIREMENTS
    assert len(requests) == 2
    assert "LLM attempt 1/2 failed" in caplog.text


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        pytest.param(
            lambda: tool_call("not json"), "invalid structured output", id="output"
        ),
        pytest.param(lambda: httpx2.Response(502), "request failed", id="http-502"),
        pytest.param(
            lambda: httpx2.Response(429, headers={"retry-after": "0"}),
            "request failed",
            id="http-429",
        ),
    ],
)
def test_generate_gives_up_after_max_attempts(
    failure: Callable[[], httpx2.Response],
    message: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    llm, requests = scripted(failure(), failure(), valid())

    with pytest.raises(LLMError, match=message):
        generate(llm)

    assert len(requests) == 2
    assert "LLM call gave up after 2 attempt(s)" in caplog.text


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_generate_does_not_retry_non_transient_client_errors(status: int) -> None:
    llm, requests = scripted(httpx2.Response(status), valid())

    with pytest.raises(LLMError, match="request failed") as error:
        generate(llm)

    assert type(error.value) is LLMError
    assert len(requests) == 1


def test_generate_does_not_retry_timeouts() -> None:
    llm, requests = scripted(timeout, valid())

    with pytest.raises(LLMTimeoutError):
        generate(llm)

    assert len(requests) == 1


def test_generate_stops_when_the_retry_times_out() -> None:
    llm, requests = scripted(tool_call("not json"), timeout, valid())

    with pytest.raises(LLMTimeoutError):
        generate(llm)

    assert len(requests) == 2


def test_generate_follows_configured_attempts_and_linear_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("LLM_RETRY_BACKOFF_SECONDS", "0.5")
    delays: list[float] = []

    async def record_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr("app.llm.asyncio.sleep", record_sleep)
    llm, requests = scripted(tool_call("not json"), httpx2.Response(500), valid())

    assert generate(llm) == REQUIREMENTS
    assert len(requests) == 3
    assert delays == [0.5, 1.0]


@pytest.mark.parametrize(
    ("retry_after", "expected_delay"),
    [
        pytest.param("2", 2.0, id="seconds"),
        pytest.param("0.5", 0.5, id="fractional-seconds"),
        pytest.param(None, 0.25, id="missing-uses-backoff"),
        pytest.param("120", 0.25, id="too-long-uses-backoff"),
        pytest.param("Wed, 21 Oct 2026 07:28:00 GMT", 0.25, id="date-uses-backoff"),
        pytest.param("soon", 0.25, id="unparsable-uses-backoff"),
    ],
)
def test_generate_waits_for_retry_after_on_429(
    monkeypatch: pytest.MonkeyPatch, retry_after: str | None, expected_delay: float
) -> None:
    monkeypatch.setenv("LLM_RETRY_BACKOFF_SECONDS", "0.25")
    delays: list[float] = []

    async def record_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr("app.llm.asyncio.sleep", record_sleep)
    headers = {} if retry_after is None else {"retry-after": retry_after}
    llm, requests = scripted(httpx2.Response(429, headers=headers), valid())

    assert generate(llm) == REQUIREMENTS
    assert len(requests) == 2
    assert delays == [expected_delay]


def test_generate_ignores_retry_after_on_other_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_RETRY_BACKOFF_SECONDS", "0.25")
    delays: list[float] = []

    async def record_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr("app.llm.asyncio.sleep", record_sleep)
    llm, _ = scripted(httpx2.Response(503, headers={"retry-after": "5"}), valid())

    assert generate(llm) == REQUIREMENTS
    assert delays == [0.25]


def test_generate_never_exceeds_the_concurrency_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_MAX_CONCURRENCY", "3")
    in_flight = 0
    peak = 0

    async def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return valid()

    llm = fake_llm(handler)

    async def generate_six() -> list[Requirements]:
        calls = (llm.generate("Analyze.", "task", Requirements) for _ in range(6))
        return await asyncio.gather(*calls)

    assert asyncio.run(generate_six()) == [REQUIREMENTS] * 6
    assert peak == 3


def test_generate_single_attempt_setting_disables_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_MAX_ATTEMPTS", "1")
    llm, requests = scripted(tool_call("not json"), valid())

    with pytest.raises(LLMError, match="invalid structured output"):
        generate(llm)

    assert len(requests) == 1


def test_generate_logs_classification_but_no_secrets_prompts_or_output(
    caplog: pytest.LogCaptureFixture,
) -> None:
    model_output = json.dumps(
        {
            **VALID_REQUIREMENTS,
            "problem_summary": "MODEL-OUTPUT-SENTINEL",
            "code": "MODEL-CODE-SENTINEL",
        }
    )
    llm, requests = scripted(
        tool_call(model_output),
        httpx2.Response(401, json={"error": {"message": "bad key"}}),
    )

    with pytest.raises(LLMError, match="request failed"):
        asyncio.run(
            llm.generate("INSTRUCTIONS-SENTINEL", "PRIVATE-TASK-SENTINEL", Requirements)
        )

    assert len(requests) == 2
    assert (
        "LLM attempt 1/2 failed: LLM returned invalid structured output" in caplog.text
    )
    assert "status=401" in caplog.text
    for sensitive in (
        "test-key",
        "Bearer",
        "INSTRUCTIONS-SENTINEL",
        "PRIVATE-TASK-SENTINEL",
        "MODEL-OUTPUT-SENTINEL",
        "MODEL-CODE-SENTINEL",
    ):
        assert sensitive not in caplog.text
