from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from app.llm import LLMClient

Language = Literal["python", "cpp"]


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


class AgentState(TypedDict):
    """State shared by every node of an AstraAi run."""

    run_id: str
    task: str
    language: Language
    requirements: NotRequired[Requirements]
    generated_tests: NotRequired[str]
    generated_code: NotRequired[str]
    execution_result: NotRequired[dict[str, Any]]
    critic_result: NotRequired[dict[str, Any]]
    attempt_count: NotRequired[int]
    max_attempts: NotRequired[int]
    status: NotRequired[Literal["pending", "running", "succeeded", "failed"]]
    errors: NotRequired[list[str]]


@dataclass(frozen=True)
class GraphContext:
    """Run-scoped dependencies for nodes, kept out of the graph state."""

    llm: LLMClient
