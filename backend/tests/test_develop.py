"""DEVELOP, first slice: repository → pinned commit → snapshot → its own tests → evidence.

Every manager here runs on real SQLite in the test's data dir, with GitHub and the sandbox
faked unless a test says otherwise.
"""

import asyncio
import logging
import tarfile
from collections.abc import Mapping
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import get_settings
from app.github import GitHub
from app.graph import build_develop_graph
from app.main import app
from app.runs import Run, RunManager
from app.state import ExecutionResult, GraphContext
from tests.fake_github import REPOSITORY, SAMPLE_FILES, SHA, FakeGitHub, make_archive
from tests.fake_llm import WORKFLOW_REPLIES, ScriptedReplies, fake_llm
from tests.fake_runs import manager_factory, poll, storage, stored
from tests.fake_sandbox import INFRASTRUCTURE_ERROR, TESTS_PASSED, FakeSandbox
from tests.test_github import DOWNLOAD_TOKEN, TOKEN, GitHubApi
from tests.test_runs import wait_until

EXISTING_FAILURES = ExecutionResult(
    status="failed",
    exit_code=1,
    stdout="FAILED tests/test_a.py::test_x - assert 1 == 2\n2 failed, 126 passed in 3.10s\n",
    tests_passed=126,
    tests_failed=2,
    error_type="test_failure",
)
CANT_RUN = ExecutionResult(
    status="failed",
    exit_code=2,
    stdout="E   ModuleNotFoundError: No module named 'requests'\n1 error in 0.10s\n",
    error_type="environment_error",
)
TIMED_OUT = ExecutionResult(status="timed_out", exit_code=137, error_type="timeout")


class HeldSandbox(FakeSandbox):
    """Holds the existing tests until released, so a test can look mid-run."""

    def __init__(self, **options: Any) -> None:
        super().__init__(**options)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run_repository(self, files: Mapping[str, bytes]) -> ExecutionResult:
        self.started.set()
        await self.release.wait()
        return await super().run_repository(files)


def manager(github: Any, sandbox: Any, **options: Any) -> RunManager:
    graph, store = storage()
    return RunManager(
        graph,
        GraphContext(
            llm=fake_llm(ScriptedReplies(WORKFLOW_REPLIES)),
            sandbox=sandbox,
            github=github,
        ),
        store,
        max_active_runs=1,
        max_queued_runs=10,
        max_retained_runs=100,
        run_timeout_seconds=options.pop("run_timeout_seconds", 300),
        approval_timeout_seconds=600,
        develop_graph=build_develop_graph(graph.checkpointer),
        **options,
    )


def finished(runs: RunManager, run_id: str) -> bool:
    return runs.get(run_id).status in ("completed", "failed")


async def develop(runs: RunManager) -> Run:
    """Submit a DEVELOP run and wait for it to end."""
    run_id = runs.submit(
        "Add a subtract function.", "python", "develop", REPOSITORY
    ).run_id
    await wait_until(lambda: finished(runs, run_id))
    return runs.get(run_id)


def run_once(github: Any = None, sandbox: Any = None) -> tuple[Run, Any, Any]:
    github = github or FakeGitHub()
    sandbox = sandbox or FakeSandbox()

    async def scenario() -> Run:
        runs = manager(github, sandbox)
        await runs.start()
        try:
            run = await develop(runs)
            assert runs._context.snapshots == {}
            return run
        finally:
            await runs.stop()

    return asyncio.run(scenario()), github, sandbox


def test_the_default_branch_is_pinned_and_its_existing_tests_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stages: list[str] = []
    update = RunManager._update

    def recording(self: RunManager, run_id: str, **changes: Any) -> None:
        if "stage" in changes:
            stages.append(changes["stage"])
        update(self, run_id, **changes)

    monkeypatch.setattr(RunManager, "_update", recording)
    run, github, sandbox = run_once()

    assert (run.status, run.mode, run.repository, run.error) == (
        "completed",
        "develop",
        REPOSITORY,
        None,
    )
    assert (run.repository_ref.commit_sha, run.repository_ref.default_branch) == (
        SHA,
        "main",
    )
    assert run.existing_tests == TESTS_PASSED
    # The archive was asked for at the pinned commit, and exactly its files were tested.
    assert [ref.commit_sha for ref in github.downloaded] == [SHA]
    assert sandbox.repositories == [SAMPLE_FILES]
    assert stages == ["fetching_repository", "running_existing_tests", "completed"]
    # No SOLVE artifacts, and no model call: this slice never asks the LLM anything.
    assert (run.generated_code, run.generated_tests, run.requirements) == (
        None,
        None,
        None,
    )


def test_failing_existing_tests_are_evidence_not_a_failed_run() -> None:
    run, _, _ = run_once(sandbox=FakeSandbox(repository_result=EXISTING_FAILURES))

    assert (run.status, run.error) == ("completed", None)
    assert (run.existing_tests.tests_passed, run.existing_tests.tests_failed) == (
        126,
        2,
    )
    assert "FAILED tests/test_a.py::test_x" in run.existing_tests.stdout


@pytest.mark.parametrize(
    "result", [CANT_RUN, TIMED_OUT], ids=["missing-dependency", "timeout"]
)
def test_tests_that_cannot_run_here_fail_clearly_and_keep_the_details(
    result: ExecutionResult,
) -> None:
    run, _, _ = run_once(sandbox=FakeSandbox(repository_result=result))

    assert run.status == "failed"
    assert (run.error.code, run.error.stage) == (
        "environment_unsupported",
        "running_existing_tests",
    )
    assert (
        run.error.message
        == "AstraAi couldn't run this repository in its current environment."
    )
    # The technical details stay on the run for the run log.
    assert run.existing_tests == result


def test_an_unavailable_sandbox_is_not_blamed_on_the_repository() -> None:
    noisy = INFRASTRUCTURE_ERROR.model_copy(update={"stderr": "docker daemon detail"})
    run, _, _ = run_once(sandbox=FakeSandbox(repository_result=noisy))

    assert (run.status, run.error.code) == ("failed", "sandbox_unavailable")
    assert run.existing_tests.stderr == ""


@pytest.mark.parametrize(
    "code", ["repository_not_public", "repository_not_found", "github_unavailable"]
)
def test_github_problems_stop_before_anything_runs(code: str) -> None:
    run, _, sandbox = run_once(github=FakeGitHub(error=code))

    assert run.status == "failed"
    assert (run.error.code, run.error.stage) == (code, "fetching_repository")
    assert sandbox.repositories == []


def test_an_unsafe_archive_stops_before_anything_runs() -> None:
    link = tarfile.TarInfo("octo-sample-aaaaaaa/evil")
    link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
    github = FakeGitHub(archive=make_archive(SAMPLE_FILES, extra=[link]))

    run, _, sandbox = run_once(github=github)

    assert (run.status, run.error.code) == ("failed", "repository_unsupported")
    assert sandbox.repositories == []


def test_the_snapshot_exists_only_while_the_run_works() -> None:
    async def scenario() -> None:
        sandbox = HeldSandbox()
        runs = manager(FakeGitHub(), sandbox)
        await runs.start()
        try:
            run_id = runs.submit("task", "python", "develop", REPOSITORY).run_id
            await asyncio.wait_for(sandbox.started.wait(), 5)
            assert runs._context.snapshots == {run_id: SAMPLE_FILES}
            sandbox.release.set()
            await wait_until(lambda: finished(runs, run_id))
            assert runs._context.snapshots == {}
        finally:
            await runs.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("ending", ["shutdown", "run_timeout", "sandbox_raises"])
def test_the_snapshot_is_dropped_however_the_run_ends(ending: str) -> None:
    async def scenario() -> None:
        sandbox = (
            FakeSandbox(repository_result=RuntimeError("boom"))
            if ending == "sandbox_raises"
            else HeldSandbox()
        )
        options = {"run_timeout_seconds": 0.5} if ending == "run_timeout" else {}
        runs = manager(FakeGitHub(), sandbox, **options)
        await runs.start()
        run_id = runs.submit("task", "python", "develop", REPOSITORY).run_id
        if ending == "shutdown":
            await asyncio.wait_for(sandbox.started.wait(), 5)
            await runs.stop()
            assert stored(run_id).error.code == "shutdown"
        else:
            await wait_until(lambda: finished(runs, run_id))
            code = runs.get(run_id).error.code
            await runs.stop()
            assert code == (
                "run_timeout" if ending == "run_timeout" else "internal_error"
            )
        assert runs._context.snapshots == {}

    asyncio.run(scenario())


def data_bytes() -> bytes:
    """Every byte AstraAi has persisted: both databases and their write-ahead logs."""
    return b"".join(path.read_bytes() for path in get_settings().data_dir.iterdir())


def test_the_token_and_the_files_never_reach_state_checkpoints_logs_or_sandbox(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    marker = b"UNIQUE_FILE_CONTENT_" * 3
    api = GitHubApi(archive=make_archive({**SAMPLE_FILES, "big.py": marker}))

    async def scenario() -> tuple[bytes, Run, HeldSandbox]:
        sandbox = HeldSandbox()
        provider = GitHub(
            SecretStr(TOKEN), httpx2.AsyncClient(transport=httpx2.MockTransport(api))
        )
        runs = manager(provider, sandbox)
        await runs.start()
        try:
            run_id = runs.submit("task", "python", "develop", "octo/sample").run_id
            await asyncio.wait_for(sandbox.started.wait(), 5)
            # Mid-run the checkpoint holds the state after prepare_repository.
            assert (
                await runs._graph.aget_state({"configurable": {"thread_id": run_id}})
            ).values
            during = data_bytes()
            sandbox.release.set()
            await wait_until(lambda: finished(runs, run_id))
            return during, runs.get(run_id), sandbox
        finally:
            await runs.stop()
            await provider.close()

    during, run, sandbox = asyncio.run(scenario())
    after = data_bytes()

    assert run.status == "completed"
    for secret in (TOKEN.encode(), DOWNLOAD_TOKEN.encode()):
        assert secret not in during and secret not in after
        assert secret.decode() not in caplog.text
        assert secret.decode() not in run.model_dump_json()
        assert all(
            secret not in content
            for files in sandbox.repositories
            for content in files.values()
        )
    # The repository's files stay in memory: never in the state or a checkpoint.
    assert marker not in during and marker not in after
    assert sandbox.repositories[0]["big.py"] == marker


def test_completed_and_failed_develop_runs_survive_a_restart() -> None:
    async def scenario() -> None:
        runs = manager(FakeGitHub(), FakeSandbox(repository_result=EXISTING_FAILURES))
        await runs.start()
        try:
            completed = await develop(runs)
        finally:
            await runs.stop()
        runs = manager(FakeGitHub(), FakeSandbox(repository_result=CANT_RUN))
        await runs.start()
        try:
            failed = await develop(runs)
        finally:
            await runs.stop()

        github = FakeGitHub()
        sandbox = FakeSandbox()
        restarted = manager(github, sandbox)
        await restarted.start()
        try:
            assert restarted.get(completed.run_id) == completed
            assert restarted.get(failed.run_id) == failed
            await asyncio.sleep(0.05)
            # Finished runs are only read back: nothing is fetched or run again.
            assert (github.resolved, sandbox.repositories) == ([], [])
        finally:
            await restarted.stop()

    asyncio.run(scenario())


def test_a_develop_run_caught_by_a_crash_fails_and_is_never_repeated() -> None:
    async def scenario() -> None:
        sandbox = HeldSandbox()
        crashed = manager(FakeGitHub(), sandbox)
        await crashed.start()
        run_id = crashed.submit("task", "python", "develop", REPOSITORY).run_id
        await asyncio.wait_for(sandbox.started.wait(), 5)

        github = FakeGitHub()
        fresh = FakeSandbox()
        restarted = manager(github, fresh)
        await restarted.start()
        try:
            run = restarted.get(run_id)
            assert (run.status, run.error.code, run.error.stage) == (
                "failed",
                "shutdown",
                "running_existing_tests",
            )
            assert run.repository_ref.commit_sha == SHA
            await asyncio.sleep(0.05)
            assert (github.resolved, fresh.repositories) == ([], [])
            assert restarted._context.snapshots == {}
        finally:
            await restarted.stop()
            await crashed.stop()

    asyncio.run(scenario())


# The API: DEVELOP is SOLVE's endpoint with a mode and a repository.


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        "app.main.build_run_manager", manager_factory(github=FakeGitHub)
    )
    return TestClient(app)


def test_a_develop_run_over_http(api: TestClient) -> None:
    with api as client:
        accepted = client.post(
            "/runs",
            json={
                "task": "Add a subtract function.",
                "language": "python",
                "mode": "develop",
                "repository": "https://github.com/octo/sample.git",
            },
        )
        assert accepted.status_code == 202
        run = poll(
            client, accepted.json()["run_id"], lambda r: r["status"] == "completed"
        )

    assert (run["mode"], run["repository"]) == ("develop", "octo/sample")
    assert run["repository_ref"]["commit_sha"] == SHA
    assert run["existing_tests"]["tests_passed"] == 1


def field_error(response: Any) -> tuple[str, str]:
    [error] = response.json()["detail"]
    return ".".join(map(str, error["loc"])), error["msg"]


@pytest.mark.parametrize(
    ("body", "field", "message"),
    [
        (
            {"repository": "https://gitlab.com/octo/sample"},
            "body.repository",
            "Enter a GitHub repository, like https://github.com/owner/name.",
        ),
        (
            {"repository": "https://github.com/octo/sample/tree/main"},
            "body.repository",
            "Enter a GitHub repository, like https://github.com/owner/name.",
        ),
        ({}, "body", "Enter a GitHub repository."),
        (
            {"repository": "octo/sample", "language": "cpp"},
            "body",
            "Develop works with Python repositories.",
        ),
    ],
)
def test_develop_requests_are_validated_before_anything_is_fetched(
    api: TestClient, body: dict[str, str], field: str, message: str
) -> None:
    with api as client:
        response = client.post(
            "/runs", json={"task": "t", "language": "python", "mode": "develop", **body}
        )

    assert response.status_code == 422
    assert field_error(response) == (field, message)


def test_a_solve_request_cannot_carry_a_repository(api: TestClient) -> None:
    with api as client:
        response = client.post(
            "/runs",
            json={"task": "t", "language": "python", "repository": "octo/sample"},
        )

    assert response.status_code == 422
    assert field_error(response) == ("body", "Only Develop runs take a repository.")


def test_solve_runs_are_unchanged_and_carry_no_develop_state(api: TestClient) -> None:
    with api as client:
        run_id = client.post(
            "/runs", json={"task": "Reverse a string.", "language": "python"}
        ).json()["run_id"]
        run = poll(client, run_id, lambda r: r["status"] == "waiting_for_approval")

    assert (
        run["mode"],
        run["repository"],
        run["repository_ref"],
        run["existing_tests"],
    ) == (
        "solve",
        None,
        None,
        None,
    )
