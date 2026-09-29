"""Runs generated code in a throwaway, locked-down Docker container."""

import asyncio
import contextlib
import io
import logging
import re
import tarfile
import time
from asyncio.subprocess import PIPE
from dataclasses import dataclass
from uuid import uuid4

from app.config import Settings
from app.sandbox.executor import COMPILE_FAILURE_EXIT, LANGUAGES, LanguageSpec
from app.state import ExecutionResult, GeneratedCode

logger = logging.getLogger(__name__)

PASSED_TESTS = re.compile(r"^PASSED (\d+) tests", re.MULTILINE)
FAILED_CASE = re.compile(r"^FAIL ", re.MULTILINE)
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


async def read_capped(stream: asyncio.StreamReader, limit: int) -> tuple[str, bool]:
    """Read a stream, keeping at most limit bytes but draining the rest."""
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await stream.read(8192)
        if not chunk:
            break
        if size < limit:
            chunks.append(chunk[: limit - size])
        size += len(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace"), size > limit


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


def build_archive(spec: LanguageSpec, generated_code: GeneratedCode) -> bytes:
    """Pack the generated files into a tar the container unpacks from stdin."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for filename, text in (
            (spec.solution_file, generated_code.solution_code),
            (spec.test_file, generated_code.test_code),
        ):
            data = text.encode("utf-8")
            entry = tarfile.TarInfo(filename)
            entry.size = len(data)
            entry.mode = 0o444
            archive.addfile(entry, io.BytesIO(data))
    return buffer.getvalue()


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

    def container_args(self, name: str, spec: LanguageSpec, language: str) -> list[str]:
        """The docker create command, including every sandbox restriction."""
        settings = self._settings
        memory = f"{settings.sandbox_memory_mb}m"
        scratch_size = f"size={settings.sandbox_scratch_mb}m"
        scratch = f"{spec.scratch_dir}:{spec.scratch_options},{scratch_size}"
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
            str(settings.sandbox_pids_limit),
            "--cpus",
            str(settings.sandbox_cpu_limit),
            "--memory",
            memory,
            "--memory-swap",
            memory,
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            f"HOME={spec.scratch_dir}",
            "--workdir",
            spec.scratch_dir,
            self._images[language],
            "sh",
            "-c",
            spec.command,
        ]

    async def _execute_in_container(
        self, spec: LanguageSpec, generated_code: GeneratedCode
    ) -> ExecutionResult:
        name = f"{CONTAINER_PREFIX}{uuid4().hex[:12]}"
        archive = build_archive(spec, generated_code)
        started = time.perf_counter()
        try:
            created = await self._docker(
                *self.container_args(name, spec, generated_code.language)
            )
            if created.code != 0:
                return self._infrastructure("container_create_failed", created, started)
            run = await self._start(name, archive)
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
            return self._result(run, state.exit_code, state.out_of_memory, started)
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

    async def _start(self, name: str, archive: bytes) -> Run:
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
            asyncio.create_task(read_capped(process.stdout, limit)),
            asyncio.create_task(read_capped(process.stderr, limit)),
        )
        timed_out = False
        try:
            await asyncio.wait_for(
                asyncio.shield(streams), self._settings.sandbox_timeout_seconds
            )
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
        self, run: Run, exit_code: int, out_of_memory: bool, started: float
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
            duration_ms=self._elapsed_ms(started),
            tests_passed=int(passed.group(1)) if passed else None,
            tests_failed=failed if (failed or passed) else None,
            error_type=error_type,
            output_truncated=run.truncated,
        )

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)
