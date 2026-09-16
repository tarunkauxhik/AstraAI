"""Opt-in checks that use the real local Docker daemon.

Run with ASTRAAI_DOCKER_TESTS=1. Never part of the normal test run.
"""

import asyncio
import os
import subprocess

import pytest

from app.config import Settings
from app.sandbox.docker import DockerSandbox
from app.state import ExecutionResult, GeneratedCode

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
