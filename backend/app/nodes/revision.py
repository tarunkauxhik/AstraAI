"""What both revision nodes share: the required evidence, the budget guard and the prompt."""

from app.repair import MAX_REVISIONS
from app.state import AgentState

REQUIRED_STATE = (
    "requirements",
    "generated_tests",
    "generated_code",
    "execution_result",
    "critic_result",
)


def revision_count_before(state: AgentState, node: str) -> int:
    """Validate a revision may run, and return how many revisions happened before it."""
    missing = [key for key in REQUIRED_STATE if state.get(key) is None]
    if missing:
        raise ValueError(f"{node} needs {', '.join(missing)} from earlier nodes")
    count = state.get("revision_count", 0)
    if count >= MAX_REVISIONS:
        raise ValueError(
            f"{node} has no revision budget left ({count} of {MAX_REVISIONS})"
        )
    return count


def revision_prompt(state: AgentState) -> str:
    """The latest artifacts and the diagnosis of what went wrong with them."""
    code = state["generated_code"]
    return (
        f"Language: {state['language']}\n\n"
        f"Task:\n{state['task']}\n\n"
        f"Requirements:\n{state['requirements'].model_dump_json(indent=2)}\n\n"
        f"Test plan:\n{state['generated_tests'].model_dump_json(indent=2)}\n\n"
        f"Current solution code:\n{code.solution_code}\n\n"
        f"Current test code:\n{code.test_code}\n\n"
        "Latest execution result:\n"
        f"{state['execution_result'].model_dump_json(indent=2)}\n\n"
        f"Reviewer's diagnosis:\n{state['critic_result'].model_dump_json(indent=2)}"
    )
