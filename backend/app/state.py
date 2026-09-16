from dataclasses import dataclass
from typing import Literal, NotRequired, Self, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.llm import LLMClient
from app.sandbox.executor import SandboxExecutor

Language = Literal["python", "cpp"]
ExecutionStatus = Literal[
    "passed",
    "failed",
    "timed_out",
    "resource_exceeded",
    "infrastructure_error",
]
CaseCategory = Literal[
    "basic",
    "boundary",
    "empty_or_small",
    "duplicates",
    "negative_or_zero",
    "performance",
    "invalid_input",
]


class Requirements(BaseModel):
    """Structured analysis of a coding task."""

    model_config = ConfigDict(extra="forbid")

    problem_summary: str
    functional_requirements: list[str]
    edge_cases: list[str]
    constraints: list[str] = Field(
        description="Limits such as input sizes, time or memory."
    )
    expected_input: str = Field(
        description="Input format, or how the solution is called."
    )
    expected_output: str = Field(
        description="Output format, or what the solution returns."
    )
    relevant_language_requirements: list[str] = Field(
        description="Language-specific needs such as standard version, entry point, libraries."
    )


class GeneratedTestCase(BaseModel):
    """One language-neutral test case.

    Test values are literals in plain string fields: tool calling carries flat strings
    intact, but not nested or JSON-encoded values.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        description="Unique snake_case identifier, e.g. duplicate_values."
    )
    category: CaseCategory
    description: str = Field(description="What the case checks and why it matters.")
    input: str = Field(
        description="Each parameter from `interface` as name = value in JSON notation, "
        'e.g. nums = [2, 7, 11], target = 9 or s = "abc". Leave out parameters that '
        "input_generator builds."
    )
    input_generator: str = Field(
        description="Only for inputs too large to write out: a deterministic recipe that "
        "builds them. Empty string otherwise."
    )
    expected_output: str = Field(
        description='Exact expected result in JSON notation, e.g. [0, 1] or "cba". '
        "For invalid input, the behavior the requirements specify."
    )


class GeneratedTests(BaseModel):
    """Language-neutral test plan that generate_code turns into executable tests."""

    model_config = ConfigDict(extra="forbid")

    interface: str = Field(
        description="How tests invoke the solution, e.g. function two_sum(nums: list of int, "
        "target: int) -> list of int, or a program reading stdin and writing stdout."
    )
    comparison: str = Field(
        description="How to compare actual and expected output, e.g. exact match, "
        "order-insensitive, or any answer satisfying a stated property."
    )
    cases: list[GeneratedTestCase] = Field(min_length=1)

    @model_validator(mode="after")
    def case_names_are_unique(self) -> Self:
        names = [case.name for case in self.cases]
        if len(names) != len(set(names)):
            raise ValueError("test case names must be unique")
        return self


class GeneratedCode(BaseModel):
    """Runnable solution and test code, kept as flat strings for the sandbox to write out.

    Python lands in solution.py and test_solution.py, C++ in solution.cpp and
    test_solution.cpp. The test program exits 0 only when every case passes.
    """

    model_config = ConfigDict(extra="forbid")

    language: Language
    solution_code: str = Field(
        min_length=1,
        description="The implementation only: no test code, no entry point that runs on "
        "import or start-up, no markdown fences.",
    )
    test_code: str = Field(
        min_length=1,
        description="A standalone program that runs every case in the test plan, prints "
        "FAIL <case_name>: expected <expected>, got <actual> for each failure, and exits "
        "non-zero when any case fails. No markdown fences.",
    )
    explanation: str = Field(
        description="Short note on the approach, and any conflict found with the test plan."
    )


class ExecutionResult(BaseModel):
    """What happened when the generated tests ran in the sandbox."""

    model_config = ConfigDict(extra="forbid")

    status: ExecutionStatus
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    tests_passed: int | None = None
    tests_failed: int | None = None
    error_type: str | None = Field(
        default=None,
        description="compile_error, test_failure, runtime_error, timeout, "
        "out_of_memory, or a sandbox infrastructure failure.",
    )
    output_truncated: bool = False


CriticVerdict = Literal[
    "pass", "code_failure", "test_failure", "execution_failure", "ambiguous"
]
RecommendedAction = Literal[
    "accept", "revise_code", "revise_tests", "retry_execution", "needs_human_review"
]


class CriticResult(BaseModel):
    """Judgement of whether the implementation meets the requirements, from the evidence.

    Flat strings only, with nowhere to put replacement code or tests.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: CriticVerdict
    reason: str = Field(
        min_length=1, description="The evidence-based explanation for the verdict."
    )
    code_issue: str = Field(
        description="What the implementation gets wrong, or an empty string."
    )
    test_issue: str = Field(
        description="Which expected result contradicts the requirements and why, "
        "or an empty string."
    )
    recommended_action: RecommendedAction

    @model_validator(mode="after")
    def only_a_pass_is_accepted(self) -> Self:
        if (self.verdict == "pass") != (self.recommended_action == "accept"):
            raise ValueError(
                "recommended_action is accept exactly when verdict is pass"
            )
        return self


class AgentState(TypedDict):
    """State shared by every node of an AstraAi run."""

    run_id: str
    task: str
    language: Language
    requirements: NotRequired[Requirements]
    generated_tests: NotRequired[GeneratedTests]
    generated_code: NotRequired[GeneratedCode]
    execution_result: NotRequired[ExecutionResult]
    critic_result: NotRequired[CriticResult]
    attempt_count: NotRequired[int]
    max_attempts: NotRequired[int]
    status: NotRequired[Literal["pending", "running", "succeeded", "failed"]]
    errors: NotRequired[list[str]]


@dataclass(frozen=True)
class GraphContext:
    """Run-scoped dependencies for nodes, kept out of the graph state."""

    llm: LLMClient
    sandbox: SandboxExecutor
