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

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("ASTRAAI_LIVE_LLM") != "1",
        reason="set ASTRAAI_LIVE_LLM=1 to call the real LLM",
    ),
]


def test_analyze_task_with_real_llm() -> None:
    task = "Given an array of integers and a target, return indices of two numbers summing to it."
    context = GraphContext(llm=LLMClient(Settings()))

    state = asyncio.run(
        build_graph().ainvoke(
            {"run_id": "live", "task": task, "language": "cpp"},
            context=context,
        )
    )

    assert state["requirements"].functional_requirements
