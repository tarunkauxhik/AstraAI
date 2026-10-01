"""Opt-in checks that use the real local Docker daemon.

Run with ASTRAAI_DOCKER_TESTS=1. Never part of the normal test run.
"""

import asyncio
import os
import subprocess
from pathlib import Path

import pytest

from app.config import Settings
from app.runs import RunManager
from app.sandbox.docker import DockerSandbox
from app.state import ExecutionResult, GeneratedCode, GraphContext
from tests.fake_llm import WORKFLOW_REPLIES, fake_llm
from tests.fake_runs import storage, stored

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.getenv("ASTRAAI_DOCKER_TESTS") != "1",
        reason="set ASTRAAI_DOCKER_TESTS=1 to use the local Docker daemon",
    ),
]

TRIVIAL_SOLUTION = "def solve():\n    return 1\n"


def python_code(test_code: str, solution: str = TRIVIAL_SOLUTION) -> GeneratedCode:
    return GeneratedCode(
        language="python",
        solution_code=solution,
        test_code=test_code,
        explanation="integration fixture",
    )


def cpp_code(test_code: str, solution: str) -> GeneratedCode:
    return GeneratedCode(
        language="cpp",
        solution_code=solution,
        test_code=test_code,
        explanation="integration fixture",
    )


def run(code: GeneratedCode, **overrides: object) -> ExecutionResult:
    sandbox = DockerSandbox(Settings(**overrides))
    return asyncio.run(sandbox.execute(code))


def sandbox_containers() -> list[str]:
    listed = subprocess.run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            "name=astraai-sandbox-",
            "--format",
            "{{.Names}}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return [name for name in listed.stdout.splitlines() if name.strip()]


def probe(body: str) -> ExecutionResult:
    """Run a Python snippet that exits 0 only when the restriction holds."""
    return run(python_code(body))


def test_python_success() -> None:
    result = run(
        python_code(
            "from solution import solve\n"
            "import sys\n"
            "if solve() != 1:\n"
            "    print('FAIL solve: expected 1')\n"
            "    sys.exit(1)\n"
            "print('PASSED 1 tests')\n"
        )
    )

    assert result.status == "passed"
    assert (result.exit_code, result.tests_passed, result.tests_failed) == (0, 1, 0)
    assert "PASSED 1 tests" in result.stdout


def test_python_failing_test() -> None:
    result = run(
        python_code(
            "import sys\nprint('FAIL basic_case: expected 2, got 1')\nsys.exit(1)\n"
        )
    )

    assert result.status == "failed"
    assert result.error_type == "test_failure"
    assert (result.exit_code, result.tests_failed) == (1, 1)


def test_python_runtime_error() -> None:
    result = run(python_code("raise RuntimeError('boom')\n"))

    assert result.status == "failed"
    assert result.error_type == "runtime_error"
    assert "RuntimeError" in result.stderr


def test_timeout_is_terminated() -> None:
    before = sandbox_containers()

    result = run(python_code("while True:\n    pass\n"), sandbox_timeout_seconds=3)

    assert result.status == "timed_out"
    assert result.error_type == "timeout"
    assert result.duration_ms >= 2500
    assert sandbox_containers() == before


def test_output_is_capped() -> None:
    result = run(
        python_code("for _ in range(200000):\n    print('noise' * 20)\n"),
        sandbox_max_output_bytes=5000,
        sandbox_timeout_seconds=30,
    )

    assert len(result.stdout) <= 5000
    assert result.output_truncated is True


CPP_SOLUTION = r"""int add(int a, int b) {
    return a + b;
}
"""

CPP_TEST = r"""#include "solution.cpp"
#include <iostream>

int main() {
    if (add(2, 3) != 5) {
        std::cout << "FAIL add: expected 5\n";
        return 1;
    }
    std::cout << "PASSED 1 tests\n";
    return 0;
}
"""

CPP_BROKEN_TEST = r"""#include "solution.cpp"

int main() { return add(1 2); }
"""


def test_a_container_that_cannot_start_hides_docker_diagnostics() -> None:
    # A user unknown to the image makes the OCI runtime refuse to start the process.
    before = sandbox_containers()

    result = run(
        python_code("print('PASSED 1 tests')\n"), sandbox_user="astraai-no-such-user"
    )

    assert (result.status, result.error_type) == (
        "infrastructure_error",
        "container_start_failed",
    )
    assert (result.stdout, result.stderr) == ("", "")
    assert "daemon" not in result.model_dump_json()
    assert sandbox_containers() == before


def test_cpp_success() -> None:
    result = run(cpp_code(CPP_TEST, CPP_SOLUTION), sandbox_timeout_seconds=120)

    assert result.status == "passed", result.stderr
    assert result.tests_passed == 1
    assert "PASSED 1 tests" in result.stdout


def test_cpp_compile_failure() -> None:
    result = run(cpp_code(CPP_BROKEN_TEST, CPP_SOLUTION), sandbox_timeout_seconds=120)

    assert result.status == "failed"
    assert result.error_type == "compile_error"
    assert result.exit_code == 90
    assert "error" in result.stderr.lower()


def test_network_is_unavailable() -> None:
    result = probe(
        "import socket, sys\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 80), timeout=3)\n"
        "except OSError:\n"
        "    print('PASSED 1 tests')\n"
        "    sys.exit(0)\n"
        "print('FAIL network: the sandbox reached the internet')\n"
        "sys.exit(1)\n"
    )

    assert result.status == "passed", result.stdout


def test_process_is_not_root() -> None:
    result = probe(
        "import os, sys\n"
        "uid = os.geteuid()\n"
        "if uid == 0:\n"
        "    print('FAIL user: running as root')\n"
        "    sys.exit(1)\n"
        "print(f'uid={uid}')\n"
        "print('PASSED 1 tests')\n"
    )

    assert result.status == "passed", result.stdout
    assert "uid=65534" in result.stdout


def test_root_filesystem_and_workspace_are_read_only() -> None:
    result = probe(
        "import sys\n"
        "for path in ('/root_probe', '/workspace/probe.txt', '/usr/probe'):\n"
        "    try:\n"
        "        open(path, 'w').write('x')\n"
        "    except OSError:\n"
        "        continue\n"
        "    print(f'FAIL readonly: wrote {path}')\n"
        "    sys.exit(1)\n"
        "print('PASSED 1 tests')\n"
    )

    assert result.status == "passed", result.stdout


def test_docker_socket_and_host_mounts_are_absent() -> None:
    result = probe(
        "import os, sys\n"
        "mounts = open('/proc/mounts').read()\n"
        "if os.path.exists('/var/run/docker.sock'):\n"
        "    print('FAIL socket: docker socket is visible')\n"
        "    sys.exit(1)\n"
        "marks = ('docker.sock', '/run/desktop/mnt/host', '/host_mnt')\n"
        "if any(mark in mounts for mark in marks):\n"
        "    print('FAIL mounts: host path mounted')\n"
        "    sys.exit(1)\n"
        "root = [line for line in mounts.splitlines() if line.split()[1] == '/'][0]\n"
        "if ' ro,' not in root:\n"
        "    print('FAIL rootfs: root filesystem is writable')\n"
        "    sys.exit(1)\n"
        "print('PASSED 1 tests')\n"
    )

    assert result.status == "passed", result.stdout


def test_cgroup_limits_are_applied() -> None:
    result = probe(
        "import sys\n"
        "def read(path):\n"
        "    try:\n"
        "        return open(path).read().strip()\n"
        "    except OSError:\n"
        "        return 'unreadable'\n"
        "print('memory', read('/sys/fs/cgroup/memory.max'))\n"
        "print('pids', read('/sys/fs/cgroup/pids.max'))\n"
        "print('cpu', read('/sys/fs/cgroup/cpu.max'))\n"
        "print('PASSED 1 tests')\n"
    )

    assert result.status == "passed", result.stdout
    assert "memory 536870912" in result.stdout
    assert "pids 64" in result.stdout
    assert "cpu 100000 100000" in result.stdout


def test_privilege_escalation_is_blocked() -> None:
    result = probe(
        "import os, subprocess, sys\n"
        "status = open('/proc/self/status').read()\n"
        "if 'NoNewPrivs:\t1' not in status:\n"
        "    print('FAIL no-new-privileges: flag not set')\n"
        "    sys.exit(1)\n"
        "try:\n"
        "    os.setuid(0)\n"
        "except OSError:\n"
        "    print('PASSED 1 tests')\n"
        "    sys.exit(0)\n"
        "print('FAIL setuid: became root')\n"
        "sys.exit(1)\n"
    )

    assert result.status == "passed", result.stdout


def test_repeated_runs_leave_nothing_behind() -> None:
    before = sandbox_containers()

    for _ in range(3):
        run(python_code("print('PASSED 1 tests')\n"))
    run(python_code("import sys\nsys.exit(1)\n"))
    run(python_code("while True:\n    pass\n"), sandbox_timeout_seconds=2)

    assert sandbox_containers() == before


INFINITE_LOOP_CODE = GeneratedCode(
    language="python",
    solution_code=TRIVIAL_SOLUTION,
    test_code="while True:\n    pass\n",
    explanation="never finishes",
)


def looping_run_manager(run_timeout_seconds: float) -> RunManager:
    """A run manager whose workflow generates code that loops forever, on real Docker."""
    replies = {
        **WORKFLOW_REPLIES,
        "GeneratedCode": INFINITE_LOOP_CODE.model_dump_json(),
    }
    graph, store = storage()
    return RunManager(
        graph,
        GraphContext(
            llm=fake_llm(replies),
            sandbox=DockerSandbox(Settings(sandbox_timeout_seconds=120)),
        ),
        store,
        max_active_runs=1,
        max_queued_runs=10,
        max_retained_runs=100,
        run_timeout_seconds=run_timeout_seconds,
        approval_timeout_seconds=600,
    )


async def wait_for_container(before: list[str]) -> list[str]:
    """Wait until a new sandbox container really exists, then return the list."""
    for _ in range(300):
        containers = sandbox_containers()
        if len(containers) > len(before):
            return containers
        await asyncio.sleep(0.05)
    raise AssertionError("no sandbox container appeared")


async def wait_for_stage(runs: RunManager, run_id: str, stage: str) -> None:
    for _ in range(600):
        if runs.get(run_id).stage == stage:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"run never reached {stage}")


def test_run_timeout_removes_the_real_container() -> None:
    before = sandbox_containers()

    async def scenario() -> tuple[str, str, list[str]]:
        runs = looping_run_manager(run_timeout_seconds=4)
        await runs.start()
        try:
            run_id = runs.submit("loop", "python").run_id
            await wait_for_stage(runs, run_id, "executing")
            running_containers = await wait_for_container(before)
            for _ in range(200):
                if runs.get(run_id).status == "failed":
                    break
                await asyncio.sleep(0.05)
            run = runs.get(run_id)
            return run.status, run.error.code, running_containers
        finally:
            await runs.stop()

    status, code, running_containers = asyncio.run(scenario())

    assert (status, code) == ("failed", "run_timeout")
    assert len(running_containers) == len(before) + 1  # A container really was running.
    assert sandbox_containers() == before


def test_shutdown_removes_the_real_container() -> None:
    before = sandbox_containers()

    async def scenario() -> tuple[str, list[str]]:
        runs = looping_run_manager(run_timeout_seconds=300)
        await runs.start()
        run_id = runs.submit("loop", "python").run_id
        await wait_for_stage(runs, run_id, "executing")
        running_containers = await wait_for_container(before)

        await runs.stop()

        return stored(run_id).error.code, running_containers

    code, running_containers = asyncio.run(scenario())

    assert code == "shutdown"
    assert len(running_containers) == len(before) + 1
    assert sandbox_containers() == before


def test_startup_removes_only_real_leftover_containers() -> None:
    # What a crashed process leaves behind: a sandbox container still running.
    leftover = "astraai-sandbox-leftover0"
    # Not ours: the name merely contains the prefix.
    lookalike = "other-astraai-sandbox-0"
    for name in (leftover, lookalike):
        subprocess.run(
            ["docker", "run", "--detach", "--name", name]
            + [Settings().sandbox_python_image, "sleep", "300"],
            check=True,
            capture_output=True,
        )
    try:
        asyncio.run(DockerSandbox(Settings()).remove_leftovers())

        remaining = sandbox_containers()
        assert leftover not in remaining
        assert lookalike in remaining
    finally:
        subprocess.run(
            ["docker", "rm", "--force", leftover, lookalike],
            capture_output=True,
            check=False,
        )


# DEVELOP: a repository's own tests, on the pinned image, exactly as they are.

SANDBOX_IMAGE_DIR = Path(__file__).resolve().parents[1] / "sandbox"


@pytest.fixture(scope="module")
def develop_image() -> None:
    """Build the DEVELOP image if needed. Only the build uses the network, never a run."""
    subprocess.run(
        ["docker", "build", "-q", "-t", Settings().sandbox_develop_image]
        + [str(SANDBOX_IMAGE_DIR)],
        check=True,
        capture_output=True,
    )


def repository(files: dict[str, str]) -> ExecutionResult:
    snapshot = {path: text.encode() for path, text in files.items()}
    return asyncio.run(DockerSandbox(Settings()).run_repository(snapshot))


@pytest.mark.usefixtures("develop_image")
def test_a_repositorys_existing_tests_run_as_they_are() -> None:
    result = repository(
        {
            "calc/__init__.py": "def add(a, b):\n    return a + b\n",
            "tests/test_calc.py": "from calc import add\n\n\n"
            "def test_add():\n    assert add(1, 2) == 3\n\n\n"
            "def test_wrong():\n    assert add(1, 1) == 3\n",
            # Temp files work, though the root filesystem is read-only.
            "tests/test_tmp.py": "def test_tmp(tmp_path):\n"
            "    (tmp_path / 'f').write_text('x')\n"
            "    assert (tmp_path / 'f').read_text() == 'x'\n",
        }
    )

    assert (result.status, result.error_type) == ("failed", "test_failure")
    assert (result.tests_passed, result.tests_failed) == (2, 1)
    assert "FAILED tests/test_calc.py::test_wrong" in result.stdout
    # Every failure by its pytest id, from the real pytest's own summary.
    assert result.failed_tests == ["tests/test_calc.py::test_wrong"]


@pytest.mark.usefixtures("develop_image")
def test_the_pinned_python_and_pytest_run_with_no_credentials() -> None:
    result = repository(
        {
            "test_environment.py": "import os, sys\n\nimport pytest\n\n\n"
            "def test_versions():\n"
            "    assert sys.version_info[:3] == (3, 12, 14)\n"
            "    assert pytest.__version__ == '9.1.1'\n\n\n"
            "def test_no_credentials():\n"
            "    names = [n for n in os.environ if 'TOKEN' in n or 'GITHUB' in n]\n"
            "    assert names == []\n"
        }
    )

    assert (result.status, result.tests_passed, result.tests_failed) == ("passed", 2, 0)
    assert result.failed_tests == []


@pytest.mark.usefixtures("develop_image")
def test_repository_tests_have_no_network() -> None:
    result = repository(
        {
            "test_network.py": "import socket\n\nimport pytest\n\n\n"
            "def test_no_connection():\n"
            "    with pytest.raises(OSError):\n"
            "        socket.create_connection(('1.1.1.1', 53), timeout=3)\n\n\n"
            "def test_no_dns():\n"
            "    with pytest.raises(OSError):\n"
            "        socket.getaddrinfo('pypi.org', 443)\n"
        }
    )

    assert (result.status, result.tests_passed) == ("passed", 2)


@pytest.mark.usefixtures("develop_image")
def test_dependencies_are_never_installed() -> None:
    result = repository(
        {
            "requirements.txt": "requests==2.32.3\n",
            "pyproject.toml": "[project]\nname = 'x'\nversion = '0'\n"
            "dependencies = ['requests']\n",
            "test_uses_requests.py": "import requests\n\n\ndef test_it():\n    assert requests\n",
        }
    )

    # The import fails at collection: the suite couldn't run here, which is not a
    # test failure.
    assert (result.status, result.error_type) == ("failed", "environment_error")
    assert (result.tests_passed, result.tests_failed) == (None, None)
    assert "No module named 'requests'" in result.stdout
    # What broke is still named, though nothing could be counted.
    assert result.failed_tests == ["test_uses_requests.py"]


@pytest.mark.usefixtures("develop_image")
def test_a_repository_without_tests_is_reported_as_such() -> None:
    result = repository({"README.md": "# nothing to test\n"})

    assert (result.status, result.exit_code) == ("passed", 5)
    assert (result.tests_passed, result.tests_failed) == (0, 0)


@pytest.mark.usefixtures("develop_image")
def test_repository_runs_leave_nothing_behind() -> None:
    before = sandbox_containers()

    repository({"test_ok.py": "def test_ok():\n    pass\n"})

    assert sandbox_containers() == before
