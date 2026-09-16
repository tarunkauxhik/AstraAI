"""A real LLMClient on an in-memory HTTP transport, so tests never reach the network."""

import json
from collections.abc import Callable
from typing import Any

import httpx2

from app.config import get_settings
from app.llm import LLMClient

Handler = Callable[[httpx2.Request], httpx2.Response]
Reply = str | dict[str, str] | Handler

VALID_REQUIREMENTS = {
    "problem_summary": "Reverse a string.",
    "functional_requirements": ["Return the characters of s in reverse order."],
    "edge_cases": ["Empty string."],
    "constraints": [],
    "expected_input": "A string s.",
    "expected_output": "The reversed string.",
    "relevant_language_requirements": ["Function reverse(s: str) -> str."],
}
VALID_REQUIREMENTS_JSON = json.dumps(VALID_REQUIREMENTS)

# A test plan as stored in state and returned by the API.
VALID_GENERATED_TESTS = {
    "interface": "Function reverse(s: string) -> string.",
    "comparison": "Exact match.",
    "cases": [
        {
            "name": "basic_word",
            "category": "basic",
            "description": "Reverses a typical word.",
            "input": 's = "abc"',
            "input_generator": "",
            "expected_output": '"cba"',
        },
        {
            "name": "empty_string",
            "category": "empty_or_small",
            "description": "An empty string stays empty.",
            "input": 's = ""',
            "input_generator": "",
            "expected_output": '""',
        },
        {
            "name": "single_character",
            "category": "boundary",
            "description": "A one-character string is its own reverse.",
            "input": 's = "x"',
            "input_generator": "",
            "expected_output": '"x"',
        },
    ],
}
VALID_GENERATED_TESTS_JSON = json.dumps(VALID_GENERATED_TESTS)

# Representative generated code, as stored in state and returned by the API.
VALID_PYTHON_CODE = {
    "language": "python",
    "solution_code": """def reverse(s: str) -> str:
    return s[::-1]
""",
    "test_code": """import sys

from solution import reverse

CASES = [
    ("basic_word", "abc", "cba"),
    ("empty_string", "", ""),
    ("single_character", "x", "x"),
]

failures = 0
for name, value, expected in CASES:
    actual = reverse(value)
    if actual != expected:
        print(f"FAIL {name}: expected {expected!r}, got {actual!r}")
        failures += 1

if failures:
    sys.exit(1)
print(f"PASSED {len(CASES)} tests")
""",
    "explanation": "Slicing with a negative step reverses the string.",
}
VALID_PYTHON_CODE_JSON = json.dumps(VALID_PYTHON_CODE)

VALID_CPP_CODE = {
    "language": "cpp",
    "solution_code": """#include <string>

std::string reverse_string(const std::string& s) {
    return std::string(s.rbegin(), s.rend());
}
""",
    # Raw string: the escape sequences belong to the generated C++ source, not to this file.
    "test_code": r"""#include "solution.cpp"

#include <iostream>
#include <string>

int main() {
    int failures = 0;
    const std::string actual = reverse_string("abc");
    if (actual != "cba") {
        std::cout << "FAIL basic_word: expected cba, got " << actual << "\n";
        ++failures;
    }
    if (failures != 0) {
        return 1;
    }
    std::cout << "PASSED 1 tests\n";
    return 0;
}
""",
    "explanation": "Reverse iterators build the reversed string.",
}
VALID_CPP_CODE_JSON = json.dumps(VALID_CPP_CODE)


# A critic verdict, as stored in state and returned by the API.
VALID_CRITIC_RESULT = {
    "verdict": "pass",
    "reason": "Every test passed and the implementation reverses the string as required.",
    "code_issue": "",
    "test_issue": "",
    "recommended_action": "accept",
}
VALID_CRITIC_RESULT_JSON = json.dumps(VALID_CRITIC_RESULT)

# Valid tool arguments for every node of the workflow, keyed by tool name.
WORKFLOW_REPLIES = {
    "Requirements": VALID_REQUIREMENTS_JSON,
    "GeneratedTests": VALID_GENERATED_TESTS_JSON,
    "GeneratedCode": VALID_PYTHON_CODE_JSON,
    "CriticResult": VALID_CRITIC_RESULT_JSON,
}

# Reasoning the live MiniMax gateway leaves in `content` next to a tool call.
MINIMAX_THINK_CONTENT = "<think>\nThe user wants an analysis.\n</think>\n\n</think>"


def completion(message: dict[str, Any], finish_reason: str) -> httpx2.Response:
    """A chat completion shaped like the live MiniMax gateway, extra fields included."""
    return httpx2.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish_reason,
                    "message": {
                        "role": "assistant",
                        "name": "MiniMax AI",
                        "audio_content": "",
                        **message,
                    },
                }
            ],
            "usage": {
                "total_tokens": 3,
                "total_characters": 0,
                "prompt_tokens": 1,
                "completion_tokens": 2,
                "completion_tokens_details": {"reasoning_tokens": 1},
                "prompt_tokens_details": {"cached_tokens": 0},
            },
            "input_sensitive": False,
            "output_sensitive": False,
            "input_sensitive_type": 0,
            "output_sensitive_type": 0,
            "output_sensitive_int": 0,
            "service_tier": "standard",
            "base_resp": {"status_code": 0, "status_msg": ""},
        },
    )


def tool_call(
    arguments: str,
    content: str | None = MINIMAX_THINK_CONTENT,
    name: str = "Requirements",
) -> httpx2.Response:
    return completion(
        {
            "content": content,
            "tool_calls": [
                {
                    "id": "call_function_test",
                    "type": "function",
                    "index": 0,
                    "function": {"name": name, "arguments": arguments},
                }
            ],
        },
        "tool_calls",
    )


def text_reply(content: str) -> httpx2.Response:
    return completion({"content": content}, "stop")


def timeout(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ReadTimeout("timed out", request=request)


def forced_tool(request: httpx2.Request) -> str:
    return json.loads(request.content)["tool_choice"]["function"]["name"]


def fake_llm(reply: Reply) -> LLMClient:
    """LLMClient answering each forced tool call.

    `reply` is the arguments for any tool, arguments keyed by tool name, or a handler.
    """

    def answer(request: httpx2.Request) -> httpx2.Response:
        tool = forced_tool(request)
        return tool_call(reply if isinstance(reply, str) else reply[tool], name=tool)

    transport = httpx2.MockTransport(reply if callable(reply) else answer)
    return LLMClient(
        get_settings(), http_client=httpx2.AsyncClient(transport=transport)
    )
