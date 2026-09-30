import asyncio
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from langgraph.types import Command

from app.config import Settings
from app.graph import build_develop_graph, build_graph
from app.llm import LLMClient, LLMError, LLMTimeoutError
from app.repair import MAX_REVISIONS
from app.runs import (
    NODE_STAGES,
    ApprovalConflictError,
    ApprovalExpiredError,
    Decision,
    QueueFullError,
    Run,
    RunManager,
    RunManagerStoppedError,
    RunNotFoundError,
    safe_error,
)
from app.sandbox.docker import DockerSandbox
from app.sandbox.executor import SandboxExecutor
from app.state import (
    CriticResult,
    ExecutionResult,
    GeneratedCode,
    GeneratedTests,
    GraphContext,
    Requirements,
)
from tests.fake_llm import (
    CODE_FAILURE_VERDICT,
    REVISED_SOLUTION,
    VALID_CRITIC_RESULT,
    VALID_GENERATED_TESTS,
    VALID_PYTHON_CODE,
    VALID_REQUIREMENTS,
    WORKFLOW_REPLIES,
    ScriptedReplies,
    fake_llm,
    timeout,
)
from tests.fake_runs import Clock, Gates, hold_forever, storage, stored
from tests.fake_sandbox import (
    FAILED,
    PASSED,
    FakeDockerCli,
    FakeSandbox,
    ScriptedSandbox,
)
from tests.graph_runs import thread


def manager(
    llm: LLMClient,
    sandbox: SandboxExecutor,
    *,
    max_queued_runs: int = 10,
    max_retained_runs: int = 100,
    run_timeout_seconds: float = 300,
    **options: Any,
) -> RunManager:
    """A manager on real SQLite in the test's data dir; a second one there is a restart."""
    graph, store = storage()
    return RunManager(
        graph,
        GraphContext(llm=llm, sandbox=sandbox),
        store,
        max_active_runs=1,
        max_queued_runs=max_queued_runs,
        max_retained_runs=max_retained_runs,
        run_timeout_seconds=run_timeout_seconds,
        approval_timeout_seconds=options.pop("approval_timeout_seconds", 600),
        **options,
    )


async def wait_until(condition: Callable[[], bool], timeout: float = 10.0) -> None:
    # Generous: runs use real SQLite files, and a cold first run can be slow on Windows.
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        if loop.time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.005)


async def run_to_rest(runs: RunManager, run_id: str) -> Run:
    """Wait until a run finishes or pauses for approval."""
    await wait_until(
        lambda: (
            runs.get(run_id).status in ("waiting_for_approval", "completed", "failed")
        )
    )
    return runs.get(run_id)


async def run_to_end(
    runs: RunManager, run_id: str, decision: Decision = "approve"
) -> Run:
    """Wait until a run finishes, answering its approval request with `decision`."""
    if (await run_to_rest(runs, run_id)).status == "waiting_for_approval":
        await runs.resolve_approval(run_id, decision)
        await wait_until(
            lambda: runs.get(run_id).status in ("completed", "failed", "expired")
        )
    return runs.get(run_id)


async def single_run(llm: LLMClient, sandbox: SandboxExecutor) -> Run:
    runs = manager(llm, sandbox)
    await runs.start()
    try:
        return await run_to_end(runs, runs.submit("Reverse a string.", "python").run_id)
    finally:
        await runs.stop()


def test_submit_creates_a_queued_run() -> None:
    async def scenario() -> None:
        runs = manager(fake_llm(WORKFLOW_REPLIES), FakeSandbox())

        run = runs.submit("Reverse a string.", "python")

        assert (run.status, run.stage) == ("queued", "queued")
        assert (run.task, run.language) == ("Reverse a string.", "python")
        assert run.created_at == run.updated_at
        assert run.requirements is None
        assert run.error is None
        assert runs.get(run.run_id) == run
        assert runs.get("unknown") is None

    asyncio.run(scenario())


def test_stages_follow_the_graph_and_results_appear_as_they_land() -> None:
    async def scenario() -> None:
        gates = Gates()
        runs = manager(gates.llm(), gates.sandbox())
        await runs.start()
        try:
            run_id = runs.submit("Reverse a string.", "python").run_id

            def current() -> Run:
                return runs.get(run_id)

            await wait_until(lambda: current().stage == "analyzing")
            assert current().status == "running"
            assert current().requirements is None

            gates.open("Requirements")
            await wait_until(lambda: current().stage == "generating_tests")
            assert current().requirements == Requirements.model_validate(
                VALID_REQUIREMENTS
            )
            assert current().generated_tests is None

            gates.open("GeneratedTests")
            await wait_until(lambda: current().stage == "generating_code")
            assert current().generated_tests == GeneratedTests.model_validate(
                VALID_GENERATED_TESTS
            )

            gates.open("GeneratedCode")
            await wait_until(lambda: current().stage == "executing")
            assert current().generated_code == GeneratedCode.model_validate(
                VALID_PYTHON_CODE
            )
            assert current().execution_result is None

            gates.open("sandbox")
            await wait_until(lambda: current().stage == "reviewing")
            assert current().execution_result == PASSED
            assert current().critic_result is None

            gates.open("CriticResult")
            done = await run_to_end(runs, run_id)
        finally:
            await runs.stop()

        assert (done.status, done.stage, done.error) == ("completed", "completed", None)
        assert (done.approval_status, done.approval_required) == ("approved", False)
        assert done.execution_result == PASSED
        assert done.critic_result == CriticResult.model_validate(VALID_CRITIC_RESULT)
        assert done.updated_at > done.created_at

    asyncio.run(scenario())


def test_one_run_executes_at_a_time_and_the_next_waits() -> None:
    async def scenario() -> None:
        gates = Gates()
        sandbox = gates.sandbox()
        runs = manager(gates.llm(), sandbox)
        await runs.start()
        try:
            first = runs.submit("first", "python").run_id
            second = runs.submit("second", "python").run_id

            await wait_until(lambda: runs.get(first).stage == "analyzing")
            await asyncio.sleep(0.05)
            assert (runs.get(second).status, runs.get(second).stage) == (
                "queued",
                "queued",
            )

            gates.open()
            assert (await run_to_end(runs, first)).status == "completed"
            assert (await run_to_end(runs, second)).status == "completed"
        finally:
            await runs.stop()

        assert [code.language for code in sandbox.calls] == ["python", "python"]

    asyncio.run(scenario())


def test_a_run_never_executes_twice() -> None:
    async def scenario() -> None:
        sandbox = FakeSandbox()
        runs = manager(fake_llm(WORKFLOW_REPLIES), sandbox)
        run_id = runs.submit("Reverse a string.", "python").run_id

        assert runs.enqueue(run_id) is False
        # Bypass the enqueue guard on purpose: the worker must still refuse a second run.
        runs._queue.put_nowait(run_id)

        await runs.start()
        try:
            await run_to_end(runs, run_id)
            await asyncio.sleep(0.05)
            assert runs.enqueue(run_id) is False
            assert runs.enqueue("unknown") is False
        finally:
            await runs.stop()

        assert len(sandbox.calls) == 1

    asyncio.run(scenario())


def test_waiting_runs_are_bounded() -> None:
    async def scenario() -> None:
        runs = manager(fake_llm(hold_forever), FakeSandbox(), max_queued_runs=1)
        await runs.start()
        try:
            active = runs.submit("active", "python").run_id
            await wait_until(lambda: runs.get(active).status == "running")

            waiting = runs.submit("waiting", "python")
            with pytest.raises(QueueFullError):
                runs.submit("rejected", "python")
        finally:
            await runs.stop()

        assert waiting.status == "queued"

    asyncio.run(scenario())


def test_failure_keeps_earlier_results_and_a_safe_error() -> None:
    llm = fake_llm({**WORKFLOW_REPLIES, "GeneratedTests": "not json"})

    run = asyncio.run(single_run(llm, FakeSandbox()))

    assert (run.status, run.stage) == ("failed", "failed")
    assert (run.error.code, run.error.stage) == ("llm_failed", "generating_tests")
    assert run.requirements == Requirements.model_validate(VALID_REQUIREMENTS)
    assert run.generated_tests is None
    assert run.generated_code is None
    assert "not json" not in run.model_dump_json()


def test_timeout_is_reported_as_its_own_error() -> None:
    run = asyncio.run(single_run(fake_llm(timeout), FakeSandbox()))

    assert (run.error.code, run.error.stage) == ("llm_timeout", "analyzing")


def test_unexpected_errors_expose_no_internals() -> None:
    sandbox = FakeSandbox(RuntimeError("Traceback: /var/run/docker.sock denied"))

    run = asyncio.run(single_run(fake_llm(WORKFLOW_REPLIES), sandbox))

    assert (run.status, run.error.code, run.error.stage) == (
        "failed",
        "internal_error",
        "executing",
    )
    assert run.generated_code is not None
    for internal in ("Traceback", "docker.sock", "RuntimeError"):
        assert internal not in run.model_dump_json()


def test_failing_tests_are_never_reported_as_success() -> None:
    failing = ExecutionResult(
        status="failed",
        exit_code=1,
        stdout="FAIL basic_word: expected cba, got abc\n",
        tests_failed=1,
        error_type="test_failure",
    )

    # The scripted critic says pass; reconciliation turns that into a human review.
    run = asyncio.run(single_run(fake_llm(WORKFLOW_REPLIES), FakeSandbox(failing)))

    assert (run.status, run.stage) == ("failed", "failed")
    assert (run.error.code, run.error.stage) == ("needs_human_review", "reviewing")
    assert run.execution_result == failing
    assert run.critic_result.recommended_action == "needs_human_review"


def test_sandbox_infrastructure_failure_fails_the_run_without_details() -> None:
    infrastructure = ExecutionResult(
        status="infrastructure_error",
        exit_code=1,
        stderr="Error response from daemon: /var/lib/docker is full",
        error_type="container_create_failed",
    )

    run = asyncio.run(
        single_run(fake_llm(WORKFLOW_REPLIES), FakeSandbox(infrastructure))
    )

    assert (run.status, run.error.code, run.error.stage) == (
        "failed",
        "sandbox_unavailable",
        "executing",
    )
    assert run.execution_result.stderr == ""
    # One retry was spent before giving up.
    assert run.execution_retry_count == 1
    assert "daemon" not in run.model_dump_json()


def test_old_finished_runs_are_forgotten() -> None:
    async def scenario() -> list[str]:
        runs = manager(fake_llm(WORKFLOW_REPLIES), FakeSandbox(), max_retained_runs=2)
        await runs.start()
        try:
            run_ids = []
            for task in ("first", "second", "third"):
                run_id = runs.submit(task, "python").run_id
                await run_to_end(runs, run_id)
                run_ids.append(run_id)
            return [run_id for run_id in run_ids if runs.get(run_id) is not None]
        finally:
            await runs.stop()

    assert len(asyncio.run(scenario())) == 2


@pytest.mark.parametrize(
    ("error", "code"),
    [
        pytest.param(LLMTimeoutError("secret detail"), "llm_timeout", id="timeout"),
        pytest.param(LLMError("secret detail"), "llm_failed", id="llm"),
        pytest.param(ValueError("secret detail"), "invalid_step_output", id="value"),
        pytest.param(KeyError("secret detail"), "internal_error", id="other"),
    ],
)
def test_safe_error_never_repeats_the_exception_message(
    error: Exception, code: str
) -> None:
    safe = safe_error(error, "analyzing")

    assert (safe.code, safe.stage) == (code, "analyzing")
    assert "secret" not in safe.message


def test_every_working_graph_node_has_a_stage() -> None:
    nodes = {
        node
        for graph in (build_graph(None), build_develop_graph(None))
        for node in graph.get_graph().nodes
    } - {"__start__", "__end__"}

    # human_approval only pauses; the manager reports that as waiting_for_approval.
    assert nodes - {"human_approval"} == set(NODE_STAGES)


def hanging_docker(monkeypatch: pytest.MonkeyPatch) -> FakeDockerCli:
    """A fake docker CLI whose containers run until they are killed or removed."""
    cli = FakeDockerCli(stdout=b"PASSED 3 tests\n", hang=True)
    monkeypatch.setattr("app.sandbox.docker.asyncio.create_subprocess_exec", cli)
    return cli


def test_run_timeout_stops_the_sandbox_and_frees_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = hanging_docker(monkeypatch)

    async def scenario() -> tuple[Run, Run, bool]:
        sandbox = DockerSandbox(Settings(sandbox_timeout_seconds=60))
        runs = manager(fake_llm(WORKFLOW_REPLIES), sandbox, run_timeout_seconds=0.5)
        await runs.start()
        try:
            slow = await run_to_end(runs, runs.submit("slow", "python").run_id)
            client_killed = cli._started.killed
            cli.hang = False  # The next container finishes normally.
            next_run = await run_to_end(runs, runs.submit("next", "python").run_id)
        finally:
            await runs.stop()
        return slow, next_run, client_killed

    slow, next_run, client_killed = asyncio.run(scenario())

    assert (slow.status, slow.error.code, slow.error.stage) == (
        "failed",
        "run_timeout",
        "executing",
    )
    assert slow.error.message == (
        "The run took longer than the allowed time and was stopped."
    )
    assert slow.generated_code is not None
    first_container = cli.ran("create")[0][cli.ran("create")[0].index("--name") + 1]
    assert ["docker", "rm", "--force", "--volumes", first_container] in cli.commands
    assert client_killed
    assert (next_run.status, next_run.execution_result.status) == (
        "completed",
        "passed",
    )


def test_shutdown_cancels_the_active_run_and_removes_its_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = hanging_docker(monkeypatch)

    async def scenario() -> tuple[Run, Run]:
        sandbox = DockerSandbox(Settings(sandbox_timeout_seconds=60))
        runs = manager(fake_llm(WORKFLOW_REPLIES), sandbox)
        await runs.start()
        active = runs.submit("active", "python").run_id
        waiting = runs.submit("waiting", "python").run_id
        await wait_until(lambda: bool(cli.ran("start")))

        await runs.stop()

        # Cleanup has finished by the time stop() returns.
        assert len(cli.ran("rm")) == 1
        with pytest.raises(RunManagerStoppedError):
            runs.submit("late", "python")
        return stored(active), stored(waiting)

    active, waiting = asyncio.run(scenario())

    assert (active.status, active.error.code, active.error.stage) == (
        "failed",
        "shutdown",
        "executing",
    )
    # A run that never started is kept for the next process, not failed.
    assert (waiting.status, waiting.stage, waiting.error) == ("queued", "queued", None)
    assert len(cli.ran("create")) == 1  # The waiting run never started a container.
    assert cli._started.killed


def repair_llm(**replies: Any) -> LLMClient:
    return fake_llm(ScriptedReplies({**WORKFLOW_REPLIES, **replies}))


def test_a_repair_reports_revision_and_re_execution_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stages: list[str] = []
    update = RunManager._update

    def recording(self: RunManager, run_id: str, **changes: Any) -> None:
        if "stage" in changes:
            stages.append(changes["stage"])
        update(self, run_id, **changes)

    monkeypatch.setattr(RunManager, "_update", recording)
    llm = repair_llm(
        CriticResult=[CODE_FAILURE_VERDICT, VALID_CRITIC_RESULT],
        RevisedSolution=REVISED_SOLUTION,
    )

    run = asyncio.run(single_run(llm, ScriptedSandbox(FAILED, PASSED)))

    assert stages == [
        "analyzing",
        "generating_tests",
        "generating_code",
        "executing",
        "reviewing",
        "revising_code",
        "executing",
        "reviewing",
        "waiting_for_approval",
        "resuming",
        "completed",
    ]
    assert (run.status, run.revision_count, run.execution_retry_count) == (
        "completed",
        1,
        0,
    )
    assert run.generated_code.solution_code == REVISED_SOLUTION["solution_code"]
    assert run.execution_result == PASSED


def test_an_exhausted_revision_budget_fails_safely_with_the_latest_artifacts() -> None:
    llm = repair_llm(
        CriticResult=CODE_FAILURE_VERDICT, RevisedSolution=REVISED_SOLUTION
    )

    run = asyncio.run(single_run(llm, ScriptedSandbox(FAILED)))

    assert (run.status, run.error.code, run.error.stage) == (
        "failed",
        "revision_budget_exhausted",
        "reviewing",
    )
    assert run.revision_count == MAX_REVISIONS
    assert run.generated_code.solution_code == REVISED_SOLUTION["solution_code"]
    assert run.execution_result == FAILED
    assert run.critic_result.recommended_action == "revise_code"


def test_a_failed_revision_keeps_the_previous_artifacts() -> None:
    llm = repair_llm(CriticResult=CODE_FAILURE_VERDICT, RevisedSolution="not json")

    run = asyncio.run(single_run(llm, ScriptedSandbox(FAILED)))

    assert (run.status, run.error.code, run.error.stage) == (
        "failed",
        "llm_failed",
        "revising_code",
    )
    assert run.generated_code == GeneratedCode.model_validate(VALID_PYTHON_CODE)
    assert run.execution_result == FAILED
    assert run.critic_result.recommended_action == "revise_code"
    assert run.revision_count == 0


def test_an_accepted_run_waits_for_approval_on_its_own_thread() -> None:
    async def scenario() -> None:
        runs = manager(fake_llm(WORKFLOW_REPLIES), FakeSandbox())
        await runs.start()
        try:
            run_id = runs.submit("Reverse a string.", "python").run_id
            run = await run_to_rest(runs, run_id)
            snapshot = await runs._graph.aget_state(thread(run_id))
        finally:
            await runs.stop()

        assert (run.status, run.stage, run.error) == (
            "waiting_for_approval",
            "waiting_for_approval",
            None,
        )
        assert (run.approval_status, run.approval_required) == ("pending", True)
        assert run.approval_request.run_id == run_id
        assert run.approval_request.execution_status == "passed"
        assert run.generated_code == GeneratedCode.model_validate(VALID_PYTHON_CODE)
        # The checkpoint lives under thread_id == run_id, paused at the approval node.
        assert snapshot.next == ("human_approval",)
        assert snapshot.values["run_id"] == run_id

    asyncio.run(scenario())


def test_every_start_and_resume_uses_the_run_id_as_thread_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configs: list[dict[str, Any]] = []

    async def scenario() -> str:
        runs = manager(fake_llm(WORKFLOW_REPLIES), FakeSandbox())
        astream = runs._graph.astream

        def recording(*args: Any, **kwargs: Any) -> Any:
            configs.append(kwargs["config"])
            return astream(*args, **kwargs)

        monkeypatch.setattr(runs._graph, "astream", recording)
        await runs.start()
        try:
            run_id = runs.submit("Reverse a string.", "python").run_id
            assert (await run_to_end(runs, run_id)).status == "completed"
        finally:
            await runs.stop()
        return run_id

    run_id = asyncio.run(scenario())

    assert configs == [thread(run_id), thread(run_id)]


def test_approval_resumes_without_repeating_work_and_completes() -> None:
    async def scenario() -> None:
        llm = ScriptedReplies(WORKFLOW_REPLIES)
        sandbox = ScriptedSandbox(PASSED)
        runs = manager(fake_llm(llm), sandbox)
        await runs.start()
        try:
            run_id = runs.submit("Reverse a string.", "python").run_id
            await run_to_rest(runs, run_id)
            work = (list(llm.calls), len(sandbox.calls))

            queued = await runs.resolve_approval(run_id, "approve")
            assert (queued.status, queued.stage, queued.approval_required) == (
                "running",
                "resuming",
                False,
            )
            done = await run_to_end(runs, run_id)
            leftover = await runs._graph.aget_state(thread(run_id))
        finally:
            await runs.stop()

        assert (done.status, done.stage, done.error) == ("completed", "completed", None)
        assert done.approval_status == "approved"
        # Replay-safe: resuming ran no LLM call or sandbox execution again.
        assert (llm.calls, len(sandbox.calls)) == work
        assert work == (
            ["Requirements", "GeneratedTests", "GeneratedCode", "CriticResult"],
            1,
        )
        # A finished run's checkpoint is deleted.
        assert leftover.values == {}

    asyncio.run(scenario())


def test_rejection_fails_the_run_safely_and_keeps_its_artifacts() -> None:
    async def scenario() -> Run:
        runs = manager(fake_llm(WORKFLOW_REPLIES), FakeSandbox())
        await runs.start()
        try:
            run_id = runs.submit("Reverse a string.", "python").run_id
            return await run_to_end(runs, run_id, decision="reject")
        finally:
            await runs.stop()

    run = asyncio.run(scenario())

    assert (run.status, run.stage, run.approval_status) == (
        "failed",
        "failed",
        "rejected",
    )
    assert (run.error.code, run.error.stage) == (
        "approval_rejected",
        "waiting_for_approval",
    )
    assert run.generated_code == GeneratedCode.model_validate(VALID_PYTHON_CODE)


def test_a_waiting_run_frees_the_worker_for_the_next_run() -> None:
    async def scenario() -> None:
        runs = manager(fake_llm(WORKFLOW_REPLIES), FakeSandbox())
        await runs.start()
        try:
            first = runs.submit("first", "python").run_id
            second = runs.submit("second", "python").run_id

            # With one worker, the second run can only get here if the first let go.
            assert (await run_to_rest(runs, first)).status == "waiting_for_approval"
            assert (await run_to_rest(runs, second)).status == "waiting_for_approval"
            assert runs.get(first).status == "waiting_for_approval"

            assert (await run_to_end(runs, first)).status == "completed"
            assert (await run_to_end(runs, second, "reject")).status == "failed"
        finally:
            await runs.stop()

    asyncio.run(scenario())


def test_only_one_decision_is_accepted_per_run() -> None:
    async def scenario() -> None:
        runs = manager(fake_llm(WORKFLOW_REPLIES), FakeSandbox())
        await runs.start()
        try:
            run_id = runs.submit("Reverse a string.", "python").run_id
            await run_to_rest(runs, run_id)

            await runs.resolve_approval(run_id, "approve")
            for late in ("approve", "reject"):
                with pytest.raises(ApprovalConflictError):
                    await runs.resolve_approval(run_id, late)
            done = await run_to_end(runs, run_id)
            with pytest.raises(ApprovalConflictError):
                await runs.resolve_approval(run_id, "reject")
        finally:
            await runs.stop()

        assert (done.status, done.approval_status) == ("completed", "approved")

    asyncio.run(scenario())


def test_approval_needs_a_known_run_that_is_waiting() -> None:
    async def scenario() -> None:
        runs = manager(fake_llm(hold_forever), FakeSandbox())
        with pytest.raises(RunNotFoundError):
            await runs.resolve_approval("unknown", "approve")
        run_id = runs.submit("queued", "python").run_id
        with pytest.raises(ApprovalConflictError):
            await runs.resolve_approval(run_id, "approve")

        await runs.start()
        try:
            await wait_until(lambda: runs.get(run_id).status == "running")
            with pytest.raises(ApprovalConflictError):
                await runs.resolve_approval(run_id, "approve")
        finally:
            await runs.stop()
        with pytest.raises(RunManagerStoppedError):
            await runs.resolve_approval(run_id, "approve")

    asyncio.run(scenario())


def test_approval_with_a_full_queue_leaves_the_run_waiting() -> None:
    async def scenario() -> None:
        gates = Gates()
        runs = manager(gates.llm(), gates.sandbox(), max_queued_runs=1)
        await runs.start()
        try:
            gates.open()
            paused = runs.submit("paused", "python").run_id
            await run_to_rest(runs, paused)
            gates.events["Requirements"].clear()
            busy = runs.submit("busy", "python").run_id
            await wait_until(lambda: runs.get(busy).status == "running")
            queued = runs.submit("queued", "python").run_id

            with pytest.raises(QueueFullError):
                await runs.resolve_approval(paused, "approve")
            still = runs.get(paused)
            assert (still.status, still.stage, still.approval_required) == (
                "waiting_for_approval",
                "waiting_for_approval",
                True,
            )
            gates.open()
            await wait_until(lambda: runs.get(queued).status != "queued")
            assert (await run_to_end(runs, paused)).status == "completed"
        finally:
            await runs.stop()

    asyncio.run(scenario())


def test_waiting_for_approval_does_not_count_toward_the_run_timeout() -> None:
    async def scenario() -> Run:
        runs = manager(
            fake_llm(WORKFLOW_REPLIES), FakeSandbox(), run_timeout_seconds=0.3
        )
        await runs.start()
        try:
            run_id = runs.submit("Reverse a string.", "python").run_id
            await run_to_rest(runs, run_id)
            await asyncio.sleep(0.5)  # Longer than the timeout, spent waiting.
            assert runs.get(run_id).status == "waiting_for_approval"
            return await run_to_end(runs, run_id)
        finally:
            await runs.stop()

    run = asyncio.run(scenario())

    assert (run.status, run.error) == ("completed", None)


def test_a_resume_that_overruns_its_own_timeout_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> Run:
        runs = manager(
            fake_llm(WORKFLOW_REPLIES), FakeSandbox(), run_timeout_seconds=0.3
        )
        await runs.start()
        try:
            run_id = runs.submit("Reverse a string.", "python").run_id
            await run_to_rest(runs, run_id)
            drive = runs._drive_graph

            async def slow_resume(*args: Any) -> Any:
                await asyncio.sleep(1)
                return await drive(*args)

            monkeypatch.setattr(runs, "_drive_graph", slow_resume)
            return await run_to_end(runs, run_id)
        finally:
            await runs.stop()

    run = asyncio.run(scenario())

    assert (run.status, run.error.code) == ("failed", "run_timeout")


def test_shutdown_keeps_runs_waiting_for_approval() -> None:
    async def scenario() -> None:
        runs = manager(fake_llm(WORKFLOW_REPLIES), FakeSandbox())
        await runs.start()
        run_id = runs.submit("Reverse a string.", "python").run_id
        await run_to_rest(runs, run_id)

        await runs.stop()

        # Waiting is not work in progress: the run and its paused thread outlive the process.
        run = stored(run_id)
        assert (run.status, run.approval_status, run.error) == (
            "waiting_for_approval",
            "pending",
            None,
        )
        restarted = manager(fake_llm(WORKFLOW_REPLIES), FakeSandbox())
        await restarted.start()
        try:
            assert await has_checkpoint(restarted, run_id)
        finally:
            await restarted.stop()

    asyncio.run(scenario())


# Approval timeout. The sweeper interval is huge unless a test says otherwise, so each test
# decides exactly when expiry is checked; the fake clock replaces real waiting.
NO_SWEEP = 3600


def approval_manager(
    clock: Clock, **options: Any
) -> tuple[RunManager, ScriptedReplies, ScriptedSandbox]:
    llm = ScriptedReplies(WORKFLOW_REPLIES)
    sandbox = ScriptedSandbox(PASSED)
    options.setdefault("approval_sweep_seconds", NO_SWEEP)
    runs = manager(fake_llm(llm), sandbox, clock=clock, **options)
    return runs, llm, sandbox


async def paused(runs: RunManager) -> str:
    run_id = runs.submit("Reverse a string.", "python").run_id
    assert (await run_to_rest(runs, run_id)).status == "waiting_for_approval"
    return run_id


async def has_checkpoint(runs: RunManager, run_id: str) -> bool:
    return (await runs._graph.aget_state(thread(run_id))).values != {}


def record_stages(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every public stage a run manager sets, in order."""
    stages: list[str] = []
    update = RunManager._update

    def recording(self: RunManager, run_id: str, **changes: Any) -> None:
        if "stage" in changes:
            stages.append(changes["stage"])
        update(self, run_id, **changes)

    monkeypatch.setattr(RunManager, "_update", recording)
    return stages


def test_the_approval_timeout_starts_when_the_run_starts_waiting() -> None:
    async def scenario() -> None:
        clock = Clock()
        gates = Gates()
        runs = manager(
            gates.llm(),
            gates.sandbox(),
            clock=clock,
            approval_sweep_seconds=NO_SWEEP,
        )
        await runs.start()
        try:
            run_id = runs.submit("Reverse a string.", "python").run_id
            created = clock.now
            # Active work takes far longer than the approval timeout; none of it counts.
            clock.advance(5_000)
            gates.open()
            run = await run_to_rest(runs, run_id)
            clock.advance(599)
            expired = await runs.expire_approvals()
            still = runs.get(run_id)
            checkpoint = await has_checkpoint(runs, run_id)
        finally:
            await runs.stop()

        assert run.approval_requested_at == created + timedelta(seconds=5_000)
        assert run.approval_expires_at == run.approval_requested_at + timedelta(
            seconds=600
        )
        assert expired == []
        assert (still.status, still.approval_status) == (
            "waiting_for_approval",
            "pending",
        )
        assert checkpoint

    asyncio.run(scenario())


def test_an_unanswered_run_expires_and_releases_its_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stages = record_stages(monkeypatch)

    async def scenario() -> None:
        clock = Clock()
        runs, llm, sandbox = approval_manager(clock)
        await runs.start()
        try:
            run_id = await paused(runs)
            assert await has_checkpoint(runs, run_id)
            work = (len(llm.calls), len(sandbox.calls))
            clock.advance(600)

            assert await runs.expire_approvals() == [run_id]
            run = runs.get(run_id)
            assert not await has_checkpoint(runs, run_id)
            assert await runs.expire_approvals() == []
        finally:
            await runs.stop()

        # Not a failure: only the decision lapsed, so there is no error to report.
        assert (run.status, run.stage, run.error) == ("expired", "expired", None)
        assert (run.approval_status, run.approval_required) == ("expired", False)
        # The verified work and its evidence stay; nothing resumed, called the LLM or
        # ran the sandbox.
        assert run.generated_code == GeneratedCode.model_validate(VALID_PYTHON_CODE)
        assert run.execution_result == PASSED
        assert run.critic_result is not None
        assert run.approval_request is not None
        assert (len(llm.calls), len(sandbox.calls)) == work
        assert stages[stages.index("waiting_for_approval") :] == [
            "waiting_for_approval",
            "expired",
        ]

    asyncio.run(scenario())


@pytest.mark.parametrize("decision", ["approve", "reject"])
@pytest.mark.parametrize("swept", [True, False], ids=["swept", "not-yet-swept"])
def test_an_expired_run_cannot_be_decided(decision: Decision, swept: bool) -> None:
    async def scenario() -> None:
        clock = Clock()
        runs, llm, sandbox = approval_manager(clock)
        await runs.start()
        try:
            run_id = await paused(runs)
            work = (len(llm.calls), len(sandbox.calls))
            clock.advance(600)
            if swept:
                await runs.expire_approvals()

            for _ in range(2):  # Deterministic: the same answer every time.
                with pytest.raises(ApprovalExpiredError):
                    await runs.resolve_approval(run_id, decision)
            await asyncio.sleep(0.05)
            run = runs.get(run_id)
            checkpoint = await has_checkpoint(runs, run_id)
        finally:
            await runs.stop()

        assert (run.status, run.approval_status, run.error) == (
            "expired",
            "expired",
            None,
        )
        assert not checkpoint
        assert (len(llm.calls), len(sandbox.calls)) == work

    asyncio.run(scenario())


def test_more_time_restarts_the_approval_window_from_now() -> None:
    async def scenario() -> None:
        clock = Clock()
        runs, _, _ = approval_manager(clock)
        await runs.start()
        try:
            run_id = await paused(runs)
            asked = runs.get(run_id)
            clock.advance(500)
            extended = await runs.extend_approval(run_id)
            clock.advance(599)
            early = await runs.expire_approvals()
            clock.advance(1)
            late = await runs.expire_approvals()
            run = runs.get(run_id)
        finally:
            await runs.stop()

        assert extended.approval_expires_at == asked.approval_requested_at + timedelta(
            seconds=1_100
        )
        # When approval was first requested doesn't change.
        assert extended.approval_requested_at == asked.approval_requested_at
        assert (extended.status, extended.approval_status) == (
            "waiting_for_approval",
            "pending",
        )
        assert (early, late) == ([], [run_id])
        assert run.status == "expired"

    asyncio.run(scenario())


def test_more_time_can_be_asked_for_repeatedly_and_the_run_still_decided() -> None:
    async def scenario() -> None:
        clock = Clock()
        runs, _, _ = approval_manager(clock)
        await runs.start()
        try:
            run_id = await paused(runs)
            for _ in range(12):
                clock.advance(590)
                await runs.extend_approval(run_id)
                assert await runs.expire_approvals() == []
            await runs.resolve_approval(run_id, "approve")
            done = await run_to_end(runs, run_id)
        finally:
            await runs.stop()

        assert (done.status, done.approval_status) == ("completed", "approved")

    asyncio.run(scenario())


@pytest.mark.parametrize("swept", [True, False], ids=["swept", "not-yet-swept"])
def test_more_time_cannot_revive_an_expired_review(swept: bool) -> None:
    async def scenario() -> None:
        clock = Clock()
        runs, _, _ = approval_manager(clock)
        await runs.start()
        try:
            run_id = await paused(runs)
            clock.advance(600)
            if swept:
                await runs.expire_approvals()

            with pytest.raises(ApprovalExpiredError):
                await runs.extend_approval(run_id)
            run = runs.get(run_id)
            checkpoint = await has_checkpoint(runs, run_id)
        finally:
            await runs.stop()

        assert (run.status, run.approval_status) == ("expired", "expired")
        assert not checkpoint

    asyncio.run(scenario())


def test_more_time_needs_a_run_that_is_waiting() -> None:
    async def scenario() -> None:
        clock = Clock()
        runs, _, _ = approval_manager(clock)
        await runs.start()
        try:
            rejected = await paused(runs)
            await runs.resolve_approval(rejected, "reject")
            with pytest.raises(ApprovalConflictError):
                await runs.extend_approval(rejected)
            with pytest.raises(RunNotFoundError):
                await runs.extend_approval("no-such-run")
            waiting = await paused(runs)
        finally:
            await runs.stop()

        with pytest.raises(RunManagerStoppedError):
            await runs.extend_approval(waiting)

    asyncio.run(scenario())


def test_expired_runs_are_forgotten_like_finished_ones() -> None:
    async def scenario() -> None:
        clock = Clock()
        runs, _, _ = approval_manager(clock, max_retained_runs=1)
        await runs.start()
        try:
            run_id = await paused(runs)
            clock.advance(600)
            await runs.expire_approvals()
            newer = runs.submit("Reverse a string.", "python").run_id
            assert runs.get(run_id) is None
            assert runs.get(newer) is not None
        finally:
            await runs.stop()

    asyncio.run(scenario())


def test_approval_just_before_the_timeout_wins() -> None:
    async def scenario() -> None:
        clock = Clock()
        runs, _, sandbox = approval_manager(clock)
        await runs.start()
        try:
            run_id = await paused(runs)
            clock.advance(599.999)

            resumed = await runs.resolve_approval(run_id, "approve")
            # The deadline passes before the worker even picks the resume up.
            clock.advance(10)
            expired = await runs.expire_approvals()
            done = await run_to_end(runs, run_id)
            checkpoint = await has_checkpoint(runs, run_id)
        finally:
            await runs.stop()

        assert (resumed.status, resumed.stage) == ("running", "resuming")
        assert expired == []
        assert (done.status, done.approval_status, done.error) == (
            "completed",
            "approved",
            None,
        )
        assert len(sandbox.calls) == 1
        assert not checkpoint

    asyncio.run(scenario())


@pytest.mark.parametrize("sweep_first", [True, False])
def test_approval_and_expiry_racing_have_exactly_one_outcome(sweep_first: bool) -> None:
    async def scenario() -> None:
        clock = Clock()
        runs, llm, _ = approval_manager(clock)
        await runs.start()
        try:
            run_id = await paused(runs)
            calls = len(llm.calls)
            clock.advance(600)
            sweep = runs.expire_approvals()
            approve = runs.resolve_approval(run_id, "approve")
            ordered = (sweep, approve) if sweep_first else (approve, sweep)

            results = await asyncio.gather(*ordered, return_exceptions=True)
            await asyncio.sleep(0.05)
            run = runs.get(run_id)
            checkpoint = await has_checkpoint(runs, run_id)
        finally:
            await runs.stop()

        swept, approval = results if sweep_first else results[::-1]
        assert isinstance(approval, ApprovalExpiredError)
        assert swept == ([run_id] if sweep_first else [])
        assert (run.status, run.approval_status, run.error) == (
            "expired",
            "expired",
            None,
        )
        assert len(llm.calls) == calls
        assert not checkpoint

    asyncio.run(scenario())


def test_approval_first_makes_a_racing_sweep_a_no_op() -> None:
    async def scenario() -> None:
        clock = Clock()
        runs, _, _ = approval_manager(clock)
        await runs.start()
        try:
            run_id = await paused(runs)
            clock.advance(599)
            approve = runs.resolve_approval(run_id, "approve")
            sweep = runs.expire_approvals()

            _, swept = await asyncio.gather(approve, sweep)
            done = await run_to_end(runs, run_id)
        finally:
            await runs.stop()

        assert swept == []
        assert (done.status, done.approval_status) == ("completed", "approved")

    asyncio.run(scenario())


def test_shutdown_leaves_an_elapsed_approval_to_the_next_process() -> None:
    async def scenario() -> None:
        clock = Clock()
        runs, _, _ = approval_manager(clock)
        await runs.start()
        run_id = await paused(runs)
        clock.advance(10_000)

        await runs.stop()

        # A stopping process decides nothing, not even expiry.
        assert await runs.expire_approvals() == []
        with pytest.raises(RunManagerStoppedError):
            await runs.resolve_approval(run_id, "approve")
        assert stored(run_id).status == "waiting_for_approval"

        restarted, _, _ = approval_manager(clock)
        await restarted.start()
        try:
            with pytest.raises(ApprovalExpiredError):
                await restarted.resolve_approval(run_id, "approve")
            run = restarted.get(run_id)
            assert (run.status, run.approval_status, run.error) == (
                "expired",
                "expired",
                None,
            )
            assert not await has_checkpoint(restarted, run_id)
        finally:
            await restarted.stop()

    asyncio.run(scenario())


def test_the_sweeper_expires_runs_on_its_own() -> None:
    async def scenario() -> None:
        clock = Clock()
        runs, _, _ = approval_manager(clock, approval_sweep_seconds=0.01)
        await runs.start()
        try:
            run_id = await paused(runs)
            clock.advance(600)
            await wait_until(lambda: runs.get(run_id).approval_status == "expired")
            assert not await has_checkpoint(runs, run_id)
        finally:
            await runs.stop()

    asyncio.run(scenario())


def test_the_sweeper_keeps_going_after_a_failed_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        runs, _, _ = approval_manager(Clock(), approval_sweep_seconds=0.01)
        passes: list[int] = []

        async def flaky() -> list[str]:
            passes.append(1)
            if len(passes) == 1:
                raise RuntimeError("boom")
            return []

        monkeypatch.setattr(runs, "expire_approvals", flaky)
        await runs.start()
        try:
            await wait_until(lambda: len(passes) >= 3)
        finally:
            await runs.stop()

    asyncio.run(scenario())


def test_one_sweeper_starts_once_and_stops_cleanly() -> None:
    async def scenario() -> None:
        runs, _, _ = approval_manager(Clock(), approval_sweep_seconds=0.01)
        await runs.start()
        sweeper, workers = runs._sweeper, list(runs._workers)
        await runs.start()  # A second start must not add tasks.

        assert runs._sweeper is sweeper
        assert runs._workers == workers
        tasks = asyncio.all_tasks() - {asyncio.current_task()}
        assert tasks == {sweeper, *workers}

        await runs.stop()

        assert sweeper.cancelled()
        assert runs._sweeper is None
        assert asyncio.all_tasks() == {asyncio.current_task()}

    asyncio.run(scenario())


# Resume stage: approval shows `resuming`, never `queued`.


def test_approval_shows_resuming_and_never_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stages = record_stages(monkeypatch)

    async def scenario() -> tuple[Run, Run, Run]:
        runs, _, _ = approval_manager(Clock())
        await runs.start()
        try:
            run_id = runs.submit("Reverse a string.", "python").run_id
            submitted = runs.get(run_id)
            await run_to_rest(runs, run_id)
            resuming = await runs.resolve_approval(run_id, "approve")
            done = await run_to_end(runs, run_id)
        finally:
            await runs.stop()
        return submitted, resuming, done

    submitted, resuming, done = asyncio.run(scenario())

    # New runs still start queued.
    assert (submitted.status, submitted.stage) == ("queued", "queued")
    assert (resuming.status, resuming.stage) == ("running", "resuming")
    assert (resuming.approval_status, resuming.approval_required) == (
        "approved",
        False,
    )
    assert stages == [
        "analyzing",
        "generating_tests",
        "generating_code",
        "executing",
        "reviewing",
        "waiting_for_approval",
        "resuming",
        "completed",
    ]
    assert (done.status, done.stage) == ("completed", "completed")


def test_rejection_ends_the_run_without_resuming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stages = record_stages(monkeypatch)

    async def scenario() -> None:
        runs, llm, sandbox = approval_manager(Clock())
        await runs.start()
        try:
            run_id = await paused(runs)
            work = (len(llm.calls), len(sandbox.calls))

            rejected = await runs.resolve_approval(run_id, "reject")
            checkpoint = await has_checkpoint(runs, run_id)
            await asyncio.sleep(0.05)
        finally:
            await runs.stop()

        # Terminal as soon as the call returns: no queue, no worker, no graph.
        assert (rejected.status, rejected.stage, rejected.approval_status) == (
            "failed",
            "failed",
            "rejected",
        )
        assert rejected.approval_required is False
        assert not checkpoint
        assert (len(llm.calls), len(sandbox.calls)) == work
        assert stages[stages.index("waiting_for_approval") :] == [
            "waiting_for_approval",
            "failed",
        ]

    asyncio.run(scenario())


def test_a_resumed_run_waiting_in_the_queue_still_reads_resuming() -> None:
    async def scenario() -> None:
        gates = Gates()
        runs = manager(gates.llm(), gates.sandbox(), approval_sweep_seconds=NO_SWEEP)
        await runs.start()
        try:
            gates.open()
            first = await paused(runs)
            gates.events["Requirements"].clear()
            busy = runs.submit("busy", "python").run_id
            await wait_until(lambda: runs.get(busy).stage == "analyzing")

            await runs.resolve_approval(first, "approve")
            await asyncio.sleep(0.05)
            # Scheduled on the internal queue behind the busy run, but never `queued`.
            assert first in runs._enqueued
            waiting_in_queue = runs.get(first)
            assert (waiting_in_queue.status, waiting_in_queue.stage) == (
                "running",
                "resuming",
            )
            gates.open()
            assert (await run_to_end(runs, first)).status == "completed"
        finally:
            await runs.stop()

    asyncio.run(scenario())


def test_an_approved_run_still_in_the_queue_resumes_after_a_restart() -> None:
    async def scenario() -> None:
        gates = Gates()
        runs = manager(gates.llm(), gates.sandbox(), approval_sweep_seconds=NO_SWEEP)
        await runs.start()
        gates.open()
        first = await paused(runs)
        gates.events["Requirements"].clear()
        busy = runs.submit("busy", "python").run_id
        await wait_until(lambda: runs.get(busy).stage == "analyzing")
        await runs.resolve_approval(first, "approve")

        await runs.stop()

        # The human's decision was recorded, so the next process carries it out.
        assert (stored(first).stage, stored(first).approval_status) == (
            "resuming",
            "approved",
        )
        llm = ScriptedReplies(WORKFLOW_REPLIES)
        sandbox = FakeSandbox()
        restarted = manager(fake_llm(llm), sandbox, approval_sweep_seconds=NO_SWEEP)
        await restarted.start()
        try:
            run = await run_to_end(restarted, first)
            assert (run.status, run.approval_status, run.error) == (
                "completed",
                "approved",
                None,
            )
            # Resumed on its checkpoint: no step was repeated.
            assert "Requirements" not in llm.calls
            assert sandbox.calls == []
            # The busy run was working when the process stopped, so it stays failed.
            assert (restarted.get(busy).status, restarted.get(busy).error.code) == (
                "failed",
                "shutdown",
            )
        finally:
            await restarted.stop()

    asyncio.run(scenario())


# Durability. Every manager below uses real SQLite files in the test's data dir, so a
# second manager there is a restarted process. A "crash" starts that second manager while
# the first is still stuck mid-step: exactly what a new process finds after a hard kill.
ALL_STATUSES = (
    "queued",
    "running",
    "waiting_for_approval",
    "completed",
    "failed",
    "expired",
)
EVIDENCE = (
    "requirements",
    "generated_tests",
    "generated_code",
    "execution_result",
    "critic_result",
)


def test_a_submitted_run_is_stored_and_executes_once_across_restarts() -> None:
    async def scenario() -> None:
        runs = manager(fake_llm(WORKFLOW_REPLIES), FakeSandbox())
        submitted = runs.submit("Reverse a string.", "python")
        await runs.stop()  # Stopped before any worker took it.

        assert stored(submitted.run_id) == submitted
        sandbox = FakeSandbox()
        restarted = manager(fake_llm(WORKFLOW_REPLIES), sandbox)
        await restarted.start()
        try:
            run = await run_to_end(restarted, submitted.run_id)
        finally:
            await restarted.stop()
        assert run.status == "completed"
        assert len(sandbox.calls) == 1

        again = manager(fake_llm(WORKFLOW_REPLIES), FakeSandbox())
        await again.start()
        try:
            assert again.get(submitted.run_id) == run
            stored_ids = [r.run_id for r in again._store.with_status(*ALL_STATUSES)]
            assert stored_ids == [submitted.run_id]
        finally:
            await again.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("ending", "status"),
    [("approve", "completed"), ("reject", "failed"), ("expire", "expired")],
)
def test_finished_runs_and_their_evidence_survive_a_restart(
    ending: str, status: str
) -> None:
    async def scenario() -> None:
        clock = Clock()
        runs, _, _ = approval_manager(clock)
        await runs.start()
        try:
            run_id = await paused(runs)
            if ending == "expire":
                clock.advance(600)
                await runs.expire_approvals()
            else:
                await run_to_end(runs, run_id, ending)
            before = runs.get(run_id)
        finally:
            await runs.stop()

        restarted, llm, sandbox = approval_manager(clock)
        await restarted.start()
        try:
            after = restarted.get(run_id)
            assert after == before
            assert after.status == status
            assert all(getattr(after, field) is not None for field in EVIDENCE)
            await asyncio.sleep(0.05)
            assert (llm.calls, sandbox.calls) == ([], [])
        finally:
            await restarted.stop()

    asyncio.run(scenario())


def test_a_waiting_run_is_approved_after_a_restart_on_the_same_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        runs = manager(fake_llm(WORKFLOW_REPLIES), FakeSandbox())
        await runs.start()
        try:
            run_id = await paused(runs)
            before = runs.get(run_id)
        finally:
            await runs.stop()

        llm = ScriptedReplies(WORKFLOW_REPLIES)
        sandbox = FakeSandbox()
        restarted = manager(fake_llm(llm), sandbox)
        streams: list[tuple[Any, str]] = []
        astream = restarted._graph.astream

        def spy(graph_input: Any, config: Any, **kwargs: Any) -> Any:
            streams.append((graph_input, config["configurable"]["thread_id"]))
            return astream(graph_input, config, **kwargs)

        monkeypatch.setattr(restarted._graph, "astream", spy)
        await restarted.start()
        try:
            assert restarted.get(run_id) == before
            decided = await restarted.resolve_approval(run_id, "approve")
            assert decided.stage == "resuming"
            run = await run_to_end(restarted, run_id)
        finally:
            await restarted.stop()

        assert (run.status, run.approval_status, run.error) == (
            "completed",
            "approved",
            None,
        )
        # One resume of the paused thread; nothing before the approval ran again.
        [(graph_input, thread_id)] = streams
        assert isinstance(graph_input, Command)
        assert thread_id == run_id
        assert (llm.calls, sandbox.calls) == ([], [])
        for field in EVIDENCE:
            assert getattr(run, field) == getattr(before, field)

    asyncio.run(scenario())


def test_a_crash_during_a_model_step_never_reports_completion() -> None:
    async def scenario() -> None:
        gates = Gates()
        crashed = manager(gates.llm(), gates.sandbox())
        await crashed.start()
        gates.open("Requirements")
        run_id = crashed.submit("Reverse a string.", "python").run_id
        await wait_until(lambda: crashed.get(run_id).stage == "generating_tests")

        llm = ScriptedReplies(WORKFLOW_REPLIES)
        restarted = manager(fake_llm(llm), FakeSandbox())
        await restarted.start()
        try:
            run = restarted.get(run_id)
            assert (run.status, run.stage) == ("failed", "failed")
            assert (run.error.code, run.error.stage) == ("shutdown", "generating_tests")
            assert run.requirements is not None  # The evidence it had is kept.
            assert not await has_checkpoint(restarted, run_id)
            await asyncio.sleep(0.05)
            assert llm.calls == []  # Never continued.
        finally:
            await restarted.stop()
            await crashed.stop()

    asyncio.run(scenario())


def test_a_crash_during_sandbox_execution_never_claims_the_execution() -> None:
    async def scenario() -> None:
        gates = Gates()
        crashed = manager(gates.llm(), gates.sandbox())
        await crashed.start()
        gates.open("Requirements", "GeneratedTests", "GeneratedCode")
        run_id = crashed.submit("Reverse a string.", "python").run_id
        await wait_until(lambda: crashed.get(run_id).stage == "executing")

        sandbox = FakeSandbox()
        restarted = manager(fake_llm(WORKFLOW_REPLIES), sandbox)
        await restarted.start()
        try:
            run = restarted.get(run_id)
            assert (run.status, run.error.code, run.error.stage) == (
                "failed",
                "shutdown",
                "executing",
            )
            # No outcome was observed, so none is reported, and it is never re-run.
            assert run.execution_result is None
            assert run.approval_status is None
            assert run.generated_code is not None
            await asyncio.sleep(0.05)
            assert sandbox.calls == []
        finally:
            await restarted.stop()
            await crashed.stop()

    asyncio.run(scenario())


def test_approval_timing_survives_a_restart() -> None:
    async def scenario() -> None:
        clock = Clock()
        runs, _, _ = approval_manager(clock)
        await runs.start()
        try:
            run_id = await paused(runs)
            requested = runs.get(run_id)
        finally:
            await runs.stop()

        clock.advance(300)
        restarted, _, _ = approval_manager(clock)
        await restarted.start()
        try:
            run = restarted.get(run_id)
            assert run.approval_requested_at == requested.approval_requested_at
            assert run.approval_expires_at == requested.approval_expires_at
            extended = await restarted.extend_approval(run_id)
            assert extended.approval_expires_at == clock.now + timedelta(seconds=600)
        finally:
            await restarted.stop()

        clock.advance(600)
        again, _, _ = approval_manager(clock)
        await again.start()
        try:
            assert again.get(run_id).approval_expires_at == extended.approval_expires_at
            with pytest.raises(ApprovalExpiredError):
                await again.extend_approval(run_id)
            assert again.get(run_id).status == "expired"
        finally:
            await again.stop()

    asyncio.run(scenario())


def test_retention_never_removes_a_waiting_run_or_its_checkpoint() -> None:
    async def scenario() -> None:
        runs, _, _ = approval_manager(Clock(), max_retained_runs=2)
        await runs.start()
        try:
            waiting = await paused(runs)
            for _ in range(3):
                await runs.resolve_approval(await paused(runs), "reject")
            runs.submit("one more", "python")

            assert runs.get(waiting).status == "waiting_for_approval"
            assert await has_checkpoint(runs, waiting)
            assert len(runs._store.with_status(*ALL_STATUSES)) == 2
            assert (await run_to_end(runs, waiting)).status == "completed"
        finally:
            await runs.stop()

    asyncio.run(scenario())


def test_a_waiting_run_whose_checkpoint_is_gone_fails_instead_of_resuming() -> None:
    async def scenario() -> None:
        runs = manager(fake_llm(WORKFLOW_REPLIES), FakeSandbox())
        await runs.start()
        try:
            run_id = await paused(runs)
        finally:
            await runs.stop()

        restarted = manager(fake_llm(WORKFLOW_REPLIES), FakeSandbox())
        checkpointer = restarted._graph.checkpointer
        await checkpointer.setup()
        await checkpointer.adelete_thread(run_id)
        await restarted.start()
        try:
            run = restarted.get(run_id)
            assert (run.status, run.error.code, run.error.stage) == (
                "failed",
                "shutdown",
                "waiting_for_approval",
            )
            with pytest.raises(ApprovalConflictError):
                await restarted.resolve_approval(run_id, "approve")
        finally:
            await restarted.stop()

    asyncio.run(scenario())


# Crash windows around an acknowledged approval. Once POST /approval returns 202 the
# decision is durable, and no restart or shutdown may turn it into a failure.


def freeze_after_resume(
    runs: RunManager, monkeypatch: pytest.MonkeyPatch
) -> asyncio.Event:
    """The resumed graph finishes, then the process dies before recording the outcome."""
    finished = asyncio.Event()
    drive = runs._drive_graph

    async def frozen(run_id: str, graph_input: Any) -> Any:
        await drive(run_id, graph_input)
        finished.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(runs, "_drive_graph", frozen)
    return finished


def test_a_finished_resume_whose_outcome_was_not_recorded_completes_after_a_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        crashed = manager(fake_llm(WORKFLOW_REPLIES), FakeSandbox())
        await crashed.start()
        run_id = await paused(crashed)
        finished = freeze_after_resume(crashed, monkeypatch)
        await crashed.resolve_approval(run_id, "approve")
        await finished.wait()
        assert stored(run_id).stage == "resuming"

        llm = ScriptedReplies(WORKFLOW_REPLIES)
        sandbox = FakeSandbox()
        restarted = manager(fake_llm(llm), sandbox)
        await restarted.start()
        try:
            run = restarted.get(run_id)
            assert (run.status, run.approval_status, run.error) == (
                "completed",
                "approved",
                None,
            )
            assert not await has_checkpoint(restarted, run_id)
            await asyncio.sleep(0.05)
            assert (llm.calls, sandbox.calls) == ([], [])
        finally:
            await restarted.stop()
            await crashed.stop()

    asyncio.run(scenario())


def test_shutdown_during_a_resume_leaves_the_approval_for_the_next_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        runs = manager(fake_llm(WORKFLOW_REPLIES), FakeSandbox())
        await runs.start()
        run_id = await paused(runs)
        resuming = asyncio.Event()

        async def in_flight(run_id: str, graph_input: Any) -> Any:
            resuming.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(runs, "_drive_graph", in_flight)
        await runs.resolve_approval(run_id, "approve")
        await resuming.wait()

        await runs.stop()

        run = stored(run_id)
        assert (run.status, run.stage, run.approval_status, run.error) == (
            "running",
            "resuming",
            "approved",
            None,
        )
        llm = ScriptedReplies(WORKFLOW_REPLIES)
        sandbox = FakeSandbox()
        restarted = manager(fake_llm(llm), sandbox)
        await restarted.start()
        try:
            done = await run_to_end(restarted, run_id)
        finally:
            await restarted.stop()
        assert (done.status, done.approval_status) == ("completed", "approved")
        assert (llm.calls, sandbox.calls) == ([], [])

    asyncio.run(scenario())


def test_repeated_crashes_while_resuming_complete_the_run_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        first = manager(fake_llm(WORKFLOW_REPLIES), FakeSandbox())
        await first.start()
        run_id = await paused(first)

        # Crash 1: the approval is stored, and the process dies before resuming.
        async def dies_first(run_id: str, graph_input: Any) -> Any:
            await asyncio.Event().wait()

        monkeypatch.setattr(first, "_drive_graph", dies_first)
        await first.resolve_approval(run_id, "approve")

        # Crash 2: the next process resumes, and dies while writing the new checkpoint.
        # (Released only at teardown, so the dead process can drain.)
        llm = ScriptedReplies(WORKFLOW_REPLIES)
        sandbox = FakeSandbox()
        second = manager(fake_llm(llm), sandbox)
        writing, release = asyncio.Event(), asyncio.Event()
        aput = second._graph.checkpointer.aput

        async def dies_writing(*args: Any, **kwargs: Any) -> Any:
            writing.set()
            await release.wait()
            return await aput(*args, **kwargs)

        monkeypatch.setattr(second._graph.checkpointer, "aput", dies_writing)
        await second.start()
        await asyncio.wait_for(writing.wait(), 5)

        third = manager(fake_llm(llm), sandbox)
        await third.start()
        try:
            run = await run_to_end(third, run_id)
            assert (run.status, run.approval_status, run.error) == (
                "completed",
                "approved",
                None,
            )
            # Neither restart repeated any work from before the approval.
            assert (llm.calls, sandbox.calls) == ([], [])
            stored_ids = [r.run_id for r in third._store.with_status(*ALL_STATUSES)]
            assert stored_ids == [run_id]
            assert not await has_checkpoint(third, run_id)
        finally:
            await third.stop()
            release.set()
            await second.stop()
            await first.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("sweep_first", [True, False])
def test_more_time_and_expiry_racing_have_exactly_one_outcome(
    sweep_first: bool,
) -> None:
    async def scenario() -> None:
        clock = Clock()
        runs, _, _ = approval_manager(clock)
        await runs.start()
        try:
            run_id = await paused(runs)
            clock.advance(600)
            sweep = runs.expire_approvals()
            extend = runs.extend_approval(run_id)
            ordered = (sweep, extend) if sweep_first else (extend, sweep)

            results = await asyncio.gather(*ordered, return_exceptions=True)
            run = runs.get(run_id)
            checkpoint = await has_checkpoint(runs, run_id)
        finally:
            await runs.stop()

        swept, extension = results if sweep_first else results[::-1]
        assert isinstance(extension, ApprovalExpiredError)
        assert swept == ([run_id] if sweep_first else [])
        assert (run.status, run.approval_status) == ("expired", "expired")
        assert not checkpoint

    asyncio.run(scenario())


def test_a_storage_error_after_a_run_does_not_stop_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        runs = manager(fake_llm(WORKFLOW_REPLIES), FakeSandbox())
        await runs.start()
        try:
            first = await paused(runs)
            delete = runs._graph.checkpointer.adelete_thread
            failures = [OSError("disk full")]

            async def flaky(thread_id: str) -> None:
                if failures:
                    raise failures.pop()
                await delete(thread_id)

            monkeypatch.setattr(runs._graph.checkpointer, "adelete_thread", flaky)
            await runs.resolve_approval(first, "approve")
            await wait_until(lambda: runs.get(first).status == "completed")

            # With one worker, the next run only gets anywhere if that worker survived.
            assert runs.get(await paused(runs)).status == "waiting_for_approval"
        finally:
            await runs.stop()

    asyncio.run(scenario())


def test_both_databases_keep_committed_writes_through_power_loss() -> None:
    async def scenario() -> None:
        graph, store = storage()
        checkpointer = graph.checkpointer
        await checkpointer.setup()
        try:
            runs = [store._db.execute(f"PRAGMA {p}").fetchone()[0] for p in PRAGMAS]
            checkpoints = []
            for pragma in PRAGMAS:
                async with checkpointer.conn.execute(f"PRAGMA {pragma}") as cursor:
                    checkpoints.append((await cursor.fetchone())[0])
        finally:
            store.close()
            await checkpointer.conn.close()
        # WAL, with synchronous FULL (2): commits are synced, not only ordered.
        assert runs == checkpoints == ["wal", 2]

    asyncio.run(scenario())


PRAGMAS = ("journal_mode", "synchronous")
