"""The sandbox contract: what a runner must offer, and how each language is laid out.

Code reaches the container as a tar on stdin and is unpacked into a writable tmpfs, so
the container needs no host mount and its root filesystem can stay read-only.

Nothing here imports app.state at runtime, so app.state can depend on this module.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.state import ExecutionResult, GeneratedCode

# Exit code the shell uses when compilation fails, to tell it apart from failing tests.
COMPILE_FAILURE_EXIT = 90
SCRATCH_DIR = "/sandbox"


@dataclass(frozen=True)
class LanguageSpec:
    """File names, scratch space and command used to run one language."""

    solution_file: str
    test_file: str
    scratch_dir: str
    scratch_options: str
    command: str


LANGUAGES: dict[str, LanguageSpec] = {
    "python": LanguageSpec(
        solution_file="solution.py",
        test_file="test_solution.py",
        scratch_dir=SCRATCH_DIR,
        # No exec: Python reads its sources, it never runs a file from here.
        scratch_options="rw,nosuid,nodev,noexec,mode=1777",
        command=f"cd {SCRATCH_DIR} && tar -x && exec python test_solution.py",
    ),
    "cpp": LanguageSpec(
        solution_file="solution.cpp",
        test_file="test_solution.cpp",
        scratch_dir=SCRATCH_DIR,
        # Exec is needed here and only here: the compiled test binary lives in the tmpfs.
        scratch_options="rw,nosuid,nodev,exec,mode=1777",
        command=(
            f"cd {SCRATCH_DIR} && tar -x && "
            f"{{ g++ -std=c++17 -O1 test_solution.cpp -o {SCRATCH_DIR}/tests || "
            f"exit {COMPILE_FAILURE_EXIT}; }} && exec {SCRATCH_DIR}/tests"
        ),
    ),
}


class SandboxExecutor(Protocol):
    """Runs generated code in isolation and reports what happened."""

    async def execute(self, generated_code: "GeneratedCode") -> "ExecutionResult": ...
