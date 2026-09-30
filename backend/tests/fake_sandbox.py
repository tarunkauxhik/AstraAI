"""Test doubles for the sandbox: a stub executor, and a fake docker CLI."""

import asyncio
import io
import tarfile
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.state import ExecutionResult, GeneratedCode

PASSED = ExecutionResult(
    status="passed",
    exit_code=0,
    stdout="PASSED 3 tests\n",
    duration_ms=12,
    tests_passed=3,
    tests_failed=0,
)


# What pytest reports for a repository whose one test passes.
TESTS_PASSED = ExecutionResult(
    status="passed",
    exit_code=0,
    stdout="tests/test_add.py .\n1 passed in 0.01s\n",
    tests_passed=1,
    tests_failed=0,
)


class FakeSandbox:
    """Executor stub: records what it was asked to run and replays one result."""

    def __init__(
        self,
        result: ExecutionResult | Exception = PASSED,
        repository_result: ExecutionResult | Exception = TESTS_PASSED,
    ) -> None:
        self._result = result
        self._repository_result = repository_result
        self.calls: list[GeneratedCode] = []
        self.repositories: list[dict[str, bytes]] = []

    async def execute(self, generated_code: GeneratedCode) -> ExecutionResult:
        self.calls.append(generated_code)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    async def run_repository(self, files: Mapping[str, bytes]) -> ExecutionResult:
        self.repositories.append(dict(files))
        if isinstance(self._repository_result, Exception):
            raise self._repository_result
        return self._repository_result


class FakeStream:
    """Byte stream that can be held open until the container is killed."""

    def __init__(self, data: bytes, release: asyncio.Event | None = None) -> None:
        self._data = data
        self._release = release
        self._done = False

    async def read(self, size: int = -1) -> bytes:
        if self._done:
            return b""
        if self._release is not None and not self._release.is_set():
            await self._release.wait()
        self._done = True
        return self._data


class FakeWriter:
    """Collects whatever the executor sends to the container on stdin."""

    def __init__(self) -> None:
        self.written = bytearray()

    def write(self, data: bytes) -> None:
        self.written.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None


class FakeProcess:
    def __init__(
        self,
        returncode: int = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
        release: asyncio.Event | None = None,
    ) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.stdout = FakeStream(stdout, release)
        self.stderr = FakeStream(stderr, release)
        self.stdin = FakeWriter()
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    async def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self.killed = True


@dataclass
class FakeDockerCli:
    """Stands in for asyncio.create_subprocess_exec and replays docker results."""

    stdout: bytes = b""
    stderr: bytes = b""
    exit_code: int = 0
    out_of_memory: bool = False
    # Docker could not start the process (an OCI runtime error, for example).
    never_started: bool = False
    # The attached client ended while the container kept running.
    still_running: bool = False
    hang: bool = False
    failing: tuple[str, ...] = ()
    # What `docker ps` lists: container ids left over from an earlier process.
    listed: bytes = b""
    commands: list[list[str]] = field(default_factory=list)
    archive: bytes = b""
    released: asyncio.Event = field(default_factory=asyncio.Event)

    async def __call__(self, program: str, *args: str, **kwargs: object) -> FakeProcess:
        assert program == "docker", f"the sandbox must only run docker, got {program}"
        self.commands.append([program, *args])
        subcommand = args[0]
        if subcommand in self.failing:
            return FakeProcess(1, b"", b"docker refused")
        if subcommand == "start":
            started = FakeProcess(
                0, self.stdout, self.stderr, self.released if self.hang else None
            )
            self._started = started
            return started
        if subcommand == "inspect":
            started_at = (
                "0001-01-01T00:00:00Z" if self.never_started else "2026-01-01T00:00:00Z"
            )
            state = " ".join(
                [
                    str(self.exit_code),
                    "true" if self.out_of_memory else "false",
                    "true" if self.still_running else "false",
                    started_at,
                ]
            )
            return FakeProcess(0, state.encode())
        if subcommand == "ps":
            return FakeProcess(0, self.listed)
        if subcommand == "kill":
            self.released.set()
        return FakeProcess(0)

    def ran(self, subcommand: str) -> list[list[str]]:
        return [command for command in self.commands if command[1] == subcommand]

    @property
    def sent_archive(self) -> bytes:
        started = getattr(self, "_started", None)
        return bytes(started.stdin.written) if started else b""

    def archive_names(self) -> list[str]:
        """File names the executor streamed into the container."""
        if not self.sent_archive:
            return []
        with tarfile.open(fileobj=io.BytesIO(self.sent_archive)) as archive:
            return sorted(archive.getnames())


FAILED = ExecutionResult(
    status="failed",
    exit_code=1,
    stdout="FAIL basic_word: expected cba, got abc\n",
    tests_failed=1,
    error_type="test_failure",
)
INFRASTRUCTURE_ERROR = ExecutionResult(
    status="infrastructure_error",
    exit_code=1,
    error_type="container_create_failed",
)


class ScriptedSandbox(FakeSandbox):
    """Executor stub replaying results in order and repeating the last one.

    `calls` records exactly which code was executed each time.
    """

    def __init__(self, *results: ExecutionResult) -> None:
        super().__init__(results[-1])
        self._results = list(results)

    async def execute(self, generated_code: GeneratedCode) -> ExecutionResult:
        self.calls.append(generated_code)
        return self._results.pop(0) if len(self._results) > 1 else self._results[0]
