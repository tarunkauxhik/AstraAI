import asyncio
from collections.abc import Callable

import pytest

from app.config import Settings
from app.graph import build_graph
from app.llm import LLMClient, LLMError, LLMTimeoutError
from app.runs import (
    NODE_STAGES,
    QueueFullError,
    Run,
    RunManager,
    RunManagerStoppedError,
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
    VALID_CRITIC_RESULT,
    VALID_GENERATED_TESTS,
    VALID_PYTHON_CODE,
    VALID_REQUIREMENTS,
    WORKFLOW_REPLIES,
    fake_llm,
    timeout,
)
from tests.fake_runs import Gates, hold_forever
from tests.fake_sandbox import PASSED, FakeDockerCli, FakeSandbox


def manager(
    llm: LLMClient,
    sandbox: SandboxExecutor,
    *,
    max_queued_runs: int = 10,
    max_retained_runs: int = 100,
    run_timeout_seconds: float = 300,
) -> RunManager:
    return RunManager(
        build_graph(),
        GraphContext(llm=llm, sandbox=sandbox),
        max_active_runs=1,
        max_queued_runs=max_queued_runs,
        max_retained_runs=max_retained_runs,
        run_timeout_seconds=run_timeout_seconds,
    )


async def wait_until(condition: Callable[[], bool], timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        if loop.time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.005)


async def run_to_end(runs: RunManager, run_id: str) -> Run:
    await wait_until(lambda: runs.get(run_id).status in ("completed", "failed"))
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
        finally:
            await runs.stop()

        assert len(sandbox.calls) == 1
        assert runs.enqueue(run_id) is False
        assert runs.enqueue("unknown") is False

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


def test_failing_generated_tests_still_complete_the_run() -> None:
    failing = ExecutionResult(
        status="failed",
        exit_code=1,
        stdout="FAIL basic_word: expected cba, got abc\n",
        tests_failed=1,
        error_type="test_failure",
    )

    run = asyncio.run(single_run(fake_llm(WORKFLOW_REPLIES), FakeSandbox(failing)))

    assert (run.status, run.stage, run.error) == ("completed", "completed", None)
    assert run.execution_result == failing


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


def test_every_graph_node_has_a_stage() -> None:
    nodes = set(build_graph().get_graph().nodes) - {"__start__", "__end__"}

    assert nodes == set(NODE_STAGES)


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
        return runs.get(active), runs.get(waiting)

    active, waiting = asyncio.run(scenario())

    assert (active.status, active.error.code, active.error.stage) == (
        "failed",
        "shutdown",
        "executing",
    )
    assert (waiting.status, waiting.error.code, waiting.error.stage) == (
        "failed",
        "shutdown",
        "queued",
    )
    assert len(cli.ran("create")) == 1  # The waiting run never started a container.
    assert cli._started.killed
