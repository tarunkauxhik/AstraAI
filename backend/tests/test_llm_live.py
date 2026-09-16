"""Opt-in check against the real endpoint configured in .env or the environment.

Run with ASTRAAI_LIVE_LLM=1. Never part of the normal test run.
"""

import asyncio
import os

import pytest

from app.config import Settings
from app.graph import build_graph
from app.llm import LLMClient
from app.state import GraphContext
from tests.fake_sandbox import FakeSandbox

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("ASTRAAI_LIVE_LLM") != "1",
        reason="set ASTRAAI_LIVE_LLM=1 to call the real LLM",
    ),
]


def test_workflow_with_real_llm() -> None:
    task = "Given an array of integers and a target, return indices of two numbers summing to it."
    # The sandbox is faked here: this test covers the gateway, not Docker.
    context = GraphContext(llm=LLMClient(Settings()), sandbox=FakeSandbox())

    state = asyncio.run(
        build_graph().ainvoke(
            {"run_id": "live", "task": task, "language": "cpp"},
            context=context,
        )
    )

    assert state["requirements"].functional_requirements
    assert state["generated_tests"].cases
    generated_code = state["generated_code"]
    assert generated_code.language == "cpp"
    assert generated_code.solution_code.strip()
    assert generated_code.test_code.strip()
    assert "```" not in generated_code.solution_code + generated_code.test_code
    assert "main(" in generated_code.test_code
