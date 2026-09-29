import asyncio
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.sandbox.docker import DockerSandbox, parse_state
from app.sandbox.executor import LANGUAGES
from app.state import ExecutionResult, GeneratedCode, GraphContext
from tests.fake_llm import (
    VALID_CPP_CODE,
    VALID_PYTHON_CODE,
    WORKFLOW_REPLIES,
    ScriptedReplies,
    fake_llm,
)
from tests.fake_sandbox import FakeDockerCli
from tests.graph_runs import checkpointed_graph, start

PYTHON_CODE = GeneratedCode.model_validate(VALID_PYTHON_CODE)
CPP_CODE = GeneratedCode.model_validate(VALID_CPP_CODE)
FAILING_OUTPUT = (
    b"FAIL basic_word: expected cba, got abc\nFAIL empty_string: expected , got x\n"
)


def execute(
    cli: FakeDockerCli,
    monkeypatch: pytest.MonkeyPatch,
    code: GeneratedCode = PYTHON_CODE,
    **overrides: Any,
) -> ExecutionResult:
    monkeypatch.setattr("app.sandbox.docker.asyncio.create_subprocess_exec", cli)
    sandbox = DockerSandbox(Settings(**overrides))
    return asyncio.run(sandbox.execute(code))


def test_python_success(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = FakeDockerCli(stdout=b"PASSED 3 tests\n", exit_code=0)

    result = execute(cli, monkeypatch)

    assert result.status == "passed"
    assert (result.exit_code, result.tests_passed, result.tests_failed) == (0, 3, 0)
    assert result.error_type is None
    assert result.stdout == "PASSED 3 tests\n"
    assert result.duration_ms >= 0
    assert cli.archive_names() == ["solution.py", "test_solution.py"]
    assert [command[1] for command in cli.commands] == [
        "create",
        "start",
        "inspect",
        "rm",
    ]


def test_python_failing_test(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = FakeDockerCli(stdout=FAILING_OUTPUT, exit_code=1)

    result = execute(cli, monkeypatch)

    assert result.status == "failed"
    assert result.error_type == "test_failure"
    assert (result.exit_code, result.tests_failed, result.tests_passed) == (1, 2, None)


def test_runtime_failure_without_failing_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = FakeDockerCli(stderr=b"Traceback: NameError\n", exit_code=1)

    result = execute(cli, monkeypatch)

    assert result.status == "failed"
    assert result.error_type == "runtime_error"
    assert "NameError" in result.stderr


def test_cpp_success_uses_the_compiler_image(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = FakeDockerCli(stdout=b"PASSED 1 tests\n", exit_code=0)

    result = execute(cli, monkeypatch, CPP_CODE)

    assert result.status == "passed"
    assert cli.archive_names() == ["solution.cpp", "test_solution.cpp"]
    create = cli.ran("create")[0]
    assert "gcc:13" in create
    assert "g++ -std=c++17 -O1 test_solution.cpp -o /sandbox/tests" in create[-1]
    assert "tar -x" in create[-1]


def test_cpp_compile_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = FakeDockerCli(stderr=b"error: expected ';'\n", exit_code=90)

    result = execute(cli, monkeypatch, CPP_CODE)

    assert result.status == "failed"
    assert result.error_type == "compile_error"
    assert result.exit_code == 90
    # Compiler output is the program's output and stays visible.
    assert result.stderr == "error: expected ';'\n"


def test_timeout_kills_the_container(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = FakeDockerCli(stdout=b"working\n", stderr=b"still going\n", hang=True)

    result = execute(cli, monkeypatch, sandbox_timeout_seconds=0.05)

    assert result.status == "timed_out"
    assert result.error_type == "timeout"
    # Output the program produced before the limit is still program output.
    assert (result.stdout, result.stderr) == ("working\n", "still going\n")
    assert cli.ran("kill")
    assert cli.ran("rm")


def test_output_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = FakeDockerCli(stdout=b"x" * 5000, exit_code=0)

    result = execute(cli, monkeypatch, sandbox_max_output_bytes=1000)

    assert len(result.stdout) == 1000
    assert result.output_truncated is True


def test_out_of_memory_is_a_resource_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = FakeDockerCli(stderr=b"allocating\n", exit_code=137, out_of_memory=True)

    result = execute(cli, monkeypatch)

    assert result.status == "resource_exceeded"
    assert result.error_type == "out_of_memory"
    assert result.stderr == "allocating\n"


@pytest.mark.parametrize(
    ("failing", "error_type"),
    [
        pytest.param("create", "container_create_failed", id="create-fails"),
    ],
)
def test_docker_failures_are_infrastructure_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failing: str,
    error_type: str,
) -> None:
    cli = FakeDockerCli(failing=(failing,))

    result = execute(cli, monkeypatch)

    assert result.status == "infrastructure_error"
    assert result.error_type == error_type
    # Docker's diagnostics are logged for operators but never returned as output.
    assert (result.stdout, result.stderr) == ("", "")
    assert "docker refused" not in result.model_dump_json()
    assert "docker refused" in caplog.text
    assert not cli.ran("start")
    assert cli.ran("rm")


def test_missing_docker_cli_is_an_infrastructure_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def missing(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("docker")

    monkeypatch.setattr("app.sandbox.docker.asyncio.create_subprocess_exec", missing)
    sandbox = DockerSandbox(Settings())

    result = asyncio.run(sandbox.execute(PYTHON_CODE))

    assert result.status == "infrastructure_error"
    assert result.exit_code == 127
    assert (result.stdout, result.stderr) == ("", "")
    assert "docker CLI unavailable" not in result.model_dump_json()


@pytest.mark.parametrize(
    ("code", "message"),
    [
        pytest.param(
            GeneratedCode.model_construct(
                language="rust", solution_code="fn main() {}", test_code="x"
            ),
            "unsupported sandbox language",
            id="unsupported-language",
        ),
        pytest.param(
            GeneratedCode.model_construct(
                language="python", solution_code="   ", test_code="x"
            ),
            "solution code is empty",
            id="empty-solution",
        ),
        pytest.param(
            GeneratedCode.model_construct(
                language="python", solution_code="x", test_code="  \n"
            ),
            "test code is empty",
            id="empty-tests",
        ),
    ],
)
def test_validation_happens_before_any_container(
    monkeypatch: pytest.MonkeyPatch, code: GeneratedCode, message: str
) -> None:
    cli = FakeDockerCli()
    monkeypatch.setattr("app.sandbox.docker.asyncio.create_subprocess_exec", cli)
    sandbox = DockerSandbox(Settings())

    with pytest.raises(ValueError, match=message):
        asyncio.run(sandbox.execute(code))

    assert cli.commands == []


@pytest.mark.parametrize(
    "cli",
    [
        pytest.param(FakeDockerCli(stdout=b"PASSED 1 tests\n"), id="success"),
        pytest.param(FakeDockerCli(exit_code=1), id="test-failure"),
        pytest.param(FakeDockerCli(failing=("create",)), id="infrastructure-failure"),
        pytest.param(FakeDockerCli(hang=True), id="timeout"),
    ],
)
def test_container_and_workspace_are_always_cleaned_up(
    monkeypatch: pytest.MonkeyPatch, cli: FakeDockerCli
) -> None:
    execute(cli, monkeypatch, sandbox_timeout_seconds=0.05)

    removals = cli.ran("rm")
    assert len(removals) == 1
    assert removals[0][2:4] == ["--force", "--volumes"]
    assert removals[0][-1].startswith("astraai-sandbox-")


def test_only_docker_is_ever_executed(monkeypatch: pytest.MonkeyPatch) -> None:
    cli = FakeDockerCli(stdout=b"PASSED 1 tests\n")

    execute(cli, monkeypatch)

    # FakeDockerCli asserts the program is docker; this pins the whole command list.
    assert {command[0] for command in cli.commands} == {"docker"}
    assert all("python" not in command[1] for command in cli.commands)


@pytest.mark.parametrize("language", ["python", "cpp"])
def test_container_is_locked_down(language: str) -> None:
    sandbox = DockerSandbox(Settings())

    args = sandbox.container_args("astraai-sandbox-test", LANGUAGES[language], language)

    assert args[0] == "create"
    assert "--interactive" in args
    for flag, value in [
        ("--network", "none"),
        ("--user", "65534:65534"),
        ("--security-opt", "no-new-privileges"),
        ("--cap-drop", "ALL"),
        ("--pids-limit", "64"),
        ("--cpus", "1.0"),
        ("--memory", "512m"),
        ("--memory-swap", "512m"),
        ("--workdir", "/sandbox"),
    ]:
        assert args[args.index(flag) + 1] == value
    assert "--read-only" in args
    assert "--privileged" not in args
    assert not {"-v", "--volume", "--mount"} & set(args)
    assert not any("docker.sock" in argument for argument in args)
    tmpfs = args[args.index("--tmpfs") + 1]
    assert tmpfs.startswith("/sandbox:")
    assert ("exec" in tmpfs and "noexec" not in tmpfs) is (language == "cpp")
    assert "size=64m" in tmpfs


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"sandbox_memory_mb": 16}, id="memory-too-small"),
        pytest.param({"sandbox_memory_mb": 4096}, id="memory-too-large"),
        pytest.param({"sandbox_cpu_limit": 0}, id="no-cpu"),
        pytest.param({"sandbox_cpu_limit": 8}, id="cpu-too-large"),
        pytest.param({"sandbox_pids_limit": 4}, id="pids-too-small"),
        pytest.param({"sandbox_timeout_seconds": 0}, id="no-timeout"),
        pytest.param({"sandbox_timeout_seconds": 600}, id="timeout-too-long"),
        pytest.param({"sandbox_max_output_bytes": 10}, id="output-too-small"),
        pytest.param({"sandbox_max_concurrency": 0}, id="no-concurrency"),
        pytest.param({"sandbox_python_image": ""}, id="empty-image"),
    ],
)
def test_sandbox_settings_reject_unsafe_values(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Settings(**overrides)


def test_sandbox_defaults_are_conservative() -> None:
    settings = Settings()

    assert settings.sandbox_max_concurrency == 1
    assert settings.sandbox_cpu_limit == 1.0
    assert settings.sandbox_memory_mb == 512
    assert settings.sandbox_pids_limit == 64
    assert settings.sandbox_timeout_seconds == 30


def test_cancellation_mid_execution_removes_the_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = FakeDockerCli(hang=True)
    monkeypatch.setattr("app.sandbox.docker.asyncio.create_subprocess_exec", cli)

    async def scenario() -> None:
        sandbox = DockerSandbox(Settings(sandbox_timeout_seconds=60))
        execution = asyncio.create_task(sandbox.execute(PYTHON_CODE))
        while not cli.ran("start"):
            await asyncio.sleep(0.005)

        execution.cancel()
        with pytest.raises(asyncio.CancelledError):
            await execution

    asyncio.run(scenario())

    name = cli.ran("create")[0][cli.ran("create")[0].index("--name") + 1]
    assert cli.commands[-1] == ["docker", "rm", "--force", "--volumes", name]
    assert cli._started.killed
    assert not cli.ran("inspect")  # No result is built for a cancelled execution.


@pytest.mark.parametrize(
    "cli",
    [
        pytest.param(FakeDockerCli(failing=("create",)), id="create-fails"),
        pytest.param(
            FakeDockerCli(stderr=b"docker refused", exit_code=127, never_started=True),
            id="start-fails",
        ),
    ],
)
def test_infrastructure_diagnostics_never_reach_the_model_or_state_across_a_retry(
    monkeypatch: pytest.MonkeyPatch, cli: FakeDockerCli
) -> None:
    monkeypatch.setattr("app.sandbox.docker.asyncio.create_subprocess_exec", cli)
    llm = ScriptedReplies(WORKFLOW_REPLIES)
    context = GraphContext(llm=fake_llm(llm), sandbox=DockerSandbox(Settings()))
    initial = {"run_id": "run-1", "task": "Reverse a string.", "language": "python"}

    state = asyncio.run(start(checkpointed_graph(), initial, context))

    # Both attempts hit the infrastructure failure: first execution plus one retry.
    assert len(cli.ran("create")) == 2
    assert state["execution_retry_count"] == 1
    assert state["execution_result"].status == "infrastructure_error"
    assert (state["execution_result"].stdout, state["execution_result"].stderr) == (
        "",
        "",
    )
    # The critic judged it deterministically; no prompt ever carried Docker output.
    assert "CriticResult" not in llm.calls
    assert not any("docker refused" in prompt for prompt in llm.prompts)


DAEMON_ERROR = (
    b"Error response from daemon: failed to create task for container: OCI runtime "
    b"create failed: unable to find user nobody-here: no matching entries in passwd file"
)


@pytest.mark.parametrize(
    ("cli", "error_type"),
    [
        pytest.param(
            FakeDockerCli(stderr=DAEMON_ERROR, exit_code=127, never_started=True),
            "container_start_failed",
            id="start-fails",
        ),
        pytest.param(
            FakeDockerCli(
                stdout=b"PASSED 3 tests\n",
                stderr=DAEMON_ERROR,
                failing=("inspect",),
            ),
            "container_inspect_failed",
            id="inspect-fails",
        ),
        pytest.param(
            FakeDockerCli(
                stdout=b"partial\n",
                stderr=b"error waiting for container: unexpected EOF",
                exit_code=0,
                still_running=True,
            ),
            "container_attach_failed",
            id="attach-ends-while-running",
        ),
    ],
)
def test_docker_start_inspect_and_attach_failures_are_infrastructure_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    cli: FakeDockerCli,
    error_type: str,
) -> None:
    result = execute(cli, monkeypatch)

    assert (result.status, result.error_type) == ("infrastructure_error", error_type)
    assert (result.stdout, result.stderr) == ("", "")
    assert result.tests_passed is None
    for docker_text in ("daemon", "OCI", "error waiting", "docker refused"):
        assert docker_text not in result.model_dump_json()
    assert error_type in caplog.text
    assert cli.ran("rm")


def test_a_program_exiting_127_is_still_a_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Same exit code Docker reports for a failed start, but the process did run.
    cli = FakeDockerCli(stderr=b"sh: 1: nonexistent_cmd: not found\n", exit_code=127)

    result = execute(cli, monkeypatch)

    assert (result.status, result.error_type) == ("failed", "runtime_error")
    assert result.stderr == "sh: 1: nonexistent_cmd: not found\n"


@pytest.mark.parametrize(
    "inspected",
    ["", "0 false", "x false false 2026-01-01T00:00:00Z", "0 false false a b"],
)
def test_unexpected_inspect_output_is_rejected(inspected: str) -> None:
    assert parse_state(inspected) is None


def test_inspect_output_is_parsed() -> None:
    state = parse_state("137 true false 0001-01-01T00:00:00Z\n")

    assert state is not None
    assert (state.exit_code, state.out_of_memory, state.running, state.started) == (
        137,
        True,
        False,
        False,
    )


def remove_leftovers(cli: FakeDockerCli, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.sandbox.docker.asyncio.create_subprocess_exec", cli)
    asyncio.run(DockerSandbox(Settings()).remove_leftovers())


def test_leftover_containers_from_an_earlier_process_are_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = FakeDockerCli(listed=b"3f2a9c1b0d4e\n7b1c2d3e4f5a\n")

    remove_leftovers(cli, monkeypatch)

    assert cli.ran("ps") == [
        ["docker", "ps", "--all", "--quiet", "--filter", "name=^/astraai-sandbox-"]
    ]
    assert cli.ran("rm") == [
        ["docker", "rm", "--force", "--volumes", "3f2a9c1b0d4e", "7b1c2d3e4f5a"]
    ]
    assert cli.ran("start") == []  # Removed, never continued.


@pytest.mark.parametrize("cli", [FakeDockerCli(), FakeDockerCli(failing=("ps",))])
def test_nothing_is_removed_without_leftovers_or_a_listing(
    monkeypatch: pytest.MonkeyPatch, cli: FakeDockerCli
) -> None:
    remove_leftovers(cli, monkeypatch)

    assert cli.ran("rm") == []
