"""Runs generated code in a throwaway, locked-down Docker container."""

import asyncio
import contextlib
import io
import logging
import re
import tarfile
import time
from asyncio.subprocess import PIPE
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from uuid import uuid4

from app.config import Settings
from app.sandbox.executor import (
    COMPILE_FAILURE_EXIT,
    LANGUAGES,
    REPOSITORY_COMMAND,
    REPOSITORY_MEMORY_MB,
    REPOSITORY_PIDS_LIMIT,
    REPOSITORY_SCRATCH_MB,
    REPOSITORY_TIMEOUT_SECONDS,
    REPOSITORY_TMP,
    SCRATCH_DIR,
    LanguageSpec,
)
from app.state import ExecutionResult, GeneratedCode

logger = logging.getLogger(__name__)

PASSED_TESTS = re.compile(r"^PASSED (\d+) tests", re.MULTILINE)
FAILED_CASE = re.compile(r"^FAIL ", re.MULTILINE)
# pytest's last line, e.g. "126 passed, 2 failed, 1 skipped in 3.10s".
PYTEST_COUNT = re.compile(r"(\d+) (passed|failed|errors?)\b")
# pytest exit codes: 0 all passed, 1 some failed, 5 no tests collected. Anything else
# (collection errors, internal or usage errors, no pytest) means the suite couldn't run.
PYTEST_FAILED = 1
PYTEST_NO_TESTS = 5
INSPECT_FORMAT = (
    "{{.State.ExitCode}} {{.State.OOMKilled}} {{.State.Running}} {{.State.StartedAt}}"
)
# Docker's zero time: the container's process was never started.
NEVER_STARTED = "0001-01-01T00:00:00Z"
CONTAINER_PREFIX = "astraai-sandbox-"


@dataclass(frozen=True)
class Completed:
    """Result of one docker CLI call."""

    code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ContainerState:
    """What docker inspect reports about a container after the attached run ends."""

    exit_code: int
    out_of_memory: bool
    running: bool
    started: bool


@dataclass(frozen=True)
class Run:
    """Output of the container itself."""

    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool


async def read_capped(
    stream: asyncio.StreamReader, limit: int, *, tail: bool = False
) -> tuple[str, bool]:
    """Read a stream, keeping at most limit bytes but draining the rest.

    Keeps the start by default; with tail, the end, where a test runner's summary is.
    """
    kept = bytearray()
    size = 0
    while True:
        chunk = await stream.read(8192)
        if not chunk:
            break
        if tail:
            kept += chunk
            del kept[:-limit]
        elif size < limit:
            kept += chunk[: limit - size]
        size += len(chunk)
    return kept.decode("utf-8", errors="replace"), size > limit


def parse_state(inspected: str) -> ContainerState | None:
    """Parse INSPECT_FORMAT output; None if it is not what Docker should print."""
    parts = inspected.split()
    if len(parts) != 4:
        return None
    exit_text, oom_text, running_text, started_at = parts
    try:
        exit_code = int(exit_text)
    except ValueError:
        return None
    return ContainerState(
        exit_code=exit_code,
        out_of_memory=oom_text == "true",
        running=running_text == "true",
        started=started_at != NEVER_STARTED,
    )


def pack(files: Iterable[tuple[str, bytes]], mode: int) -> bytes:
    """A tar of regular files, built in memory, for the container to unpack from stdin."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for filename, data in files:
            entry = tarfile.TarInfo(filename)
            entry.size = len(data)
            entry.mode = mode
            archive.addfile(entry, io.BytesIO(data))
    return buffer.getvalue()


def build_archive(spec: LanguageSpec, generated_code: GeneratedCode) -> bytes:
    """Pack the generated files into a tar the container unpacks from stdin."""
    return pack(
        [
            (spec.solution_file, generated_code.solution_code.encode("utf-8")),
            (spec.test_file, generated_code.test_code.encode("utf-8")),
        ],
        0o444,
    )


def pytest_result(
    run: "Run", exit_code: int, out_of_memory: bool, elapsed_ms: int
) -> ExecutionResult:
    """What a repository's own pytest run showed, from its exit code and summary line."""
    lines = run.stdout.strip().splitlines()
    counts: dict[str, int] = {}
    for number, kind in PYTEST_COUNT.findall(lines[-1] if lines else ""):
        counts["error" if kind.startswith("error") else kind] = int(number)
    if run.timed_out:
        status, error_type = "timed_out", "timeout"
    elif out_of_memory:
        status, error_type = "resource_exceeded", "out_of_memory"
    elif exit_code in (0, PYTEST_NO_TESTS):
        status, error_type = "passed", None
    elif exit_code == PYTEST_FAILED:
        status, error_type = "failed", "test_failure"
    else:
        status, error_type = "failed", "environment_error"
    # Counts only mean something when the suite ran to its end.
    finished = status == "passed" or error_type == "test_failure"
    return ExecutionResult(
        status=status,
        exit_code=exit_code,
        stdout=run.stdout,
        stderr=run.stderr,
        duration_ms=elapsed_ms,
        tests_passed=counts.get("passed", 0) if finished else None,
        tests_failed=counts.get("failed", 0) + counts.get("error", 0)
        if finished
        else None,
        error_type=error_type,
        output_truncated=run.truncated,
    )


class DockerSandbox:
    """One ephemeral container per execution, with no network and no host mounts."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._images = {
            "python": settings.sandbox_python_image,
            "cpp": settings.sandbox_cpp_image,
        }
        self._slot = asyncio.Semaphore(settings.sandbox_max_concurrency)

    async def execute(self, generated_code: GeneratedCode) -> ExecutionResult:
        spec = LANGUAGES.get(generated_code.language)
        if spec is None:
            raise ValueError(f"unsupported sandbox language: {generated_code.language}")
        if not generated_code.solution_code.strip():
            raise ValueError("solution code is empty")
        if not generated_code.test_code.strip():
            raise ValueError("test code is empty")
        async with self._slot:
            return await self._execute_in_container(spec, generated_code)

    async def run_repository(self, files: Mapping[str, bytes]) -> ExecutionResult:
        """Run a repository's existing tests, unchanged, with nothing installed."""
        archive = pack(sorted(files.items()), 0o644)
        async with self._slot:
            return await self._run_container(
                self.repository_args,
                archive,
                pytest_result,
                timeout=REPOSITORY_TIMEOUT_SECONDS,
                tail=True,
            )

    def container_args(self, name: str, spec: LanguageSpec, language: str) -> list[str]:
        """The docker create command, including every sandbox restriction."""
        settings = self._settings
        return self._create_args(
            name,
            image=self._images[language],
            command=spec.command,
            scratch=f"{spec.scratch_dir}:{spec.scratch_options},"
            f"size={settings.sandbox_scratch_mb}m",
            memory_mb=settings.sandbox_memory_mb,
            pids=settings.sandbox_pids_limit,
        )

    def repository_args(self, name: str) -> list[str]:
        """The same restrictions, with room for a repository and its tests' temp files."""
        python = LANGUAGES["python"]
        return self._create_args(
            name,
            image=self._settings.sandbox_develop_image,
            command=REPOSITORY_COMMAND,
            scratch=f"{SCRATCH_DIR}:{python.scratch_options},size={REPOSITORY_SCRATCH_MB}m",
            memory_mb=REPOSITORY_MEMORY_MB,
            pids=REPOSITORY_PIDS_LIMIT,
            env=(f"TMPDIR={REPOSITORY_TMP}",),
        )

    def _create_args(
        self,
        name: str,
        *,
        image: str,
        command: str,
        scratch: str,
        memory_mb: int,
        pids: int,
        env: tuple[str, ...] = (),
    ) -> list[str]:
        settings = self._settings
        memory = f"{memory_mb}m"
        extra_env = [arg for value in env for arg in ("--env", value)]
        return [
            "create",
            # Keep stdin open: the code arrives as a tar on it.
            "--interactive",
            "--name",
            name,
            "--network",
            "none",
            "--user",
            settings.sandbox_user,
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "--read-only",
            "--tmpfs",
            scratch,
            "--pids-limit",
            str(pids),
            "--cpus",
            str(settings.sandbox_cpu_limit),
            "--memory",
            memory,
            "--memory-swap",
            memory,
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            f"HOME={SCRATCH_DIR}",
            *extra_env,
            "--workdir",
            SCRATCH_DIR,
            image,
            "sh",
            "-c",
            command,
        ]

    async def _execute_in_container(
        self, spec: LanguageSpec, generated_code: GeneratedCode
    ) -> ExecutionResult:
        return await self._run_container(
            lambda name: self.container_args(name, spec, generated_code.language),
            build_archive(spec, generated_code),
            self._result,
            timeout=self._settings.sandbox_timeout_seconds,
            tail=False,
        )

    async def _run_container(
        self,
        create_args: Callable[[str], list[str]],
        archive: bytes,
        interpret: Callable[["Run", int, bool, int], ExecutionResult],
        *,
        timeout: float,
        tail: bool,
    ) -> ExecutionResult:
        """Create, feed and wait for one container, and always remove it."""
        name = f"{CONTAINER_PREFIX}{uuid4().hex[:12]}"
        started = time.perf_counter()
        try:
            created = await self._docker(*create_args(name))
            if created.code != 0:
                return self._infrastructure("container_create_failed", created, started)
            run = await self._start(name, archive, timeout=timeout, tail=tail)
            inspected = await self._docker("inspect", "--format", INSPECT_FORMAT, name)
            state = parse_state(inspected.stdout) if inspected.code == 0 else None
            if state is None:
                # Without the container's state there is no trustworthy outcome.
                return self._infrastructure(
                    "container_inspect_failed", inspected, started
                )
            # In both cases below the attached stderr is the Docker CLI's, not the program's.
            if not state.started:
                failure = Completed(state.exit_code, "", run.stderr)
                return self._infrastructure("container_start_failed", failure, started)
            if state.running and not run.timed_out:
                failure = Completed(state.exit_code, "", run.stderr)
                return self._infrastructure("container_attach_failed", failure, started)
            return interpret(
                run, state.exit_code, state.out_of_memory, self._elapsed_ms(started)
            )
        finally:
            # Shielded: a second cancellation must not abort removing the container.
            await asyncio.shield(self._cleanup(name))

    async def remove_leftovers(self) -> None:
        """Remove sandbox containers left behind by a process that ended without cleanup.

        Call once at startup, before any run executes. Their executions are never continued:
        the process that enforced their timeout and waited for their output is gone.

        Only names starting with CONTAINER_PREFIX match (Docker matches the name with its
        leading slash, unanchored unless told otherwise). One AstraAi process owns that
        namespace on a Docker daemon: a second instance on the same daemon would lose its
        running sandboxes whenever this one starts.
        """
        listed = await self._docker(
            "ps", "--all", "--quiet", "--filter", f"name=^/{CONTAINER_PREFIX}"
        )
        if listed.code != 0:
            logger.warning("could not list leftover sandbox containers")
            return
        leftovers = listed.stdout.split()
        if not leftovers:
            return
        logger.warning("removing %d leftover sandbox container(s)", len(leftovers))
        removed = await self._docker("rm", "--force", "--volumes", *leftovers)
        if removed.code != 0:
            logger.warning("leftover sandbox containers were not all removed")

    async def _docker(self, *args: str) -> Completed:
        try:
            process = await asyncio.create_subprocess_exec(
                "docker", *args, stdout=PIPE, stderr=PIPE
            )
        except FileNotFoundError as exc:
            return Completed(127, "", f"docker CLI unavailable: {exc}")
        stdout, stderr = await process.communicate()
        return Completed(
            process.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async def _start(
        self, name: str, archive: bytes, *, timeout: float, tail: bool
    ) -> Run:
        limit = self._settings.sandbox_max_output_bytes
        process = await asyncio.create_subprocess_exec(
            "docker",
            "start",
            "--attach",
            "--interactive",
            name,
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE,
        )
        await self._send_archive(process, archive)
        streams = asyncio.gather(
            asyncio.create_task(read_capped(process.stdout, limit, tail=tail)),
            asyncio.create_task(read_capped(process.stderr, limit, tail=tail)),
        )
        timed_out = False
        try:
            await asyncio.wait_for(asyncio.shield(streams), timeout)
        except TimeoutError:
            timed_out = True
            await self._docker("kill", name)
        except asyncio.CancelledError:
            # The run was cancelled (run timeout or shutdown): stop reading and stop the
            # docker client. The caller's finally still removes the container.
            streams.cancel()
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            # Collect the cancelled readers so asyncio does not warn about them; the
            # original cancellation is re-raised either way.
            with contextlib.suppress(asyncio.CancelledError):
                await streams
            raise
        (stdout, out_cut), (stderr, err_cut) = await streams
        await process.wait()
        return Run(stdout, stderr, timed_out, out_cut or err_cut)

    @staticmethod
    async def _send_archive(process: object, archive: bytes) -> None:
        """Hand the code to the container on stdin; it may already have exited."""
        stdin = getattr(process, "stdin", None)
        if stdin is None:
            return
        try:
            stdin.write(archive)
            await stdin.drain()
            stdin.close()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    async def _cleanup(self, name: str) -> None:
        """Remove the container. No host workspace exists: the code only ever
        lived in the tar on stdin and in the container tmpfs."""
        removed = await self._docker("rm", "--force", "--volumes", name)
        if removed.code != 0:
            logger.warning(
                "sandbox container %s was not removed: %s",
                name,
                removed.stderr.strip()[:200],
            )

    def _infrastructure(
        self, error_type: str, failure: Completed, started: float
    ) -> ExecutionResult:
        # Docker's own diagnostics are internal: logged here, never put in the result,
        # which the API returns and later steps may read. stdout and stderr stay empty.
        logger.warning("sandbox %s: %s", error_type, failure.stderr.strip()[:200])
        return ExecutionResult(
            status="infrastructure_error",
            exit_code=failure.code,
            duration_ms=self._elapsed_ms(started),
            error_type=error_type,
        )

    def _result(
        self, run: Run, exit_code: int, out_of_memory: bool, elapsed_ms: int
    ) -> ExecutionResult:
        passed = PASSED_TESTS.search(run.stdout)
        failed = len(FAILED_CASE.findall(run.stdout))
        if run.timed_out:
            status, error_type = "timed_out", "timeout"
        elif out_of_memory:
            status, error_type = "resource_exceeded", "out_of_memory"
        elif exit_code == 0:
            status, error_type = "passed", None
        elif exit_code == COMPILE_FAILURE_EXIT:
            status, error_type = "failed", "compile_error"
        else:
            status = "failed"
            error_type = "test_failure" if failed else "runtime_error"
        return ExecutionResult(
            status=status,
            exit_code=exit_code,
            stdout=run.stdout,
            stderr=run.stderr,
            duration_ms=elapsed_ms,
            tests_passed=int(passed.group(1)) if passed else None,
            tests_failed=failed if (failed or passed) else None,
            error_type=error_type,
            output_truncated=run.truncated,
        )

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)
