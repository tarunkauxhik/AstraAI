"""The human approval pause: interrupt, checkpoint, and resume on the same thread."""

import asyncio
import json
from typing import Any

import pytest

from app.nodes.human_approval import APPROVAL_MEANS
from app.repair import repair_router
from app.state import ApprovalRequest, GeneratedCode, GraphContext
from tests.fake_llm import (
    VALID_PYTHON_CODE,
    WORKFLOW_REPLIES,
    ScriptedReplies,
    fake_llm,
)
from tests.fake_sandbox import PASSED, ScriptedSandbox
from tests.graph_runs import (
    checkpointed_graph,
    pending_interrupts,
    resume,
    start,
    thread,
)

INITIAL = {"run_id": "run-1", "task": "Reverse a string.", "language": "python"}


class Workflow:
    """A checkpointed graph with counting fakes, all created inside the running loop."""

    def __init__(self) -> None:
        self.graph = checkpointed_graph()
        self.llm = ScriptedReplies(WORKFLOW_REPLIES)
        self.sandbox = ScriptedSandbox(PASSED)
        self.context = GraphContext(llm=fake_llm(self.llm), sandbox=self.sandbox)

    async def start(self) -> dict[str, Any]:
        return await start(self.graph, INITIAL, self.context)

    async def resume(self, answer: object) -> dict[str, Any]:
        return await resume(self.graph, "run-1", answer, self.context)

    def work(self) -> tuple[int, int]:
        return len(self.llm.calls), len(self.sandbox.calls)


def test_an_accepted_solution_pauses_for_approval_with_a_compact_payload() -> None:
    async def scenario() -> None:
        workflow = Workflow()

        state = await workflow.start()

        assert repair_router(state) == "accept"
        assert "approval_status" not in state
        (payload,) = await pending_interrupts(workflow.graph, "run-1")
        assert [item.value for item in state["__interrupt__"]] == [payload]
        snapshot = await workflow.graph.aget_state(thread("run-1"))
        assert snapshot.next == ("human_approval",)
        # Everything before the pause is checkpointed on the run's own thread.
        assert snapshot.values["generated_code"] == GeneratedCode.model_validate(
            VALID_PYTHON_CODE
        )

        assert json.loads(json.dumps(payload)) == payload
        request = ApprovalRequest.model_validate(payload)
        assert (request.run_id, request.language) == ("run-1", "python")
        assert (request.execution_status, request.tests_passed) == ("passed", 3)
        assert request.approval_means == APPROVAL_MEANS
        # Large code blobs stay in state, not in the payload.
        assert VALID_PYTHON_CODE["solution_code"] not in json.dumps(payload)
        assert VALID_PYTHON_CODE["test_code"] not in json.dumps(payload)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("decision", "status"), [("approve", "approved"), ("reject", "rejected")]
)
def test_a_decision_resumes_the_same_thread_without_repeating_work(
    decision: str, status: str
) -> None:
    async def scenario() -> None:
        workflow = Workflow()
        await workflow.start()
        work_before_pause = workflow.work()

        state = await workflow.resume({"decision": decision})

        assert state["approval_status"] == status
        assert "__interrupt__" not in state
        assert await pending_interrupts(workflow.graph, "run-1") == []
        # Replay-safe: no LLM call or sandbox execution runs again on resume.
        assert workflow.work() == work_before_pause == (4, 1)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param({"decision": "yes"}, id="unknown-decision"),
        pytest.param({"decision": "APPROVE"}, id="wrong-case"),
        pytest.param({"decision": "approve", "note": "ok"}, id="extra-field"),
        pytest.param({}, id="empty"),
        pytest.param("approve", id="bare-string"),
        pytest.param(True, id="boolean"),
        pytest.param({"decision": ["approve"]}, id="list"),
    ],
)
def test_malformed_answers_are_neither_approval_nor_rejection(answer: object) -> None:
    async def scenario() -> None:
        workflow = Workflow()
        await workflow.start()
        (payload,) = await pending_interrupts(workflow.graph, "run-1")

        state = await workflow.resume(answer)

        assert "approval_status" not in state
        assert await pending_interrupts(workflow.graph, "run-1") == [payload]
        # Still waiting: a valid decision afterwards is honored.
        assert (await workflow.resume({"decision": "approve"}))[
            "approval_status"
        ] == "approved"
        assert workflow.work() == (4, 1)

    asyncio.run(scenario())


def test_a_different_thread_does_not_see_the_paused_run() -> None:
    async def scenario() -> None:
        workflow = Workflow()
        await workflow.start()

        other = await workflow.graph.aget_state(thread("run-2"))

        assert other.values == {}
        assert await pending_interrupts(workflow.graph, "run-1") != []

    asyncio.run(scenario())


def test_checkpoints_hold_no_runtime_objects_or_secrets() -> None:
    async def scenario() -> None:
        workflow = Workflow()
        await workflow.start()

        snapshot = await workflow.graph.aget_state(thread("run-1"))
        stored = repr(workflow.graph.checkpointer.storage) + repr(
            workflow.graph.checkpointer.blobs
        )

        assert set(snapshot.values) == {
            "run_id",
            "task",
            "language",
            "requirements",
            "generated_tests",
            "generated_code",
            "execution_result",
            "critic_result",
        }
        for runtime in ("LLMClient", "Sandbox", "Semaphore", "test-key"):
            assert runtime not in stored

    asyncio.run(scenario())
