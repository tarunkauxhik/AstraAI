from typing import Any, Literal, NotRequired, TypedDict


class AgentState(TypedDict):
    """State shared by every node of an AstraAi run."""

    run_id: str
    task: str
    language: str
    max_attempts: int
    attempt_count: int
    status: Literal["pending", "running", "succeeded", "failed"]
    errors: list[str]
    requirements: NotRequired[list[str]]
    generated_tests: NotRequired[str]
    generated_code: NotRequired[str]
    execution_result: NotRequired[dict[str, Any]]
    critic_result: NotRequired[dict[str, Any]]
